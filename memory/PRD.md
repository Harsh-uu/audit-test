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
