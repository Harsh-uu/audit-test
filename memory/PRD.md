# Supervision 2.0 — PRD

## Original Problem Statement
A web-based app for care providers that records meetings on demand, generates a post-meeting
transcript and summary, and maps discussion points to regulatory standards. Requirements: secure
login, meeting creation, recording, post-meeting transcription, AI-generated summary/actions/risks/
achievements, evidence mapping, PDF export, Super Admin layer, background async processing queue,
transcript find & replace, segregated inspection pages, organisation sub-tenant hierarchy.

## Stack
React (Vite prod build, hot reload OFF) + FastAPI + PostgreSQL (asyncpg) + Supabase Storage.
AI: Google Cloud Vertex AI (Gemini 2.5 Flash), OpenAI GPT-4o fallback.

## Dead/dangerous manual RLS script removed (Sep 2026)
`/app/backend/supabase_rls_policy.sql` was a stale "run by hand in Supabase Dashboard" script
(referenced in README.md) that had drifted from the real automatic schema (`migrations/`):
it granted/created RLS on `refresh_tokens`, a table `m003_grants_indexes.py` intentionally
`DROP TABLE IF EXISTS`'d — confirmed not present live. Worse, its policies compared
`org_id = current_setting(...)` as plain text against columns that are now native `UUID`
(Phase 2 migration), missing the `NULLIF(...,'')::uuid` cast the real policies use — would
throw `operator does not exist: uuid = text` on nearly every `CREATE POLICY` if run today.
Deleted the file (no code imports/references it — grep-confirmed) and removed the
README "apply RLS manually" step + file-tree entries; RLS is fully applied automatically by
`create_schema()`/`migrations/` on backend startup, so the manual step was both broken and
redundant. Zero functional change — backend/frontend confirmed still healthy after removal.

## Schema Migration Ledger Refactor (Sep 2026) — COMPLETE, verified
Replaced the monolithic 1095-line `init_db.py` (156 idempotent SQL statements re-evaluated on
every backend boot) with a versioned migration system:
- **New `/app/backend/migrations/` package**: 7 ordered chunks (`m001_core_tables` ..
  `m007_data_cleanup`), each exposing `VERSION` + `async def up(conn)`. Every SQL statement was
  copied **verbatim** from the old monolithic script (AST-diff-verified zero drift by
  testing_agent) — this was a pure structural refactor, no functional/business-logic change.
- **`schema_migrations` ledger table** (`version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ`):
  `migrations/__init__.py::run_migrations()` creates it, reads applied versions, and only runs
  chunks not yet in the ledger (each chunk's `up()` + its ledger INSERT share one
  `conn.transaction()`, so a mid-chunk failure can't record a half-applied version).
  `init_db.py::create_schema()` keeps its exact signature (`server.py`'s `from init_db import
  create_schema` untouched) — it now just calls `run_migrations(conn)` internally.
- **First-boot catch-up**: since this DB already had every statement applied historically, all 7
  chunks ran once more on first boot after deploy (safe — fully idempotent) and got recorded;
  every boot since then applies zero chunks (confirmed via 2 consecutive real supervisor
  restarts — no "Applied migration" log lines, `schema_migrations` still has exactly 7 rows).
- **4 pre-existing static tests** (`test_processing_error_iter58.py`,
  `test_prep_context_bug_fix.py`, `test_iter101_meetings_index_regression.py`) that did raw
  string-search assertions against `init_db.py`'s source were updated to scan the new
  `migrations/` directory instead, so their schema-guard checks keep working.
- **Drift fix while here**: `meetings.processing_error` existed live in the DB but was never
  created by any migration statement (pre-existing gap, inherited from the old script, not
  introduced by this refactor) — added `ALTER TABLE meetings ADD COLUMN IF NOT EXISTS
  processing_error TEXT` to `m002_schema_patches.py` so a fresh database now matches.
- **Verified via testing_agent** (iteration_111): 27/27 new regression tests (ledger contents,
  25 tables/21 RLS policies/38 FK constraints/composite index all present, auth, dashboard,
  meeting create/get/delete, org settings/teams CRUD, portfolio/standards, malformed-UUID 404,
  transcript/analysis round-trip) + full UI smoke (login, dashboard, org structure, settings,
  portfolio, standards library, meeting report, meeting creation, team creation) — zero
  regressions attributable to the refactor. `pytest --collect-only` across all 1158 backend
  tests found zero import errors from the new `migrations` package.
- **Not actioned** (code-review suggestions, low priority): no content-hash/checksum on applied
  migrations (editing an already-applied chunk silently never re-runs on existing DBs — by
  design for this lightweight ledger, but worth a checksum warning later); no `pg_advisory_lock`
  around `run_migrations()` (fine for single-replica boots, would matter for multi-replica).

## Post-Phase-2 fixes (Sep 2026) — Edit Setting race, FK indexes, date validation
Follow-up to Phase 2, 4 items requested together:
1. **Edit Setting/Team stale-form race condition — FIXED**: `OrgStructure.js`'s
   `refreshData()` is now `async` and every mutation handler (`saveSetting`, `saveTeam`,
   `saveEditUser`, `inviteUser`, `deleteSetting`, `deleteTeam`) `await`s it before closing its
   modal. Previously the modal closed immediately after the PUT/POST resolved while the
   background refetch was still in flight (~seconds); reopening Edit on the same row in that
   window prefilled stale pre-save data, and saving again silently reverted the change.
2. **18 missing FK-supporting indexes — ADDED** in `init_db.py` (analyses/audio_files/
   audit_logs/evidence_feedback/invitations/meeting_prep/review_edits/reviewer_comments/
   standards_entries/transcripts `.org_id`, `meetings.setting_id/team_id/schedule_id`,
   `org_settings.manager_user_id`, `schedules.meeting_type_id/staff_user_id`,
   `teams.supervisor_user_id`, `evidence_feedback.meeting_id`) — without these, deleting a
   referenced row (org/user/meeting) forced a full table scan of the referencing table to
   find CASCADE/SET NULL matches. Also un-reverted a previously-dropped
   `idx_schedules_staff_user_id` (was dropped for an unrelated SELECT-query-pattern reason;
   re-added here for the FK/cascade-performance reason instead — documented in-file).
3. **Meeting date validation — ADDED**: `CreateMeetingRequest.date` now has a Pydantic
   `field_validator` requiring `datetime.fromisoformat()` to parse it; garbage dates get a
   clean 422 instead of being silently stored or (previously) sometimes crashing.
4. **Bug found by testing_agent (iteration_110) + fixed**: `org.py` `create_team`/
   `update_team` inserted a raw `""` (not `None`) for `supervisor_user_id` when the field was
   omitted/blank, which the UUID column now rejects (500). Normalized to `sup_id =
   data.supervisor_user_id or None` (matching the existing `manager_user_id` pattern used for
   Settings). Proactively found + fixed the identical pattern in `meetings.py` create_meeting
   (`sign_off_manager_id`, `schedule_id` could also be raw `""`).
- **Verified via testing_agent** (iteration_110): Playwright repro of the exact race (edit →
  save → reopen within ~1s → save again) confirmed fixed for both Settings and Teams; date
  validator confirmed rejecting garbage with 422 and accepting valid dates normally; no
  startup errors from the new indexes.
- **Known minor items not fixed** (low priority): malformed-UUID path params still log a full
  traceback to `backend.err.log` before the global 404 handler catches it (cosmetic log noise
  only); `GET /api/admin/standards` 403s for attendees viewing their own portfolio (pre-existing,
  unrelated).

## Phase 2 Data-Type Migration (Sep 2026) — TEXT -> UUID, COMPLETE, verified
Migrated ~75 id/foreign-key columns to native UUID across 22 tables, rebuilding all
39 FK constraints and 21 RLS policies atomically. Same "text-format codec" technique as
Phase 1: `database.py` registers a UUID codec so every `str(uuid.uuid4())` call site
keeps working unchanged, while Postgres now validates/stores real UUIDs at rest.
- **Migration mechanics** (`init_db.py`, new DO block after the Phase 1 block): captures
  every FK's exact definition from `pg_constraint` before dropping (so they're rebuilt
  byte-identical), drops all 21 RLS policies (Postgres refuses to retype a column a policy
  depends on), converts columns, rebuilds FKs + policies (uuid-aware
  `NULLIF(current_setting(...),'')::uuid` cast). All-or-nothing: a DO block failing anywhere
  rolls the whole thing back automatically — safe to retry.
- **Deliberately excluded** (confirmed not uuid-shaped by inspecting both code and live
  data first): `login_attempts.identifier` (composite string), `password_reset_tokens.token`
  / `invitations.token` (`secrets.token_urlsafe(32)`), `evidence_feedback.evidence_item_id`
  (`str(uuid4())[:8]`, truncated), and **`settings.id`/`settings.org_id`** — settings.id is a
  composite string key (`"supervision_template:{org_id}"`), not a UUID at all; found this the
  hard way (see bugs below), so its RLS policy stays a static TEXT-comparison policy and it
  has no FK to organisations.
- **Safety**: dry-ran the full migration SQL in an explicit `BEGIN/ROLLBACK` against the real
  DB first (validated column types, FK/policy counts, RLS filtering) before ever writing it
  into `init_db.py`. Backup from Phase 1 reused to verify zero row loss after (761 rows).
- **Real bugs found (by testing_agent iteration_108) + fixed**:
  1. **Critical**: `settings.id`/`org_id` were wrongly included in the migration (composite
     key, not UUID) — broke `GET/PUT /api/admin/template`. Reverted to TEXT, dropped the
     now-permanently-incompatible `fk_settings_org_id`, restored a static TEXT `settings_rls`.
  2. **Critical**: `routers/portfolio.py` — one bind param ($2) used against both a UUID
     column (`sign_off_manager_id`) and a JSONB `->>'user_id'` text extraction in the same
     query, so Postgres couldn't infer one consistent type. Fixed with explicit `::uuid` /
     `::text` casts per usage. Same pattern found+fixed in `admin.py` (meetings-brief,
     export-evidence, export-transcripts, export-cc-excerpts — 4 endpoints) and
     `super_admin.py` (org-deletion cascade deletes).
  3. Several `= ANY($1::text[])` array casts against now-UUID columns (`teams.setting_id`,
     `users.id`, `users.team_id`, `analyses.id`, `transcripts.id`) across `org.py`, `admin.py`,
     `dashboard.py`, `meetings.py`, `portfolio.py`, `review.py` — changed to `::uuid[]`.
     Left `elem->>'user_id' = ANY($::text[])` (prep.py/transcription_pipeline.py) unchanged —
     those extract from JSONB as text regardless of the referenced column's type.
  4. `org.py` — `team_id IS NULL OR team_id=''` is now structurally invalid (a UUID column can
     never hold `''`); simplified to `team_id IS NULL`.
  5. Minor: malformed-UUID path params (e.g. `GET /api/meetings/not-a-uuid`) 500'd instead of
     404ing — added a global FastAPI `exception_handler` for asyncpg's
     `InvalidTextRepresentationError` → 404.
  6. Hardened `init_db.py`'s Phase-2 column loop: a NOT NULL/primary-key column with non-uuid
     values now `RAISE EXCEPTION`s loudly (caught by the outer handler, whole migration rolls
     back cleanly) instead of silently nulling it and hitting a confusing NOT NULL violation.
- **Verified via testing_agent** (iteration_108 found the bugs above; iteration_109 confirmed
  all 4 fixed — 32/32 regression + 12/12 new confirmation tests, Playwright UI pass for
  Settings→Template full CRUD, My Portfolio for admin+attendee, cross-org RLS isolation
  re-confirmed clean). Cleaned up test-data residue left by testing_agent runs (leftover
  `TEST_iter107` schedules/meeting_types, a `TEST_iter108`-overwritten supervision template,
  two stray `test add`/`TEST Invitee` demo users).
- **Known minor items not fixed** (low priority, logged for later): `GET /api/admin/standards`
  403s for attendees viewing their own portfolio (silently falls back to a 0 count, pre-existing,
  unrelated to this migration); malformed-id paths still emit a full traceback to
  `backend.err.log` before the 404 handler catches it (cosmetic/log-noise only — could type path
  params as `uuid.UUID` for a clean 422 instead).

## Phase 1 Data-Type Migration (Sep 2026) — TEXT -> TIMESTAMPTZ, COMPLETE, verified
Migrated 52 date/time columns across 22 tables from TEXT to TIMESTAMPTZ (organisations,
users, meetings, transcripts, analyses, audio_files, review_edits, reviewer_comments,
standards_entries, standards_documents, login_attempts, password_reset_tokens, invitations,
jobs, audit_logs, org_settings, teams, schedules, meeting_types, meeting_prep,
supervision_uploads, evidence_feedback). Deliberately EXCLUDED (kept TEXT, not full
timestamps): `meetings.date`, `schedules.start_date` (code comment already says "keep as
str"), `supervision_uploads.meeting_date` (date-only), `focus_topics.active_month`
("YYYY-MM" only).
- **Approach** (lower-risk than the original ~90-call-site `.isoformat()` rewrite plan):
  registered a custom asyncpg **text-format codec** for `timestamptz`/`timestamp`
  (`database.py::_encode_timestamp`/`_decode_timestamp`) — encoder passes an ISO-8601 string
  straight through (Postgres's own parser accepts it), decoder normalizes Postgres's text
  output ('YYYY-MM-DD HH:MI:SS+TZ') back to Python's isoformat ('...T...'). Net effect: every
  existing `.isoformat()` string call site keeps working completely unchanged, while the
  column is a real TIMESTAMPTZ at rest — correct chronological sorting, and Postgres itself
  now rejects malformed values at the DB level instead of silently storing bad text.
- **Migration mechanics** (`init_db.py`, new DO block after the FK-constraints section):
  idempotent (checks `information_schema.columns` first, skips if already migrated or column
  doesn't exist), nulls out any value that doesn't match a `YYYY-MM-DD[ T]HH:MI:SS` shape
  before the ALTER (logged via `RAISE WARNING`), and catches any other cast failure per-column
  (warns, leaves that one column as TEXT) so one bad column can't abort the whole migration.
- **Safety**: took a full pre-migration JSON backup of all 22 tables (761 rows) to
  `/app/backups/pre_phase1_timestamptz_backup.json` before running; verified row-count parity
  (761/761) and zero unexpected NULLs after.
- **Real bug found + fixed**: `utils/rate_limit.py` — `locked_until = CASE WHEN ... THEN $4
  ELSE NULL END` lost Postgres's type inference once the column became TIMESTAMPTZ (bare
  parameter + untyped NULL inside a CASE branch defaults to `text`), causing a 500
  (`DatatypeMismatchError`) on every rate-limited endpoint (e.g. `POST /api/meetings/`). Fixed
  with explicit `::timestamptz` casts on both branches (both `check_rate_limit` and
  `record_failed_attempt`). Also fixed the same class of bug in `tests/get_tokens.py` (test
  helper opens its own unpooled connection without the codec).
- **Second bug found by testing_agent + fixed**: `routers/review.py` `update_speaker_text` —
  `existing_t.get("speaker_text_edited_at") or ""` wrote `''` into the now-TIMESTAMPTZ
  `transcripts.speaker_text_backup_at`, 500ing on every speaker-label edit/rename/flip/split
  save (permanently broken from the first edit onward, since the backup path always fires
  once a transcript has any speaker_text). Fixed: `or None`.
- **Verified via testing_agent** (iteration_107): full auth+MFA, failed-login lockout, rapid
  meeting creates through the fixed rate limiter, meetings list ordering/date filters, review
  edits/comments/audit-trail/signoff/reopen, org settings/teams/invitations, schedules,
  super-admin org+invite lifecycle, dashboard/admin reads — all clean after the two fixes.
  Manually re-verified the review.py fix directly against a real seeded transcript (both first
  and second speaker-text edits now 200); restored that transcript's original content
  afterward from the pre-migration backup so no seed/demo data was left mutated.
- **Explicitly NOT done this round** (per user instruction — stop after Phase 1 for review):
  Phase 2 (TEXT -> UUID for ID columns + RLS policy rewrites), and all previously-logged P2/P3
  backlog items below.
- Minor items surfaced but not fixed (low priority, logged for later): `meetings.date` accepts
  any garbage string (pre-existing gap, unrelated to this migration, would need Pydantic-level
  validation before ever converting that column); malformed `date_from`/`date_to` query params
  are silently ignored rather than 422 (no 500s, just a correctness smell).

## Session note (Aug 2026): Supabase DB audit mode
User is running a deliberate, field-by-field Supabase/Postgres audit — reports one issue at a time,
requires confirmation + RCA + recommended fix BEFORE any change, then explicit "go ahead" before
implementing. Every fix in this mode is followed by a mandatory testing_agent regression round
(never self-declared fixed). Two Supabase projects exist: preview (`orsxhtlpybxoexdjrbnx`, wired via
backend/.env DATABASE_URL/SUPABASE_URL — this is what code changes here actually affect) and a
"production" one (`niapfxyeynkxxotgzweq`) that this session's backend has never been given
credentials for — schema changes here do NOT propagate there automatically; they'd need either
direct DB password access or a real deploy of this backend pointed at that DB.

### DB audit fixes completed this session (all verified via testing_agent, 0 regressions)
8. **Deletion leaves data behind (High, needed a decision)** — confirmed: (a) `evidence_feedback`
   table was missing from both meeting-deletion and org-deletion manual lists (and I'd missed
   giving it a FK in fix #7) — `meeting_prep` and the org-hierarchy tables (`teams`, `org_settings`,
   `settings`, `focus_topics`, `standards_documents`, `standards_entries`) were already auto-fixed
   as a side effect of #7's FK CASCADE. (b) Audio recordings were NEVER actually deleted from
   Supabase Storage — the full grace-period design existed (sign-off by all attendees + manager →
   `audio_deletion_status='grace_period'` → 5-min task + recovery sweep) but no code anywhere
   called a storage delete; `utils/supabase_storage.py` had no delete function at all. Confirmed
   "signed off by both parties" was already correctly implemented (`sign_off()`'s P3c check blocks
   until every attendee has called mark-reviewed) — no workflow change needed, just wiring.
   User decided: audio deletion must NOT touch transcripts/analyses (kept forever); org deletion =
   "customer leaves, delete everything." Fixed: added real `delete_audio()` (Supabase Storage
   `.remove()`, confirmed this bucket supports it) wired into the existing grace-period task +
   recovery sweep (storage delete happens *before* the DB flag flips, so a storage failure leaves
   the row retryable rather than falsely marking it deleted) and into both `delete_meeting()` and
   `delete_org()` for any audio not yet grace-period-deleted. Added `evidence_feedback.meeting_id`/
   `org_id` FK CASCADE (0 orphans) and added it to both manual lists for defense-in-depth. Verified
   via testing_agent against REAL Supabase Storage (not mocked): 12/12 pass (iteration_106) — upload
   → download → delete → confirmed gone at origin; meeting deletion purges the real object;
   evidence_feedback FK cascade proven with a raw-SQL parent delete; transcript/analysis explicitly
   confirmed untouched by audio deletion; full role smoke clean.
   - Hardened further after 2 minor findings: set `cache-control: no-store` on audio uploads (a
     Supabase CDN edge cache was serving previously-streamed deleted audio for up to 1h after
     purge, origin was always correctly 404 — GDPR timing gap, now closed); dropped an
     `is_deleted=FALSE` filter on the meeting/org-deletion storage-purge queries so a silently-
     failed earlier purge can't be permanently skipped (delete_audio is confirmed idempotent on a
     missing path). Re-verified via the same 12/12 suite after hardening — self-tested (pytest),
     no new testing_agent round needed for this size of follow-up.
   - Not actioned (heavier suite exists but wasn't run for time — `tests/test_iter105_audio_gdpr_delete.py`
     covers the 5-min grace-period timing, storage-failure retry, and full org-deletion e2e in more
     depth; available to run selectively later if needed).
7. **Zero foreign key constraints in the schema (High)** — confirmed 0 FKs existed anywhere;
   every "belongs to" relationship (transcript→meeting, team→org, etc.) was only enforced by hand
   in app code, and this had already caused real drift (3 orphan `audit_logs` rows pointing to
   deleted meetings, found live). User decided: keep `audit_logs.meeting_id` CASCADE (matches
   current app behavior), do it as one coordinated migration. Added **37 FK constraints** across
   the schema in `init_db.py` (idempotent DO blocks, safe to re-run every startup): CASCADE on
   org_id/meeting_id parent-child chains, SET NULL on team/setting/supervisor/manager soft
   references. Cleaned the 3 pre-existing orphan `audit_logs` rows before adding that constraint.
   Deliberately excluded (documented in code comments, has pre-existing orphans or is an
   intentional historical snapshot): `jobs.meeting_id`, `invitations.user_id`,
   `meetings.transcript_id/analysis_id/audio_file_id` (reverse pointers, circular-FK risk),
   `meetings.created_by/sign_off_manager_id` (intentional post-deletion snapshots).
   Hardened the DO blocks to also catch `foreign_key_violation` (log a warning, don't crash boot)
   so this migration can't brick startup on a dirtier DB (e.g. production) that hasn't been
   audited yet. Verified via testing_agent: 38/38 tests — meeting-delete cascade (all 6 child
   tables cleaned, no over-cascade into unrelated orgs), team/setting/user deletion SET NULL
   (no 500s), negative test (bad FK inserts correctly rejected), full role smoke, and a
   real raw-SQL bypass test proving the constraint itself (not just the app code) enforces it
   (iteration_104).
   - Not yet actioned (flagged by testing_agent): several FK child columns have no supporting
     index (review_edits.org_id, standards_entries.org_id, meetings.team_id/setting_id/
     schedule_id, teams.supervisor_user_id, org_settings.manager_user_id, schedules.staff_user_id/
     meeting_type_id, transcripts/analyses/audio_files/meeting_prep/settings/invitations.org_id) —
     negligible today, worth indexing before volume grows; no `schema_migrations` version table
     exists yet, so all DDL here is idempotent-by-hand rather than versioned.
6. **`SELECT *` waste (deps.py hot path)** — `get_current_user()` (runs on every authenticated
   request via `Depends`) selected all 17 `users` columns including `password_hash`, MFA codes,
   `must_change_password`, timestamps. Narrowed to the 8 columns actually consumed anywhere
   downstream (`id, org_id, email, name, role, team_id, setting_id, password_changed_at` — the last
   needed internally by deps.py's own SEC-001 token-freshness check). Verified via exhaustive grep
   (no code reads a dropped field) + 57/57 tests incl. SEC-001 regression (iteration_103). Removed a
   dead `pool = request.app.state.pool` line found during the same pass.
   - ~81 other `SELECT *` occurrences across routers exist but are lower-value (not per-request-
     for-every-user); not yet addressed, available as a future field if the user wants to continue.
5. **N+1 query patterns (6 locations)** — batched into single `WHERE id = ANY($1::text[])` queries
   or correlated subqueries: `super_admin.py list_orgs()` (2 counts/org → 1 query),
   `admin.py export_evidence/export_cqc_excerpts/export_cc_excerpts` (analyses fetched per-meeting →
   batched), `admin.py export_transcripts` (transcripts fetched per-meeting → batched),
   `dashboard.py fetch_structure()` (teams fetched per-setting → batched), `review.py
   share_meeting()` (user lookup per user_id → batched, also fixed a duplicate-user_id edge case).
   `org.py get_structure()` N+1 was already fixed in item 2 above. Verified row-level output
   identical (dangling analysis/transcript ids, shared analysis_id across meetings, PII redaction
   stays per-meeting, role filters, scope-correct dashboards) — 31/31 tests, iteration_102.
   - Noted but not fixed (pre-existing, out of scope): export PDF attendee/manager name lines are
     not PII-redacted even though the analysis/transcript body is; orphan `teams` row with NULL
     `setting_id` stays invisible in dashboard dropdown (same as before the fix, not a regression).
1. **Missing index on `audio_files.meeting_id`** — added (meeting deletion was a full table scan).
2. **7 missing indexes on daily filters** — added: `teams(org_id, setting_id)`,
   `org_settings(org_id)`, `focus_topics(org_id)`, `standards_documents(org_id)`,
   `users(team_id, setting_id)`. Staff-filter (`GET /admin/users`) was the hot path.
   - Surfaced 5 pre-existing unrelated bugs during regression, all fixed + verified:
     - `PUT /api/org/settings/{id}` (branch rename) always 500'd — `org_settings.manager_user_id`
       column didn't exist though code assumed it. Added column, wired create/update to persist it.
     - `GET /api/org/structure` N+1 query loop → batched into ~4 queries (org.py, output shape
       verified byte-identical).
     - Focus Topics tab showed stale list after add/set-current/delete — added `invalidateCache`.
     - PeopleHub header "Refresh" button served stale cache (defeated its own purpose) — now
       invalidates before reload.
     - Root cause of "Structure tree needs reload after mutation": PWA service worker
       (`vite.config.mjs`) was caching `/api/org/structure` under `StaleWhileRevalidate` — moved to
       its own `NetworkOnly` rule. `admin/standards` remains `StaleWhileRevalidate`.
     - Bonus: `manager_user_id` empty-string vs NULL hygiene fixed (`mgr_id = data.manager_user_id or None`).
3. **Duplicate index on `users.email`** — `idx_users_email` (manual) was a pure duplicate of
   `users_email_key` (auto from `UNIQUE` constraint); every write updated both for no read benefit.
   Dropped `idx_users_email` (schema-qualified `public.idx_users_email` per testing-agent hardening
   suggestion), removed its `CREATE INDEX` line from init_db.py.
4. **Two `meetings` indexes built-then-dropped every restart** — `idx_meetings_org_id` /
   `idx_meetings_status` were created early in `init_db.py`, then immediately `DROP INDEX`'d later
   in the same script (superseded by composite `idx_meetings_org_status_date`) — full index build +
   drop wasted on every single backend restart. Deleted the two dead `CREATE INDEX` lines; kept the
   `DROP INDEX IF EXISTS` lines (still needed for any DB, e.g. production, not yet migrated).

### Known follow-up not yet actioned (flagged to user, awaiting decision)
- **Medium**: Edit Setting modal stale-form race — reopening Edit during the ~4s post-mutation
  refetch window can silently revert a just-saved change (sends full stale form, not a partial
  patch). Root cause identified (`OrgStructure.js saveSetting`), fix not yet applied.
- Low/cosmetic (not actioned): no loading spinner on org-tree during refetch; a few missing
  data-testids (Settings sub-tabs, Manager select); native month `<input>` in Focus Topics instead
  of app's date-picker; orphan `teams` row (`name='Team Alpha'`, `setting_id=NULL`, pre-existing seed
  residue, unreachable from UI).

## Recently Completed (Aug 2026, pre-audit-session — see CHANGELOG for older entries)
- Team Themes UI unification, component-splitting refactor, security audit fixes (privilege
  escalation, export data-scope leaks, zip-bomb guard, access-token revocation on password change,
  CORS tightening, email HTML escaping), optimistic bulk-accept on Evidence page, AI summary
  "the home manager" naming bug fix, witnessed-outcome-evidence prompt rule, DBS→Regulation 19
  mis-mapping fix.

## Backlog

### P1
- Fix Edit Setting modal stale-form race (see "Known follow-up" above).
- Session Expiry Notice: friendly "Your session expired" message instead of silent redirect.
- Toast Position Fix: move toasts above header menu so text isn't clipped.
- Meeting Templates: duplicate a past meeting's setup as a starting template.

### P2
- Full Code Review Pass (missing hook deps, index-as-key).
- CSV Export Polish: note about safety-escaped text in evidence export.
- Mobile Evidence Pass: mobile-spacing for Compliance Evidence card badges/links.
- Crash Reporting: lightweight client-side error logging.
- Split TeamInsights.js into smaller modules.
- Loading indicator on org-tree during post-mutation refetch.
- Data-testids for Settings sub-tabs + Manager select in Add/Edit Setting modal.
- Evidence-specific domain tagging (Safe/Effective/Well-led per-instance, not static per-regulation).

### P3
- Audit Trail Digest, Bulk Spelling Fix (US→UK), Mobile Speaker Menu, Portfolio Progress Bar,
  Super Admin Portfolio Access decision, "Undo Bulk Accept" toast, Provider Comparison Log,
  Vite 7/8 migration, Impersonate org for Super Admins, Prep Time Stamps.
- Replace native month `<input>` in Focus Topics with app's date-picker component.
- Clean up orphan `teams` row with `setting_id=NULL`.
- Catch `asyncpg.UniqueViolationError` in create_user/invite_user for a clean 400 instead of 500 on
  a rare concurrent-duplicate-email race (flagged by testing_agent, low likelihood).

## Environments
Preview only in this session (`supervision-preview.preview.emergentagent.com`, Supabase project
`orsxhtlpybxoexdjrbnx`). Production is 1two.one — separate Supabase project `niapfxyeynkxxotgzweq`;
no DB credentials obtained this session, schema fixes have NOT been applied there yet.
