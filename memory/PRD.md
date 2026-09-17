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

## Evidence Under-Detection Root Cause + Rescan Data Integrity Fixes (Sep 2026) — DONE, tested
- **RCA**: rescanning found far more valid evidence than the initial automatic scan (20→46→51 across repeated rescans). Root cause: `transcription_pipeline.py` ran evidence analysis CONCURRENTLY with diarisation (`asyncio.gather`) instead of after it, so the initial scan read a transcript with NO speaker names (`[00:24] some text`) — the evidence framework depends on knowing who's speaking (worker narrating own practice vs manager observing) and played it safe without that info. Rescan reads `transcripts.speaker_text` (properly labelled), hence the gap. NOT a prompt-wording issue.
- **Fix 1**: `transcription_pipeline.py` now `await`s diarisation FIRST, then runs `analyze_meeting()` + `generate_meeting_summary()` concurrently against the labelled transcript. Adds a few seconds to background processing (hidden behind the existing PII-review step the manager is doing anyway).
- **Fix 2**: `cqc_mappings`/`care_cert_mappings`/`custom_mappings` items now get a globally-unique id (`cqc_<12-hex-uuid>` etc.) instead of the model's own sequential `cqc_1`/`cqc_2`, which collided across rescans (confirmed real collision cases in DB, e.g. two different mappings both `cqc_6`).
- **Fix 3**: `_merge()` in `review.py`'s rescan logic now permanently preserves any evidence item with status accepted/rejected/needs_followup — a rescan can never silently overwrite a manager's review decision, even if that standard isn't re-found. Pending items are still replaced 1:1 when the fresh scan re-touches that standard ref (unbounded pending-item growth for untouched refs is a known, accepted tradeoff — user is aware rescan is a low-frequency/admin tool, not something to fully redesign right now).
- Verified via testing_agent (iteration_141.json): 5/5 pytest tests, 100% pass, real LLM rescan round-trip confirmed accepted items survive + new uuid ids applied with no duplicates + role-gate (403 for non-manager) intact.

## Team Themes Tab Swap + "rota"/"rotor" ASR Fix + AdminLibrary Upload Race Condition (Sep 2026) — DONE, tested
- Swapped "Standards Coverage"/"AI Accuracy" tab positions on Team Themes page.
- Added "rotor"→"rota" homophone correction (case-preserved) to `_apply_uk_spelling()`; added "rota"/"rotas" to AssemblyAI word_boost.
- Fixed AdminLibrary.js document upload race: `fetchAll()` + parse-status poll shared no request-order guard, so a stale response could overwrite a fresh post-upload list. Added shared `fetchReqRef` counter; poll also switched from `cachedGet` (was replaying a 120s-stale response) to live `axios.get`. Tested via testing_agent (iteration_139/140), 100% pass.


## AI Analysis: Missing "Record on File" Actions (Sep 2026) — DONE, verified live
- **RCA**: user reported a report where the summary correctly noted "Helen will record positive feedback on Megan's file" but no corresponding action item was generated. Root cause: the ACTIONS prompt rule in `ANALYSIS_SYSTEM_PROMPT` (utils/ai.py) was generic ("list only concrete tasks...") with no explicit instruction that a commitment to formally RECORD/DOCUMENT/LOG/FILE something discussed counts as an action — the model under-weighted these as descriptive narrative (captured in summary) rather than an actionable follow-up, especially for low-key/administrative commitments (positive feedback) vs. substantive ones (training, referrals).
- Fix: added explicit rule directly after the ACTIONS instruction requiring any "will add to file/record/log/document" commitment to be captured as an action, regardless of whether it's already reflected in the summary, for positive feedback, complaints, or incidents alike.
- Verified live via a synthetic transcript replicating the exact scenario (Vertex AI unavailable in this env, fell back to OpenAI o4-mini) — action now correctly generated: "Helen Mercer will add the positive feedback from Mrs A's son to Megan Foster's file."
- NOTE: this only affects FUTURE meeting analyses. The existing report the user showed will not retroactively gain the missing action unless that meeting is re-analysed.

 + "rota"/"rotor" ASR Fix + AdminLibrary Upload Race Condition (Sep 2026) — DONE, tested
- Swapped "Standards Coverage" and "AI Accuracy" tab positions on Team Themes page (was matrix,themes,...,ai_accuracy → now matrix,ai_accuracy,...,themes).
- Added homophone-correction to `_apply_uk_spelling()` in `utils/ai.py`: "rotor"/"rotors" → "rota"/"rotas" (case-preserved), applied to verbatim transcripts AND all AI-generated text. Also added "rota"/"rotas" to AssemblyAI `word_boost` list.
- **AdminLibrary.js document upload race condition** (user-reported: "uploaded doc, no indication it worked" → "uploaded 2nd doc, both appeared"): `fetchAll()` (mount + post-mutation) and the parse-status polling `setInterval` both called `setDocs()` independently with no ordering guard, so a slow mount-time or stale poll response could resolve AFTER a fresh post-upload refresh and silently overwrite it. Fixed by giving `fetchAll()`, the poll, `handleToggleDoc`, and `handleDeleteDoc` one shared monotonic `fetchReqRef` counter — whichever request was issued LAST always wins on write, regardless of resolution order. Poll also switched from `cachedGet` (was replaying a 120s-stale cached response every 3s tick) to plain `axios.get` + `invalidateCache`, since its purpose is near-real-time parse_status observation. Tested via testing_agent (iteration_139.json found the poll-race, iteration_140.json confirmed 100% fix, 6/6 upload cycles, 0 regressions).
- NOTE: test docs (`TEST_race_*`, `TEST_racePoll_*`, `TEST_it140*`) left in Test Company's Custom Standards library from testing — safe to delete via UI if desired.


## AI Accuracy Sortable Table (Sep 2026) — DONE, tested
- Route `/admin/team?tab=ai_accuracy` (NOT `/team-insights` — that path doesn't exist; App.js:94 confirms actual route).
- "Recent evidence decisions" converted from flat list to sortable `<table>`: columns Standard, Manager, Attendee, Date, AI Confidence, Decision. All 6 independently sortable (click=asc, click again=desc, ▲/▼ indicator).
- Dates use en-GB short format via custom `formatUkDate()` helper (not `toLocaleDateString`, which returns "Sept" for September in en-GB — fixed to always give 3-letter months, e.g. "16 Sep 2026").
- Tested via testing_agent (iteration_138.json): 95% pass, only nit was Sept/Sep which is now fixed.


## Bug Fixes: Ofsted Evidence Field Aliasing, Teachers' Standards Badge, Report Loading Skeleton, Meetings Month-Lazy-Load, Doc-Upload Bulk-Accept Race Condition (Sep 2026) — DONE, user-confirmed
- **Ofsted zero-evidence bug**: root-caused to the AI sometimes inventing jurisdiction-named JSON keys
  (`eif_mappings`, `teachers_standards_mappings`) instead of the fixed schema keys
  (`cqc_mappings`/`care_cert_mappings`) the pipeline reads — evidence was generated correctly but
  silently discarded. Fixed with an explicit "field names are fixed" prompt rule + a
  `_normalize_mapping_aliases()` safety net in `ai.py` covering all non-CQC jurisdictions
  (Wales/Scotland/NI/Ofsted). User-confirmed fixed on their live meeting (13 evidence items now).
- **Mislabeled evidence badge**: the small per-card badge hardcoded "Care Cert" regardless of
  jurisdiction (section header was already correct). Added `certBadge` to `getJurisdictionLabels()`
  in `ComplianceTab.js`: Teachers' Standards → "TS", Wales → "AWIF/SCW", Scotland → "SSSC",
  NI → "NISCC", Early Years → "EYFS", Children's Home → "L3".
- **Meeting report bare-spinner gap**: replaced with a skeleton resembling the processing tracker
  layout in `MeetingReport.js`'s `loading` state.
- **Meetings page month-based lazy load**: current month loads in full; every previous month
  collapses into a "Month Year ── N meetings · status breakdown" divider row, lazy-expanded on
  click. New `GET /api/meetings/month-summary` endpoint + `year`/`month` filter added to
  `_list_meetings_data()` (all 4 role-scoping branches). Search/filter auto-fetches full history
  transparently. Old "Load all meetings" button removed (superseded). Tested: 13/13 backend,
  all frontend flows pass (iteration_137).
- **Doc-upload "Accept all likely/possible" bulk-accept race condition**: `ComplianceTab.js` was
  missing `onBulkAccept`/`bulkAcceptingTier` props on the `DocUploadReport.js` page (buttons were
  literal no-ops). First fix (wiring + `Promise.all` of N single-item PUTs) still failed under
  real testing — root cause was a read-modify-write race: N concurrent PUTs to the same JSONB
  column each read the same stale row and the last writer wins, silently dropping all other
  updates (11 requests → only 2 survived). Real fix: new atomic
  `POST /api/doc-uploads/{upload_id}/evidence/bulk-action` endpoint using
  `SELECT ... FOR UPDATE` + one write, mirroring the meeting-side pattern in `review.py`.
  User-confirmed fixed live (13/13 items correctly flipped to Accepted in one call).

## Prep-Prompt Rewrite Verification + Admin/Review Security Audit + Minor UI Cleanups (Sep 2026) — DONE, tested
Continuation of prior session's `generate_prep_questions` prompt rewrite (GROW model, 25-word cap,
higher context limits, blank-slate mode, bonus insight section).
- **Critical bug found & fixed on session start**: the previous agent's prompt edit left a Python
  3.11-incompatible nested triple-quote (`{"""..."""}` inside an outer `f"""..."""`) in `ai.py`'s
  rule 10 (blank-slate mode) — this crashed the ENTIRE backend on every hot-reload (`SyntaxError`
  at import time, `routers/processing.py` import chain). Fixed by extracting that block into a
  plain `blank_slate_rule` string variable computed before the f-string, referenced via
  `{blank_slate_rule}` — no nested-quote conflict. Backend confirmed healthy after fix.
- **Prompt verified end-to-end, live**: (1) rich-context case (real supervisee, 5 prior meetings +
  2 uploaded docs + org standards) — produced grounded, GROW-styled, sub-25-word questions
  referencing specific document content, non-generic AOB, bonus insight section present. (2)
  blank-slate case (brand-new starter, zero history/docs/focus) — correctly switched to warm
  first-check-in questions with no reference to "documents"/"focus topic". User approved both.
- **Security audit** (`security_audit_agent` on `admin.py`+`review.py`'s `with_admin()` usage,
  continuing the P1 backlog item): found and fixed 3 confirmed cross-tenant BOLA bugs — SEC-001
  `delete_standard` could deactivate ANY org's custom standard (no org filter, now `with_org()`);
  SEC-002 4 debug/repair endpoints (`debug-by-email`, `{user_id}/debug`, `debug-attendees`,
  `add-attendee`) let a plain `admin` (not just super_admin) read/mutate other orgs' users/meetings
  — now gated with an explicit org_id-match 404 for non-super_admin callers; SEC-003
  `export-cc-excerpts` could leak foreign-org staff names into a PDF — now `with_org()` so RLS
  drops foreign ids. Also downgraded ~12 more `with_admin()`→`with_org(org_id)` call sites across
  both files per the audit's hardening list (defence-in-depth, zero behaviour change — org lookups,
  template save, evidence_feedback inserts, send-email recipient check, rescan org lookup,
  `delete_audio_after_grace` fetching org_id up front instead of using god-mode throughout).
  Left untouched: genuinely global/pre-org paths (email-uniqueness check, rate-limit tables, the
  global settings-template fallback, super_admin cache rewarm).
- **Minor UI cleanups**: password hint placeholders/validation "8 characters"→"10" in
  `SuperAdminDashboard.js`, `OrgStructure.js`, `PeopleHub.js`, `UsersTab.js`; removed the dead
  `isMandatory`/super_admin branch + stale "cannot be disabled for managers and admins" copy in
  `OrgSettings.js` SecurityTab (super_admin never reaches this admin/manager-only route, and MFA
  is actually optional for both roles per the Supabase Auth migration); restyled "Export Portfolio
  PDF" button (pill shape, hover lift, spinner icon while exporting) in `StaffPortfolio.js`;
  lightened the Team Themes loading skeleton (`bg-gray-100` override) in `TeamInsights.js`; fixed a
  missed "Care Worker"→"Staff / Supervisee" label in `PeopleHub.js`'s `ROLES` array (regression
  from the earlier session's role-label update — OrgStructure.js/UsersTab.js had it, PeopleHub.js
  didn't).
- **Tested via `testing_agent`** iteration_136: 19/19 backend pytest pass, verified with a genuine
  second org+admin (`orgb-test-3628a11d@example.com` / OrgBTest123! in "IDOR Test Org B") proving
  real cross-org 404 denial on all 3 SEC fixes, same-org happy-path unaffected, zero regressions on
  standards/users/template/rescan/send-email. Frontend UI items self-verified via screenshot
  (Security tab, password hints, button restyle, lighter skeleton) — not run through testing_agent
  (low-risk cosmetic-only, backend was the priority this session).
- Non-blocking code-review notes from testing agent → moved to Backlog P3.


Added a 5th jurisdiction, `ofsted`, alongside england/wales/scotland/northern_ireland, fully
additive (mirrors the NI residential/domiciliary pattern exactly). Covers 3 setting types via a
required `service_type`:
- **school**: regs = Ofsted EIF (effective Nov 2025) — 7 areas (Safeguarding, Inclusion,
  Curriculum and Teaching, Achievement, Attendance and Behaviour, Personal Development and
  Wellbeing, Leadership and Governance). Induction/cert = Teachers' Standards (DfE 2021, TS1-TS9
  incl. Part Two conduct). Deliberately excludes the ITE inspection toolkit per user request.
- **early_years**: regs = EYFS Safeguarding & Welfare Requirements (5 categories). Induction/cert
  = EYFS Learning & Development, 7 areas of learning.
- **childrens_home**: regs = The 9 Children's Homes Quality Standards (Children's Homes (England)
  Regulations 2015). Induction/cert = Level 3 Diploma for Residential Childcare, 16 mandatory
  units.
- Seeded 53 new `standards_entries` rows (`seed_ofsted_standards()` in `seed.py`).
- `super_admin.py`: `VALID_JURISDICTIONS` +`ofsted`; `NI_SERVICE_TYPES`/`OFSTED_SERVICE_TYPES`
  kept as separate tuples so the two families can never cross-contaminate (validated both ways).
- `ai.py`: reg_label/cert_label branches in both `analyze_doc_for_evidence` and `analyze_meeting`,
  plus 3 new detailed domain guides (evidence-detection instructions) in `analyze_meeting` for
  ofsted_school / ofsted_early_years / ofsted_childrens_home — first-pass v1, intended to be
  refined once real Ofsted demo feedback comes in (same as CQC's guide was iteratively tuned).
  `generate_prep_questions` gained an optional `sector_label` param (default unchanged for all
  other jurisdictions) so the Induction/Prep page reads correctly for Ofsted orgs.
- Wired through `doc_uploads.py`, `transcription_pipeline.py`, `review.py` (rescan + PDF export),
  `admin.py` (`list_standards`, `_ti_load_standards`), `prep.py`.
- Frontend: `SuperAdminDashboard.js` (Ofsted option + Setting Type sub-picker + badges),
  `InspectionPrep.js`, `ComplianceTab.js`, `AdminLibrary.js`, `UploadSupervision.js` all made
  service_type-aware for Ofsted labels.
- **Bugfix (user-approved, found & fixed alongside)**: NI's "Rescan evidence" button was passing
  plain `jurisdiction="northern_ireland"` to `analyze_meeting`, which only branches on
  `northern_ireland_residential`/`northern_ireland_domiciliary` — so NI rescans always silently
  fell back to CQC/England content. Fixed in `review.py::_run_rescan_background` by building the
  same `effective_jurisdiction` string the main pipeline already used.
- **Tested via testing_agent**: 100% backend (20/20 pytest — org validation, cross-family
  service_type rejection, seed counts, list_standards scoping, AI label branches, NI bugfix
  source-verified) and 100% frontend (Super Admin create/edit modals, badges, regression clean
  on England/Wales/Scotland/NI). AI evidence-scan pipeline verified end-to-end for school and
  childrens_home (correct EIF/Teachers'-Standards/CHQS refs, zero CQC cross-contamination);
  early_years transcript returned 0 mappings once due to LLM non-determinism on a short test
  transcript (not a wiring bug). No critical/minor issues outstanding.
- Nit for future polish: `ai.py`'s Ofsted label maps are duplicated across the 2 functions
  (harmless, matches existing pattern for wales/scotland/NI) — could be refactored into a shared
  jurisdiction→label dict later if touching this area again.


## Issue 3.4: Dead `_compress_to_mp3` Function — DELETED (Sep 2026), verified live
Confirmed 100% via full-codebase search (backend + frontend, every directory): `_compress_to_mp3`
in `ai.py` had zero references from any actual app code path (routers, pipeline, other utils) —
only referenced by `tests/test_vad_threshold_and_retry.py`.
- **Fix**: deleted the function from `ai.py`, plus its now-unused `subprocess`/`tempfile`
  imports (both were only used inside this one function). Updated the test file: removed the 2
  tests that asserted on the deleted function's internal `silence_filter` string
  (`test_silence_filter_uses_minus_40db`, `test_silence_filter_has_both_silenceremove_steps` —
  nothing left to test), updated `test_ai_py_imports_valid` to no longer import the deleted
  function, and removed the now-unused `import re`.
- **Verified live**: backend restarted clean (confirms `ai.py` still imports with no errors).
  Ran the updated `tests/test_vad_threshold_and_retry.py` — all 4 tests in `TestCodeReview`
  (including the modified `test_ai_py_imports_valid`) passed. The 5 errors in the unrelated
  `TestRetryEndpoint` class are a pre-existing stale fixture issue (expects an `access_token`
  field the cookie-based auth no longer returns) — confirmed unrelated to this change, not
  introduced by it. Full-codebase grep confirms zero remaining references to the deleted
  function. No testing_agent round used (dead-code deletion + matching test cleanup, verified
  via direct pytest run).
- Issue 3.4 now fully CLOSED.

## Issue 3.3: Admin Stat/List Endpoints — ACKNOWLEDGED, NOT FIXED (Sep 2026, by user request)
Audit item confirmed accurate: `/admin/people-stats`, `/admin/meetings-brief`,
`/admin/team-insights`, `/admin/standards*`, `/admin/template`, `/admin/users` all already have
frontend-side `cachedGet` TTLs (30s–10min) configured in `apiCache.js` — backend "fetches more
than needed" concern is already mitigated by not re-fetching on every render. `super_admin.py`'s
`list_org_users` (super-admin viewing one org's user list) has no LIMIT, but is naturally bounded
by a single care-provider org's realistic headcount.
- **Decision**: user's own fix note said "Low priority — already mitigated by caching, or
  naturally bounded by realistic data size." No code changes made.

## Issue 3.2: seed.py One-Row-at-a-Time Standards Insert — FIXED (Sep 2026, per follow-up user request), verified live
Originally flagged as "not worth prioritizing" and left unfixed — user then asked to proceed
anyway. `_insert_standards_entries` (the ONE shared helper used by all 5 region seed functions —
England, Wales/CIW, Wales/AWIF+SCW, Scotland, Northern Ireland) looped `for e in entries: await
conn.execute(INSERT...)`. Replaced with a single `conn.executemany(...)` call passing all rows
at once — fixes all 5 regions' first-boot seeding through this one shared function. Confirmed
the connection-level jsonb type codec (`database.py`, encoder=json.dumps) applies identically to
`executemany()` as it does to `execute()`, so raw Python lists for `keywords`/`sub_outcomes`/
`key_questions` still encode correctly (not double-encoded). Left the 2 separate one-time
JSONB-repair/backfill UPDATE loops in `seed_standards()` untouched — out of the stated scope
("adds standards records"), and each is an even rarer one-time data-migration path.
- **Verified live**: real backend restart triggered the full startup seed sequence for all
  regions with no errors (all "already seeded — skipping", so the new batched INSERT path
  wasn't exercised by real data on this restart). Directly invoked `_insert_standards_entries`
  with 5 isolated fake test entries (`jurisdiction='test_jurisdiction_perf6'`) — all 5 correctly
  inserted with correct jsonb encoding (verified `keywords`/`sub_outcomes`/`key_questions` came
  back as proper lists/objects, not double-encoded strings); re-ran the same insert and confirmed
  `ON CONFLICT (id) DO NOTHING` still prevents duplicates (count stayed at 5). Test rows deleted
  afterward — no real seeded standards touched. No backend errors. Self-tested via direct
  function invocation, no testing_agent round used.
- Issue 3.2 now fully CLOSED.

## Issue 3.1: 5 Small Batch/Dedup Tidy-ups — FIXED (Sep 2026), verified live
5 small, self-contained inefficiencies batched together in files already being touched.
- **super_admin.py `delete_org`**: was `for path in audio_paths: await delete_audio(path)`.
  Added `delete_audio_batch()` to `supabase_storage.py` (new `_sync_remove_many` using
  `.remove(paths)` with the full list in one Supabase Storage call) and switched `delete_org` to
  call it once with all paths.
- **job_worker.py `_sweep_audio_deletions`**: was opening 2 separate `with_admin()` connections
  per meeting (one for `audio_files`, one for `meetings`). Merged into 1 connection for the
  audio_file_id-present case; the audio_file_id-absent case (meetings-only update) unchanged.
- **auth.py `reset_password`**: was querying `users` by email twice (`id`, then later
  `supabase_password_set`). Now selects both columns in the one query. Confirmed
  `supabase_auth.create_user`/`set_password` never touch `supabase_password_set`, so reading it
  earlier is equivalent, not stale.
- **transcription_pipeline.py `_get_rolled_actions`**: was recomputing `set(supervisee_ids)` on
  every loop iteration (up to 50x). Hoisted to `supervisee_ids_set = set(supervisee_ids)` once
  before the loop.
- **ai.py `transcribe_audio`**: was calling `_apply_uk_spelling(u.text)` twice per utterance
  (once for `lines`, once for `ts_lines`). Now computed once per utterance into
  `cleaned_utterances`, reused for both.
- **Verified**: (1) `delete_audio_batch()` called directly against real Supabase Storage with
  fake/non-existent paths — succeeded with no exception (idempotent, matches original per-path
  behavior), plus empty-list no-op confirmed. The `super_admin.py` router wiring itself is a
  straightforward substitution, confirmed via clean backend startup with no import/syntax errors
  — full end-to-end org-deletion was not exercised (blocked by an unrelated pre-existing
  super_admin login credential mismatch against `test_credentials.md`, not a regression from
  this change) — noting this explicitly rather than overclaiming. (2) `_sweep_audio_deletions`
  invoked directly against real DB with 2 throwaway test meetings (one with an `audio_files`
  row, one without) — both correctly updated to `audio_deletion_status='deleted'` via the merged
  connection, `audio_files.is_deleted` correctly set true for the with-audio case. Test rows
  cleaned up. (3) Full live `forgot-password` → `reset-password` flow on a throwaway test user —
  succeeded, login confirmed working with the new password; test user deleted afterward. (4)
  Direct re-invocation of `_get_rolled_actions` — identical result (1 rolled action) to before
  the hoist. (5) Isolated logic test confirmed the cleanup call count dropped from 4 to 2 (one
  per utterance) with identical output content for both `speaker_text` and `timestamped_plain`.
  No backend errors across all tests. Self-tested via curl + direct DB/function invocation, no
  testing_agent round used.
- Issue 3.1 now fully CLOSED (with the one noted exception on full super_admin org-delete E2E
  coverage — flagging for a future retest once that unrelated login issue is looked at, if ever
  raised).

## Issue 2.9: Dashboard Action Stats + Doc Uploads Unbounded History — FIXED (Sep 2026), verified live
Audit item: 2 endpoints pulled an org's entire history with no cap, getting slower forever as an
org accumulates data.
- **dashboard.py `fetch_action_stats`**: was fetching the full `actions` JSONB array for every
  qualifying meeting ever, then counting outstanding/overdue in Python. Replaced with a single
  aggregate SQL query using `jsonb_array_elements` + `CROSS JOIN LATERAL` +
  `COUNT(*) FILTER (...)` — counts both numbers directly in Postgres, zero JSON blobs
  transferred. Preserved exact original semantics: `jsonb_typeof(action) = 'object'` guard
  (matches Python's `isinstance(action, dict)` check — skips non-object array entries the same
  way), `COALESCE((action->>'completed')::boolean, false)` (matches `action.get("completed",
  False)` default), and `COALESCE(action->>'due_date', '') != ''` before the date-string
  comparison (matches Python's truthy check on `due_date` before comparing).
- **doc_uploads.py `list_uploads`**: added `LIMIT 200` (both the `staff_id`-filtered and
  unfiltered query variants), ordered by `created_at DESC` so it's always the most recent —
  frontend (`UploadSupervision.js`, `StaffPortfolio.js`) already consumes this as a plain array
  with no pagination UI, so kept the exact same response shape, no frontend changes needed.
- **Verified live**: independently re-computed the OLD Python-counting logic directly against
  the real DB scoped to the admin's org — got `{"outstanding": 17, "overdue": 0}`. Called the
  actual `/api/dashboard/` endpoint with the NEW SQL-based counting — got the exact same
  `{"outstanding": 17, "overdue": 0}`, byte-for-byte match. `/api/doc-uploads/` still correctly
  returns all 3 existing uploads (well under the 200 cap) in the same order as before. No
  backend errors. Self-tested via curl + direct DB comparison script, no testing_agent round
  used.
- Issue 2.9 now fully CLOSED.

## Issue 2.8: 5 Backend "One-at-a-Time" Loops Batched — FIXED (Sep 2026), verified live
Audit item: 5 backend actions looped through a list doing 1 DB call per item instead of 1 batched
call for the whole list — small impact today, grows proportionally with usage.
- **schedules.py `bulk_create_schedules`**: replaced per-staff `SELECT` (validate exists) + per-
  staff `INSERT` with one `SELECT id FROM users WHERE id = ANY($1::uuid[])` to validate all
  candidates at once, then one multi-row `INSERT ... SELECT gen_random_uuid(), ... FROM
  UNNEST($7::uuid[])` for all new schedules at once.
- **org.py `delete_setting`**: replaced fetch-teams-then-loop-update with a single
  `UPDATE users SET team_id=NULL, setting_id=NULL WHERE team_id IN (SELECT id FROM teams WHERE
  setting_id=$1)` — no Python loop, no separate fetch needed at all.
- **review.py `bulk_update_evidence`**: was opening a BRAND NEW `with_admin()` pooled connection
  per changed item to insert into `evidence_feedback` (worse than a plain N+1 — N connection
  checkouts). Now collects all rows first, then one `with_admin()` connection + one
  `executemany(...)` call for the whole batch.
- **prep.py, 2 places** (`get_prep_context` and `_run_generate_prep`): both fetched up to 5 (or 3)
  previous meetings then looped doing 1 `SELECT` on `analyses` per meeting. Now collect all
  `analysis_id`s first, one `SELECT ... WHERE id = ANY($1::uuid[])`, build a dict, use dict
  lookups in the loop instead of a query per row.
- **transcription_pipeline.py `_get_rolled_actions`**: fetched up to 50 previous meetings then
  looped doing 1 `SELECT` on `analyses` per matching meeting. Now filters matching meetings
  first, then one batched `SELECT ... WHERE id = ANY($1::uuid[])` for all their actions.
- **Verified live** (all via real DB, not mocked): (1) `bulk_create_schedules` — created 3
  candidates, 1 correctly created via the new `UNNEST` insert (verified `gen_random_uuid()` +
  `created_by` correct in DB), 2 correctly skipped (1 scope/duplicate, 1 pre-existing). (2)
  `delete_setting` — created a test branch + 2 teams, assigned a real staff member to one,
  deleted the branch: staff's `team_id`/`setting_id` both correctly nulled via the single
  subquery UPDATE, teams and setting rows gone. (3) `bulk_update_evidence` — bulk-accepted 11
  real "likely_evidence" pending items on a real meeting via the actual `/api/review/{id}
  /evidence/bulk-action` endpoint: all 11 updated to "accepted" AND exactly 11 `evidence_feedback`
  rows inserted via the new `executemany` batch (verified in DB) — reverted both afterward. (4)
  `get_prep_context` (`/api/prep/{id}/context`) — returned exactly 5 previous meetings each with
  correct summary/actions from the batched analysis lookup. `generate_prep` (background AI task)
  — ran successfully end-to-end, produced valid prep questions, no errors. (5)
  `_get_rolled_actions` — invoked directly against real DB with real attendee data, correctly
  returned 1 rolled-over incomplete action matching what was independently visible in the
  `get_prep_context` output. No console/backend errors across all 5 tests, no regressions.
  Self-tested via curl + direct DB/function verification, no testing_agent round used.
- Issue 2.8 now fully CLOSED.

## Issue 2.7: ComplianceTab Fully-Expanded Unbounded List — FIXED (Sep 2026), verified live
Audit item: `EvidenceCard` (in `ComplianceTab.js`) hardcoded `useState(true)` for its `expanded`
state — every evidence card defaulted to fully expanded, with a confirmed real meeting having
126 evidence mappings all rendered open simultaneously with no incremental loading.
- **Fix**: `EvidenceCard` now accepts a `defaultExpanded` prop. New `EvidenceSection` wrapper
  (used for all 3 groups — CQC/Care Cert/Custom) renders only the first 20 items per section by
  default (`INITIAL_VISIBLE_COUNT`), with only the first 3 of those defaulting to expanded
  (`INITIAL_EXPANDED_COUNT`); a "Show N more (M remaining)" button reveals the rest of that
  section incrementally. Chose this simpler load-more pattern over a scroll-position
  virtualization library (react-window) — lower risk, no new dependency, doesn't interact with
  per-card expand/collapse or the "Show in transcript" jump action.
  Verified `bulkAcceptEvidence` (Accept all likely/possible) operates on the full
  `meeting.analysis.*_mappings` data arrays in React state, completely independent of what's
  mounted in the DOM — confirmed zero impact on bulk-accept correctness before implementing.
- **Verified live**: temporarily inflated a real meeting's `custom_mappings` to 25 items via
  direct DB update (reversible test, not synthetic UI mocking) — confirmed exactly 36 cards
  mounted initially (14 CQC + 2 Care Cert + 20 of 25 Custom, capped), "Show 5 more (5 remaining)"
  button appeared and correctly revealed all 25 on click (41 total after). Screenshot confirmed
  the CQC section's first 3 cards render expanded (transcript excerpt + accept/reject/flag
  visible) and the 4th+ render collapsed (header only) — exactly matching the intended default.
  Reverted the test meeting's `custom_mappings` back to its original single item afterward
  (confirmed count restored to 17 total: 14+2+1). No console errors, no regressions. Self-tested
  via screenshot_tool + direct DB verification, no testing_agent round used.
- Issue 2.7 now fully CLOSED.

## Issue 2.6: BrandingTab/ShareModal Bypassed App Cache — FIXED (Sep 2026), verified live
Audit item: `utils/apiCache.js`'s `TTL_MAP` explicitly configures `/org/branding` (5 min) and
`/admin/users` (30s) for caching, but `BrandingTab.js` and `ShareModal.js` both used a plain
`axios.get(...)` for these exact endpoints, bypassing the cache entirely — hitting the server on
every mount/every modal open.
- **Fix**: swapped `axios.get` → `cachedGet` (drop-in replacement) in both files. Additionally
  (needed to avoid a real regression from the switch, not just the literal 1-line ask): added
  `invalidateCache("/org/branding")` to `BrandingTab.js`'s 3 mutation handlers
  (`handleLogoUpload`, `removeLogo`, `handleSave`) — without this, editing branding then
  switching Settings tabs away and back within the 5-min TTL would show stale pre-edit data,
  since `BrandingTab` unmounts/remounts on every tab switch (`OrgSettings.js:593`,
  `{tab === "branding" && <BrandingTab />}`). `ShareModal.js` needed no invalidation addition —
  it only reads `/admin/users`, never mutates it.
- **Verified live** via Playwright + network interception (admin login):
  `/org/branding`: exactly 1 GET fired across opening the Branding tab, switching away, and
  switching back TWICE (previously would have been 3 GETs). Clicking "Save Branding" (PUT 200,
  "Branding saved" shown) then revisiting the tab correctly triggered a fresh GET (2nd call) —
  confirming `invalidateCache` works and stale data is never shown after an edit.
  `/admin/users`: opening a signed-off meeting's Share modal fired exactly 1 GET (showed the
  correct manager/admin list); closing and reopening the modal fired 0 additional GETs — served
  from cache.
  No console errors, no regressions. Self-tested via screenshot_tool, no testing_agent round
  used.
- Issue 2.6 now fully CLOSED.

## Issue 2.5: RecordingScreen Progressive-Slowdown Auto-Save — FIXED (Sep 2026), verified live
Audit item: `RecordingScreen.js`'s IndexedDB backup used ONE record per meeting (`keyPath:
"meetingId"`) holding the full recording blob. Every 3-min auto-save AND the final
`recorder.onstop` handler both rebuilt `new Blob(audioChunksRef.current, ...)` from ALL chunks
recorded since the start, then overwrote that single record — so save #10 (30min) re-copied
~10x the bytes save #1 (3min) did; total work across a recording grew ~O(length²).
- **Fix**: IndexedDB schema bumped v1→v2 to store one small record PER incremental save
  (autoIncrement key + `meetingId` index) instead of one ever-growing record.
  `lastSavedChunkIndexRef` tracks how many chunks are already persisted; a new
  `saveNewChunksToBackup()` helper blobs+appends only the chunks since the last save — used by
  both the 3-min interval AND the final `onstop` handler (previously each rebuilt independently).
  `loadAudioBackup` (rare read path: page-refresh recovery / upload-retry) now concatenates all
  saved chunk records in order — same return shape, zero change needed in `handleUpload` or the
  refresh-recovery effect. `clearAudioBackup` (after successful upload) now deletes all chunk
  records for that meeting via a cursor over the index. Added a defensive
  `clearAudioBackup(meetingId)` at the start of `startRecording()` (was already effectively a
  no-op in the one real call path, now correct-by-construction for the new schema too).
  Confirmed no race: `stopRecording()` already clears the periodic interval BEFORE triggering
  `.stop()`, so the periodic and final saves can never overlap.
- **Verified TWO ways** (user explicitly required live proof, not just code review):
  (1) Isolated IndexedDB algorithm test via `page.evaluate` mirroring the exact schema: 3
  sequential appends produced 3 SEPARATE records (not overwritten), concatenated read
  reconstructed the exact byte-for-byte original content in the correct order, clear removed all
  records for that meetingId — all assertions passed. (2) Full live browser test: created a real
  meeting, granted mic permission (Playwright fake device), started recording — IndexedDB had 0
  records mid-recording (correct, periodic save hadn't fired yet), stopped after 8s — exactly 1
  chunk record appended by the `onstop` handler, upload succeeded and the meeting correctly
  progressed to "Processing Audio: Complete → Transcribing" (AssemblyAI accepted the file as
  valid WebM audio, only rejecting it afterward for containing silence — the fake mic device
  produces no real speech, an expected test-environment artifact, not a bug), and after the
  successful upload the IndexedDB record count correctly dropped back to 0 (cleared). All 3 test
  meetings cleaned up afterward. No console errors from the recording flow itself (pre-existing
  benign 401s from the unrelated silent-refresh interceptor). No testing_agent round used — self
  tested via screenshot_tool with real browser IndexedDB + MediaRecorder execution.
- Issue 2.5 now fully CLOSED.

## Issue 2.4: Meetings.js Unconditional Polling — FIXED (Sep 2026), verified
Audit item: `Meetings.js:83-98` started an unconditional `setInterval(fetchMeetingsOnly, 15000)`
on mount that ran for as long as the page stayed open — polling every 15s even when every
visible meeting was fully terminal (signed off/reviewed/draft) and nothing could possibly change.
`UploadSupervision.js` already had the correct pattern: a `pollRef`-tracked interval that only
runs while `uploads.some(u => ["processing","text_ready"].includes(u.status))`.
- **Fix**: applied the identical pattern. Added a `pollRef` (`useRef`), removed the unconditional
  interval from the mount effect (kept the initial `cachedGet` load unchanged), and added a new
  `useEffect` watching `meetings` that starts the 15s interval only when
  `meetings.some(m => ["processing","transcribing","analyzing"].includes(m.status))` is true,
  clearing it otherwise. Those 3 statuses are the only ones that change automatically via the
  backend AI pipeline without a user action; `draft`/`recording`/`stopped` are user-driven and
  `in_review`/`reviewed`/`signed_off`/`shared`/`processing_failed` are terminal — none of these
  need polling.
- **Verified**: frontend rebuilt, logged in as `admin@supervision.com`, intercepted `GET
  /api/meetings` network calls on `/meetings`. With no meeting in a processing state: 0 calls
  over a 35s wait (previously would have fired at 15s/30s). Temporarily set a real meeting's
  `status` to `processing` directly in the DB, reloaded: page correctly showed a "Processing"
  badge and fired exactly 2 poll calls over the same 32s window (at ~15s/~30s) — confirmed both
  the "stays off" and "turns on" branches work. Reverted the test meeting back to `in_review`
  afterward. No console errors, no regressions. Self-tested via screenshot_tool + direct DB
  verification, no testing_agent round used.
- Issue 2.4 now fully CLOSED.

## Issue 2.3: NewMeeting Staff-List Filter Memoization — FIXED (Sep 2026), verified
Audit item, same pattern as 2.1/2.2: `NewMeeting.js:81-89` ran 4 `.filter()` passes over the full
org `users` list (`attendees`, `selectedAttendees`, `managers`, `supervisees`) directly in the
component body. Since these live alongside `location`/`meeting_type` in the same `form` state
object, typing a single character into Location or picking a Meeting Type re-rendered the
component and re-ran all 4 filters over the entire staff list, even though `users` and
`attendee_ids` hadn't changed.
- **Fix**: wrapped all 4 in `useMemo` — `attendees` keyed on `[users]`; `selectedAttendees`/
  `managers` keyed on `[users, form.attendee_ids]`; `supervisees` keyed on `[selectedAttendees]`.
  `titlePreview` (cheap `buildTitle()` call on the already-memoized small arrays) left as plain
  computation. No early `return` exists in this component, so hook-call order is safe.
- **Verified**: frontend rebuilt, logged in as `admin@supervision.com`, Playwright walkthrough on
  `/meetings/new`: selecting attendee 1 → title updates correctly ("Supervision with Demo
  Manager"); typing "Room 12B" into Location → title unchanged (correct, no dependency); changing
  Meeting Type to Appraisal → title updates ("Appraisal with Demo Manager"); selecting a 2nd
  attendee (Demo User) → title correctly shows the non-manager supervisee ("Appraisal with Demo
  User"), sign-off manager auto-selected to "Demo Manager (manager)" as before. No console
  errors, no regressions. Self-tested via screenshot_tool, no testing_agent round used.
- Issue 2.3 now fully CLOSED.

## Issue 2.2: TeamInsights PersonGroups + regCounts Memoization — FIXED (Sep 2026), verified
Audit item, same pattern as 2.1: `TeamInsights.js`'s `PersonGroups` component (used by all 4
register tabs — Achievements/Learning Needs/Attention/Actions) built its `groupMap`/`groups`
(grouping by staff name, then sorting by most-recent meeting) directly in the component body —
recomputed on every single expand/collapse click, since `togglePerson`/`toggleItem`/`setShowAllFor`
state lives in that same component. `regCounts` (the 4 tab-header count badges) had the identical
unmemoized pattern one level up, in the main page component.
- **Fix**: wrapped `PersonGroups`'s grouping+sort in `useMemo` keyed on `[items]`; wrapped
  `regCounts` in `useMemo` keyed on `[registers]`. Both hooks sit unconditionally above/alongside
  existing hooks with no intervening early `return` in either component, so no rules-of-hooks risk
  (verified by tracing both function bodies).
- **Verified**: frontend rebuilt, logged in as `admin@supervision.com`, navigated to
  `/admin/team` → Achievements tab. Tab badges (17/6/8/16) render correctly from memoized
  `regCounts`. Expanded "Demo Manager" person group — correct 5 achievements shown with
  identical data before/after toggle. No console errors, no regressions. Self-tested via
  screenshot_tool, no testing_agent round used (single-file, 2-hook perf fix).
- Issue 2.2 now fully CLOSED.

## Issue 2.1: CareCertPrep/InspectionPrep Coverage-Matrix Memoization + Definition Align — FIXED (Sep 2026), verified
Audit item: both `CareCertPrep.js` (Induction page) and `InspectionPrep.js` (CQC/CIW/CI/RQIA page)
called their near-identical `buildCoverage(standards, rows)` directly in the component body —
recomputed the full standards×staff matrix (nested filter/map loops) on every re-render, including
every single row expand/collapse (`toggle()` only flips `open` state, not the underlying data).
Also found the two files' "evidenced" count used differently-written filters
(`status === "evidenced" || status === "partial"` in CareCertPrep vs `status !== "gap"` in
InspectionPrep) — mathematically equivalent given today's actual status values (each matrix only
ever has 2 non-gap statuses), but brittle/inconsistent if a status is ever added to one matrix
and not the other.
- **Fix**: wrapped both `buildCoverage(...)` calls in `useMemo`, keyed on `[stds, rows]` —
  extracted the `rows`/`standards` data-access lines from `insights` and moved them (with the
  `useMemo` call) ABOVE the loading/no-data early `return`s in both files, required to keep
  React's hook-call order identical across the loading→loaded transition (a `useMemo` placed
  after an early return would only fire on some renders, violating rules of hooks). Standardized
  `CareCertPrep.js`'s evidenced filter to the same `status !== "gap"` expression InspectionPrep
  already used (already used for both files' `evidenced_staff` list) — zero output change with
  today's data, just removes future drift risk.
- **Verified**: frontend rebuilt (`vite build` — no hot reload here), logged in as
  `admin@supervision.com`, Playwright-clicked through both `/inspection-prep`... correction, real
  routes are `/inspection` and `/care-cert` (not `/inspection-prep`/`/care-cert-prep`) — confirmed
  via `App.js` route table. Expanded/collapsed the first row on both pages: percentage, staff
  count, gap names, and evidenced-staff list byte-identical before/after each toggle. No console
  errors, no regressions. Self-tested via screenshot_tool, no testing_agent round used (2-file,
  isolated frontend perf fix).
- Issue 2.1 now fully CLOSED.

## Issue 1.9: Logo Upload/Download Blocking Fix — FIXED (Sep 2026), verified
Audit item: `utils/storage.py`'s `put_object`/`get_object`/`init_storage` all use the synchronous
`requests` library, called directly (no thread offload) from `org.py`'s `upload_logo()` (line
482) and `get_org_logo()` (line 507, unauthenticated, hit on every page render that shows a logo)
— same event-loop-blocking pattern as 1.1/1.7/1.8.
- **Fix**: wrapped both call sites in `org.py` in `await asyncio.to_thread(...)` — `put_object`
  in `upload_logo`, `get_object` in `get_org_logo`. `storage.py` itself left untouched (kept as
  plain sync functions so `server.py`'s one-time startup `init_storage()` call is unaffected).
- **Verified**: backend restarted clean, no errors in logs. Logged in as `admin@supervision.com`,
  uploaded a real PNG via `POST /api/org/branding/logo` (200, ~2s real network call) — fired a
  concurrent `GET /api/health` mid-upload, returned 200 in ~0.13s. Same test for
  `GET /api/org/branding/logo/{org_id}` (200, ~0.9s) with concurrent health check at ~0.13s.
  Downloaded logo confirmed byte-identical (md5 match) to the uploaded file — no functional
  regression. Self-tested via curl, no testing_agent round used (2-call-site fix). Test data
  cleaned up.
- Issue 1.9 now fully CLOSED.

## Issue 1.8: Forgot-Password Email Blocking Fix — FIXED (Sep 2026), verified
Audit item: `POST /auth/forgot-password`'s `resend.Emails.send(...)` call in `auth.py` was still
a direct synchronous network call (same class of bug as 1.1/1.7, already fixed for
bcrypt/PDF-generation and the MFA-code send at line 204). Confirmed on inspection: the MFA-code
send was already correctly wrapped, but the password-reset send (line 626) was not.
- **Fix**: wrapped `resend.Emails.send(...)` in `await asyncio.to_thread(...)`, identical pattern
  to the MFA-code send just above it in the same file.
- **Verified**: backend restarted clean (no errors in `backend.err.log`), `POST
  /api/auth/forgot-password` still returns 200 with correct message (~1.8s, real network call to
  Resend), and a concurrent `GET /api/health` fired mid-send returned 200 in ~0.1s — proves the
  event loop is no longer blocked during the send. Self-tested via curl (concurrent timing test),
  no testing_agent round used (single-file, single-call-site fix).
- Issue 1.8 now fully CLOSED.

## SELECT * Column Trimming — COMPLETE (Sep 2026), fully tested
Audit flagged pervasive `SELECT *` (81 occurrences across 12 files) on tables holding full
meeting transcripts/AI analysis. Verified live: confirmed count, then classified every call
site into 3 tiers before touching anything — genuinely wasteful (bulk/aggregation queries),
deliberate full-row fetches (detail/edit views, already-optimized hot path in
`deps.py::get_current_user`), and unverified (required tracing before deciding).
- **Trimmed to explicit column lists** (traced every downstream field access first): 
  `portfolio.py`'s meetings/analyses aggregation (was fetching up to 500 full rows just for
  3 mapping fields), `admin.py`'s 4 export endpoints (evidence/cqc-excerpts/cc-excerpts/
  transcripts — same bulk pattern), `prep.py` (`_get_meeting_guarded`, `_run_generate_prep`,
  `carry_forward_missed`), `processing.py` (retry/diarize/retranscribe), `doc_uploads.py`
  (`update_upload_evidence`), `transcription_pipeline.py` (prep coverage check).
- **Corrected a real prioritization mistake during planning**: initially flagged `auth.py`'s
  `SELECT * FROM users` as highest-priority ("per-request hot path") — turned out `deps.py`'s
  actual `get_current_user` (the real per-request dependency) already uses an explicit column
  list; `auth.py`'s occurrences are all low-frequency (login/MFA-toggle/password-change) on a
  small non-blob table. Redirected effort to the genuinely heavy tables instead.
- **Deliberately left untouched**: `meetings.py`'s detail view (explicit code comment defends
  it), `review.py`'s edit-lock views (`FOR UPDATE`, read-modify-write same row), `org.py`/
  `schedules.py`'s list endpoints (spread full row into frontend response — Type A passthrough),
  `standards_cache.py` (feeds AI analysis functions, unclear/risky to trim), `standards_entries`/
  `standards_documents` list/rescan queries in `admin.py` (broad UI consumption or AI-function
  input, not verified safe to trim).
- **Testing**: `testing_agent` iteration_117 — 25/25 backend tests pass, all export
  PDFs/CSVs verified non-empty with correct content (magic bytes checked), frontend spot-check
  clean (portfolio stats, standards library, cross-tenant isolation all correct). One
  pre-existing data gap noted (no signed-off meeting has a transcript in seed data — unrelated
  to this change, already flagged in iteration_116).
- **Part 2 (Sep 2026, completed to closure)**: user asked to finish the job completely. Trimmed
  the remaining ~53 occurrences across `review.py` (9), `auth.py` (9), `meetings.py` (1),
  `org.py` (8), `schedules.py` (4), `admin.py` (2 more: `list_standards`/`list_documents`),
  `doc_uploads.py` (9 more), `standards_cache.py` (1), `transcription_pipeline.py` (2 more) —
  every column list traced through both backend usage AND frontend consumers (React components)
  before trimming, then every single column name cross-checked against live
  `information_schema.columns`. That cross-check caught 2 real bugs before they shipped: a
  non-existent `outcomes` column on `standards_entries` (briefly crashed backend startup,
  fixed immediately) and a non-existent `description` column on `org_settings` (`teams` has
  one, `org_settings` doesn't — fixed before any request hit it). Final state: **81 → 11
  occurrences remaining**, every one individually verified as a deliberate full-row
  detail/report view (`meetings.py`/`review.py` detail & report pages, `prep.py`'s
  `get_prep`/focus-topics passthroughs, `doc_uploads.py`'s `get_upload`) or the documented
  null-org_id edge case (`portfolio.py`). Tested via `testing_agent` iteration_118 — 31/31
  pass, zero column errors, zero 500s, join-resolved fields (manager_name, supervisor_name,
  staff_name, meeting_type_name/color, sub_outcomes counts) all verified non-blank.
- **Part 3 (Aug 2026, final closure — 81 → 0 occurrences)**: fixed the last 11. Two strategies
  used depending on risk: (a) for full-detail views whose entire row is spread into a frontend
  report page (`meetings.py::get_meeting`, `review.py::get_review_data`, plus their nested
  transcript/analysis sub-fetches) — replaced `SELECT *` with an **exhaustive** explicit column
  list matching the live `information_schema.columns` output exactly (verified via direct DB
  query, not migration-file tracing) — zero behavior change, same data returned, just no longer
  an opaque `*`. (b) for narrower single-purpose queries where downstream field usage was fully
  traced through both backend and the exact frontend consumer — trimmed to only what's used:
  `review.py::export_pdf` (traced `_generate_pdf`'s actual field reads), `portfolio.py`'s `users`
  lookup (id/org_id/name/email/role/team_id/setting_id only), `doc_uploads.py::get_upload`
  (matches `list_uploads`' existing column list, excludes unused `full_text`), `prep.py::get_prep`
  (exhaustive `meeting_prep` enumeration, small table). Tested via `testing_agent` iteration_119 —
  21/21 pass, zero column errors, PDF export still generates correctly, new-user creation flags
  still flip correctly. Non-blocking code-review note: `meetings.py::_DETAIL_COLS` and
  `review.py::_MEETING_DETAIL_COLS` are identical 47-column strings duplicated across 2 files —
  could extract to a shared `utils/columns.py` later to avoid future drift.


## `create_org_user` Transaction-Timeout Risk — FIXED (Aug 2026), fully tested
`super_admin.py::create_org_user` made 2 Supabase Auth network calls (`create_user`,
`set_password`) INSIDE an open `with_admin()` transaction — under slow network conditions this
could exceed the 30s `idle_in_transaction_session_timeout` (from the earlier transaction-duration
fix) and get killed mid-request. Restructured into 3 phases: (1) `with_admin()` block does the
local `users` insert only, then commits/closes; (2) both Supabase Auth calls now run with NO open
transaction; (3) on success, a short follow-up `with_admin()` block persists
`supabase_migrated`/`supabase_password_set=TRUE`. On Supabase failure, same as before — logged,
user stays on bcrypt fallback (no change in that fallback behavior, just no longer risks holding
a DB session open during the HTTP call). Verified via `testing_agent` iteration_119: full
happy-path (created user can log in immediately, flags flip correctly), 404 org-not-found and 400
duplicate-email guards still fire before any Supabase call. Code-review note (non-blocking): no
retry/reconciliation mechanism if Supabase provisioning fails after the local row commits — could
add a retry cron later.


## Evidence Feedback — "write-only" table given a read path (Aug 2026), fully tested
Audit finding: `evidence_feedback` (written by `review.py`'s `update_evidence`/`bulk_update_evidence`
on every AI-evidence accept/reject/edit, comment says "Training data") had 194 rows and genuinely
zero read path anywhere — not in any router, not in the frontend. User chose Option C: keep the
writes untouched, add a minimal read-only admin report instead of deleting the data or building a
full ML pipeline.
- **Backend** (`admin.py`, 2 new endpoints, admin/manager only, `with_org()` + explicit `WHERE
  org_id=$1` + explicit column lists, no `SELECT *`): `GET /admin/evidence-feedback/stats`
  (total, breakdown by manager_action/evidence_type/ai_confidence, acceptance_rate =
  accepted/(accepted+rejected)*100 rounded 1dp or null if nothing decided yet, top 10 most-rejected
  standards) and `GET /admin/evidence-feedback` (raw list, LEFT JOIN meetings for title, optional
  `limit`/`date_from`/`date_to`, capped at 1000 rows).
- **Frontend**: new 7th "AI Accuracy" tab on Team Themes (`TeamInsights.js`) — self-contained
  `AiAccuracyView` component with its own fetch/loading state (does not touch the page's shared
  `data`/`registers` state or `load()`/`loadRegisters()`). Stat strip (total/acceptance
  rate/rejected/needs-follow-up), "standards the AI misses on most" list, scrollable recent-decisions
  list with client-side CSV export. Added as pure appends: one lucide-react import addition, one
  `MAIN_TABS` array entry, one `valid` tabs array entry, one new conditional render block — zero
  lines changed in the other 6 tabs.
- `review.py`'s write side was deliberately NOT touched.
- **Tested via `testing_agent`** iteration_120: 10/10 backend tests (stats math, list schema, limit
  cap, 403 for attendee, 401 unauth, date filters, org isolation) + frontend verified end-to-end
  (cookie-injection login, tab renders real data: 194 total/99.3% acceptance/1 rejected/1
  needs-follow-up/top-rejected standard shown, CSV export works) — all 6 pre-existing Team Themes
  tabs confirmed unaffected, zero regressions.


## Jobs Table Orphan Cleanup — FIXED (Aug 2026), fully tested
Audit finding: `jobs.meeting_id` had no FK and wasn't in either `delete_meeting()`'s or
`delete_org()`'s manual cascade-delete list — a **deliberate** decision from the original
`m004_fk_constraints.py` audit ("app intentionally keeps job history after a meeting is
deleted"). Live DB check showed 5 of 10 rows (50%) were already orphaned, and grep confirmed
nothing anywhere ever reads `jobs` for display — the "history" rationale was never realized, so
the decision was reversed with user approval.
- New migration `m014_jobs_fk_cascade.py`: deletes pre-existing orphans, adds
  `fk_jobs_meeting_id FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE` (same
  idempotent DO-block pattern as the other 7 meeting-child tables), adds `idx_jobs_meeting_id`.
  Migrations run via manual `python3 init_db.py` (not auto-run on boot) — already executed.
- Added `"jobs"` to the manual cascade-delete table list in both `meetings.py::delete_meeting()`
  and `super_admin.py::delete_org()`, matching the existing belt-and-suspenders convention.
  `job_worker.py`'s insert/update logic was NOT touched.
- Tested via `testing_agent` iteration_121: 10/10 pass (FK+index existence, zero orphans, real
  API-level meeting delete cascades the job row, org delete cascades too, 403/404 guards, normal
  job insert/update lifecycle unaffected). New regression suite: `tests/test_jobs_fk_cascade.py`.
- Non-blocking hygiene note from testing agent: the cascade-delete table list is now duplicated
  verbatim in `meetings.py` and `super_admin.py` — could extract to a shared constant later.


## Settings Table Orphan Cleanup — FIXED (Aug 2026), fully tested
Audit finding: `settings.org_id` has no FK and the table was completely absent from
`delete_org()`'s cleanup (neither its `meeting_id`-list nor its `org_id`-list). Unlike the `jobs`
case, a real FK genuinely isn't possible here (documented in `m004_fk_constraints.py`):
`settings.id` uses composite string keys (e.g. `"supervision_template:{org_id}"`) rather than a
real UUID row identity, so `settings.org_id` is TEXT forever and can't type-match
`organisations.id` (UUID). That comment only explained why the FK was skipped though — it never
said cleanup itself was intentionally skipped, and every other FK-impossible table (e.g.
`standards_documents`) still gets a manual-delete fallback; `settings` never did.
- Fix: added `"settings"` to the existing `org_id`-based manual cleanup list in
  `super_admin.py::delete_org()` (`meetings, users, schedules, meeting_types,
  standards_documents, supervision_uploads, invitations` → + `settings`). One-line change, same
  proven pattern.
- Verified end-to-end: created a throwaway org (`TEST_settings_fk_org`) via the real
  `POST /api/super-admin/orgs`, inserted a `settings` row for it, deleted it via the real
  `DELETE /api/super-admin/orgs/{id}` — response now reports `"settings": 1` deleted, row
  confirmed gone, org confirmed removed, throwaway data cleaned up. Test Company org
  (`b00bf04f-a1b9-4673-8430-b4a08ba15d6c`) unaffected.


## Standards Document Download + Storage-Leak Fix — FIXED (Aug 2026), fully tested
Audit finding: custom standards documents (uploaded for AI evidence extraction) had no way to be
read back, AND deleting a document's DB row left its file orphaned in Supabase storage forever
— **verified live**: 12 files existed in the `supervision-documents` bucket with 0 matching
`standards_documents` rows (100% orphan rate from prior test uploads/deletes), all cleaned up
manually as part of this fix.
- `utils/supabase_storage.py`: added `get_document()`/`delete_document()`, thin wrappers around
  the existing generic `_sync_get`/`_sync_remove` helpers with `DOCS_BUCKET` — exact mirror of
  the pre-existing `get_audio`/`delete_audio`.
- `admin.py`: new `GET /standards/documents/{doc_id}/download` (org-scoped, admin/manager only,
  returns original bytes with correct filename + content-type). `delete_document()` now fetches
  `storage_path` before the DB delete, then removes the file from storage best-effort (mirrors
  `meetings.py::delete_meeting`'s audio-cleanup sequencing — storage failure is logged, never
  blocks the DB delete).
- Frontend: new Download button on each document card (`DocumentsTab.js`/`AdminLibrary.js`),
  alongside the existing toggle/delete buttons.
- Tested via `testing_agent` iteration_122: 8/8 backend tests (TXT/PDF/DOCX byte-identical
  downloads, 403/404 guards, delete removes DB row + storage file, full
  upload→parse→toggle→delete lifecycle unaffected) + Playwright UI verification, 100%/100%.
  New regression suite: `tests/test_standards_documents_download.py`.
- Non-blocking notes from testing agent: storage failure on delete still creates a fresh orphan
  (same accepted tradeoff as the audio pattern — a future periodic reconciliation job could catch
  these); blob URL revoke timing tightened to `setTimeout(1000ms)` per review comment.


## Supervision Upload Download + Storage-Leak Fix — FIXED (Aug 2026), fully tested
Sibling fix to the standards-documents fix above, applied to the staff-facing "supervision
upload" path (`doc_uploads.py` — managers backfill evidence by uploading a staff member's
previous supervision PDF/DOCX). Confirmed the original file was discarded entirely after text
extraction — `supervision_uploads` had no `storage_path` column, and `full_text` only stored the
AI-extracted text, never the original bytes.
- New migration `m015_supervision_uploads_storage_path.py`: adds `storage_path TEXT` column.
  Applied via `init_db.py`.
- `doc_uploads.py`: `upload_supervision_doc()` now calls the existing `put_document()` (same
  function/bucket the standards-documents path uses, different prefix:
  `supervision/uploads/{uuid}.{ext}` vs `standards/docs/`) before inserting the row. New
  `GET /{upload_id}/download` endpoint. `delete_upload()` now fetches `storage_path` before the
  DB delete and best-effort removes the file after — added proactively (not explicitly requested)
  to avoid reintroducing the exact orphan-file bug just fixed on the sibling table.
- Frontend: new "Download original" button on `DocUploadReport.js`'s top bar, hidden for legacy
  uploads with no `storage_path` (pre-migration rows never had a file to download — testing agent
  caught this edge case, fixed by conditionally rendering the button + adding `storage_path` to
  `get_upload()`'s column list so the frontend can check it).
- Tested via `testing_agent` iteration_123: 8/8 backend tests (PDF+DOCX upload-then-download
  byte-identical, 403/404 guards, delete cleans storage, full AI lifecycle + evidence-update
  regression unaffected) + frontend spot-check, 100%/100%. New regression suite:
  `tests/test_supervision_upload_storage.py`.


## Date/UUID Column Type Fixes — FIXED (Aug 2026), fully tested
Audit found 6 columns still stored as plain TEXT. Investigation found the blanket "convert all 6"
suggestion was only safe for 5 — `evidence_feedback.evidence_item_id` is proven (live values like
`'cqc_69'`/`'cc_26'`, traced to `utils/ai.py`'s prompt templates) to be an AI-generated
type-prefixed string, not a UUID; converting it would break every future insert. Correctly left as
TEXT with a documented code comment in `review.py` explaining why.
- **4 new migrations** (`m016`-`m019`, registered in `migrations/__init__.py`, applied via
  `init_db.py`): `focus_topics.created_at` → `TIMESTAMPTZ` (plain oversight, same pattern as
  `m005`'s other 40+ columns); `meetings.meeting_type_id` → `UUID` + FK to `meeting_types.id`
  `ON DELETE SET NULL` (verified 100% NULL, zero writers anywhere in the codebase — passive,
  zero-risk); `schedules.start_date` + `supervision_uploads.meeting_date` → `DATE`;
  `meetings.date` → `TIMESTAMP` (deliberately **not** `TIMESTAMPTZ` — the column holds a naive
  local wall-clock value from `NewMeeting.js`'s combined date+time picker with no timezone
  attached, so `TIMESTAMPTZ` would silently misinterpret it as UTC).
- New `_encode_date`/`_decode_date` codec pair added to `database.py` (mirrors the existing
  timestamp codec exactly) so `DATE` columns keep returning plain `'YYYY-MM-DD'` strings —
  required for `schedules.py::next_due_date()`'s `date.fromisoformat()` call to keep working
  unchanged.
- Verified zero data loss: all 18 pre-existing `meetings.date` values (including messy mixed
  formats — some full timestamps with microseconds, some `HH:MM`-without-seconds, some pure
  dates) cast cleanly with a bespoke lenient regex, confirmed via direct DB query before/after.
- Tested via `testing_agent` iteration_124: 12/12 backend tests (schema types, zero data loss,
  meetings TIMESTAMP round-trip across 3 input formats, schedules/doc-uploads DATE codec
  read+write paths, date-filtered endpoints) + frontend E2E (NewMeeting.js date+time picker →
  API round-trip → Dashboard display), 100%/100%. New regression suite:
  `tests/test_iter124_date_uuid_migration.py`.
- Applied 1 non-blocking code-review fix: added the same `date.fromisoformat()` 422 validation
  already present on `PUT /schedules/{id}` to the two schedule-creation endpoints
  (`POST /schedules/` and `POST /schedules/bulk`), which previously would have 500'd on a
  malformed `start_date` instead of returning a clean validation error.


## SEC-DB-001: get_current_user Least-Privilege Fix — FIXED (Aug 2026), fully tested
Security audit (HIGH) found `deps.py::get_current_user` — the dependency injected into 142 of
~150 route handlers — opened the RLS-bypass `admin_pool` on EVERY authenticated request, exactly
backward from the earlier least-privilege DB role fix's intent. Root cause: `get_current_user`
only has a user_id (JWT `sub`), and `with_org()` needs org_id (which wasn't in the JWT) before it
can safely query — a genuine chicken-and-egg problem, plus a hard constraint discovered mid-fix:
`super_admin` accounts have `org_id = NULL` (confirmed live), so a naive "always use `with_org()`"
fix would have permanently locked out super-admin login.
- `org_id` added as a JWT claim at all 4 token-issuance sites in `auth.py` (login, verify-mfa,
  refresh, accept-invite) — `create_access_token()` now requires it.
- `deps.py::get_current_user` branches on the claim: **missing key** (pre-fix token) → clean 401
  "Session expired", self-healed by the frontend's existing axios auto-refresh (same pattern
  already used for the `pwd_ts` claim); **`org_id: null`** (super_admin — no single org) →
  legitimately keeps `with_admin()`, exactly the audit's own named exception; **real org_id** →
  now uses `with_org(org_id)` with an explicit `WHERE org_id=$2` predicate.
- `create_refresh_token`/`/auth/refresh`'s own lookup deliberately left untouched (audit names
  "sign-in" as an acceptable exception; it's not per-request).
- Verified end-to-end via curl before testing: all 3 normal roles get a correct org_id claim;
  super_admin gets `null` and still works; a hand-crafted pre-fix token gets a clean 401, not a
  crash; refresh mints a new token with org_id.
- Tested via `testing_agent` iteration_125: 14/14 backend pytest pass + live browser
  confirmation that the axios interceptor's silent refresh-and-retry works exactly as designed
  (overwrote a session cookie with a pre-fix token, page kept working, user never saw
  login/error). RBAC unaffected (attendee still 403 on admin endpoints). New regression suite:
  `tests/test_org_id_jwt_claim.py` (run with `-n 0` — parallel workers race on the shared MFA
  code column, unrelated to this fix).
- accept-invite's org_id claim was verified once via curl by the main agent, not re-tested
  end-to-end by the testing agent (would require a real invite record) — noted for future
  verification if that flow is touched again.


## Idle Session Timeout — COMPLETE (Sep 2026), fully tested
Audit follow-up to the earlier transaction-duration fix: `idle_in_transaction_session_timeout`
(stuck mid-transaction) was already fixed at 30s via `m010`, but `idle_session_timeout` (fully
idle, transaction-finished-but-connection-never-closed) was still `0` (disabled) — confirmed
live via `pg_stat_activity` showing Supabase-managed connections (pg_net, PostgREST, pg_cron)
idle for 7-30 days with nothing to reclaim them. Matches Supabase's own documented
best-practice value.
- **Fix (`migrations/m012_idle_session_timeout.py`)**: `ALTER DATABASE ... SET
  idle_session_timeout = '10min'` — same `ALTER DATABASE` (not `ALTER SYSTEM`, which needs
  true superuser this role lacks) pattern as `m010`, applies DB-wide to every role/pool.
- Verified via live query: both settings now persisted (`idle_in_transaction_session_timeout=
  30s`, `idle_session_timeout=10min`); post-fix smoke test confirmed login + meeting-list counts
  unchanged for admin (15) and attendee (7) roles — no regression.

## Least-Privilege DB Connection Role — COMPLETE (Sep 2026), fully tested
Security review flagged: the app's ONE connection pool authenticated as Supabase's `postgres`
role, which has `rolbypassrls=true` — every `with_admin()` call (123 sites) and, by extension,
the entire app's default connection identity, could silently bypass RLS with no DB-level
defence-in-depth if a Python-level org_id filter were ever missing. Verified live via direct
pg_roles queries before fixing (not just code-reading): `postgres` → `rolbypassrls: true`;
proved the bypass empirically (`with_admin()` returned 16 rows across 2 orgs in one query;
`with_org()` on a bogus org_id returned 0).
- **Fix (`migrations/m011_least_privilege_role.py`)**: new Postgres role `app_default`
  (LOGIN, `NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB`), granted membership in
  `app_rls_user` ONLY. Password generated via `secrets.token_urlsafe`, stored in
  `backend/.env` as `APP_DB_PASSWORD`/`APP_DATABASE_URL` (never hardcoded in the migration).
- **`database.py`**: now creates TWO pools — `pool` (main, authenticates as `app_default`,
  used exclusively by `with_org()`) and `admin_pool` (authenticates as `postgres`/BYPASSRLS,
  used exclusively by `with_admin()`). The RLS bypass is now a separately-provisioned
  escalation, not the app's default identity.
- **`server.py`**: startup order changed — `create_schema()` (migrations, incl. m011 creating
  `app_default`) now runs BEFORE `database.create_pool()`, since the pool's DSN depends on
  that role already existing. Reversing this order breaks boot with "role app_default does
  not exist".
- **Narrowed 2 of the 15 files that called `with_admin()`**: `routers/meetings.py`
  (`_list_meetings_data`'s non-admin/manager branch WITH a valid org_id) and
  `routers/portfolio.py` (`_build_portfolio_data`'s 2 org-scoped meetings/analyses lookups)
  moved to `with_org()`. Left the null-org_id edge-case branches in both files on
  `with_admin()` — genuinely needs the bypass (legacy/invited accounts with missing org_id;
  RLS would silently hide their own data). No RLS *policy* changes were needed — the
  existing `org_id = current_org_id` policy already matches what Python's explicit WHERE
  clauses were already filtering by.
- **Testing**: `testing_agent` iteration_115 — 64/64 backend tests pass (iter114 broad
  regression suite + iter115 exact-ownership isolation suite), all core frontend flows pass
  (login/dashboard/meeting-CRUD/portfolio/admin/super-admin across admin/attendee/manager
  roles). Cross-tenant and same-org isolation confirmed correct (no regression).
- **2 pre-existing bugs found & fixed during this pass (unrelated to the RLS change itself)**:
  (1) `frontend/src/utils/apiCache.js`'s cache was only cleared on logout, not on login — a
  user switch in the same tab within a cached endpoint's TTL could render the previous user's
  data. Fixed: `AuthContext.js`'s `login()`/`completeLogin()` now call `clearCache()` before
  prewarming. (2) `StaffPortfolio.js` called the admin/manager-only `/admin/standards`
  endpoint unconditionally, causing a 403 + console error for attendees viewing their own
  portfolio (gap-analysis sub_outcomes just don't render for them, harmless). Fixed: gated
  the fetch by `role === admin/manager`.
- **Remaining, NOT fixed (low priority, logged for later)**: `admin.py` (19 `with_admin()`
  calls) and `review.py` (11 calls) were classified as "needs review" during RCA but not
  audited line-by-line or migrated — most are likely legitimately org-scoped and could also
  move to `with_org()` in a future pass, same pattern as this session's fix.


## Transaction-duration fix (Sep 2026)
Verified report: `idle_in_transaction_session_timeout`/`idle_session_timeout`/`lock_timeout` were
all `0` (disabled) on the live DB, and `with_org()`/`with_admin()` (306 usages) wrap their whole
`async with` block in one transaction — a stalled request would hold its connection+locks with
nothing to reclaim them. The specific example cited ("Structure tab holds dozens of queries")
was already stale — all 6 known N+1 sites were fixed in a prior session. Found 2 additional
endpoints with the same underlying pattern while verifying (not originally reported):
`export_cqc_excerpts`/`export_cc_excerpts` also ran their Python redaction/grouping loop inside
`with_org`, same as the 2 originally-flagged `export_evidence`/`export_transcripts`.
**Fix**: (1) `migrations/m010_idle_timeout.py` — `ALTER DATABASE ... SET
idle_in_transaction_session_timeout='30s'` at the database level (applies uniformly to both
`with_org`/`app_rls_user` and `with_admin`/postgres sessions); confirmed via 2 restarts that the
app's own connection pool now enforces it. (2) All 4 export endpoints in `admin.py` now fetch
rows inside `with_org`, then release the transaction BEFORE the Python-side
redaction/CSV-row/PDF-context-building loop runs — mirrors the pattern those same functions
already used correctly for PDF/CSV generation itself. Verified all 4 still produce correct
output (2 populated PDFs, 1 correctly-empty CSV/PDF pair, 1 correct 404) against real seeded
data — confirmed the empty/404 cases trace to each endpoint's pre-existing status-filter logic
and this dataset, not the refactor (only fetch/process ordering changed, not what's queried).

## Supabase Auth Migration — Phases 1-4 COMPLETE (Sep 2026), fully tested
Full replacement of bcrypt password storage/verification with Supabase Auth, per explicit user
choice: (1) session/JWT layer stays 100% our own (deps.py, cookies, RLS untouched) — only
password identity moved to Supabase; (2) forced password reset for all existing users, no hash
carryover; (3) MFA made optional for admin/manager (was mandatory), kept mandatory for
super_admin only.
- **Phase 1**: `utils/supabase_auth.py` (create_user/verify_login/set_password/generate_recovery_link),
  `users.supabase_migrated` column, all 4 user-creation endpoints (`admin.py::create_user`,
  `org.py::invite_user_to_org`, `super_admin.py::create_org_user`/`invite_org_admin`) provision a
  Supabase identity (same UUID as `users.id`). Backfilled all 13 existing users, idempotent.
- **Phase 2**: `/api/auth/login` credential check routes to Supabase when `supabase_password_set`
  is true, else bcrypt fallback — added this SECOND flag after catching a real bug mid-build:
  gating on `supabase_migrated` alone (identity exists) would have locked out every real user,
  since Phase 1's backfill creates identities with NO password. MFA-optional 1-line gating fix
  (`_mfa_required_for_user`: super_admin always True, admin/manager check `mfa_enabled`).
  Replaced the Supabase SDK's `sign_in_with_password` (intermittent multi-second latency, one
  observed timeout) with a direct, stateless httpx POST to `/auth/v1/token?grant_type=password`
  — consistently ~0.3-0.6s, verified under concurrent load.
- **Phase 3**: `reset-password`, `change-password`, `accept-invite` all dual-write bcrypt +
  Supabase; `change-password`'s current-password check branches Supabase-or-bcrypt correctly.
- **Phase 4**: batch-sent forced-reset email to all 9 real remaining users (2 synthetic
  `@example.com` fixtures correctly rejected by Resend, harmless) via
  `scripts/send_supabase_migration_emails.py` — reuses the same token/endpoint as
  forgot-password. `jane@supervision.com` (JaneNew456!) and `user@supervision.com`
  (AnotherNew789!) fully migrated as live verification; everyone else has a pending, unexpired
  reset link and still logs in via bcrypt until they use it.
- **Post-testing fixes** (iteration_112 → 113, all verified): `deps.py::get_current_user`'s
  SELECT was missing `must_change_password`/`mfa_enabled` (broke the force-password-change
  redirect for ALL users, pre-existing bug surfaced by this work) — fixed. `OrgSettings.js`
  Security tab hardcoded MFA as mandatory/undisableable for admin+manager — now shows the real
  toggle and status. `reset-password`/`change-password` now return 503 instead of silently
  succeeding if an already-migrated user's Supabase write fails. `verify_login` maps 429/403 to
  a service-unavailable error instead of "wrong password". Fixed inconsistent "8 characters" vs
  actual 10-char policy copy on `/reset-password` and `/accept-invite`.
- **Known environment quirk (important for future work)**: frontend does NOT hot-reload —
  `yarn start` runs `vite build && vite preview`, so `sudo supervisorctl restart frontend` is
  required after every frontend source edit (~60s rebuild), otherwise the browser keeps serving
  the previous build. This caused a false "fix didn't work" signal during this session.
- **Not done (backlog, low priority, out of migration scope)**: stale "8 characters" copy in
  `UsersTab.js`, `SuperAdminDashboard.js`, `OrgStructure.js`, `PeopleHub.js` (same class of bug as
  the reset-password fix, just in admin-creates-user forms); unreachable super_admin branch in
  `OrgSettings.js` SecurityTab (super_admin never sees this panel — dead code, not a bug); missing
  `minLength={10}` on `AcceptInvite.js`'s password input (copy/JS validation already correct).
  Also not done: bcrypt fallback cleanup (removing bcrypt entirely once confidence is high) and
  native Supabase session tokens (deliberately kept out of scope per user's explicit choice).

## Multi-instance cache staleness fix (Sep 2026)
`utils/standards_cache.py`'s `_org_info` (org jurisdiction/service_type) was the only cache in
the app with **no TTL** — comment literally said "cached indefinitely," invalidated only via an
explicit `invalidate_org()` call from the request that made the change. On a single-instance
deployment this is harmless; on 2+ replicas behind a load balancer, an admin's jurisdiction
change only clears the replica that handled the click — every other replica keeps mapping
meeting evidence to the wrong regulatory framework (CQC vs CIW vs SSSC vs RQIA) forever, since
there's no cross-process invalidation signal (no Redis/pub-sub/LISTEN-NOTIFY).
Confirmed this was an inconsistency, not a deliberate design choice: every sibling cache in the
same app already had a TTL backstop for exactly this reason (`_custom_docs` 5min — "backstop in
case invalidation is missed"; `schedules._meeting_types_cache` 5min — "TTL ensures stale data
auto-expires **across workers**"; `admin._stats_cache` 60s).
**Fix**: gave `_org_info` the same TTL-backstop pattern (5 min, matching `_custom_docs`) — stores
`(fetched_at, info)` tuples now, `get_org_info()` self-expires stale entries. `set_org_info()`/
`invalidate_org()` callers and both real consumers (`review.py::_run_rescan_background`,
`utils/transcription_pipeline.py`) needed zero changes — `get_org_info()`'s return shape
(`{"jurisdiction":..., "service_type":...}` or `None`) is unchanged. No new infra — matches the
existing in-process-cache-with-TTL-backstop pattern already used everywhere else in this file.
Verified: immediate get returns fresh data, simulated 301s-old entry self-expires and is popped,
explicit `invalidate_org()` still works, backend restarts clean (`/api/health` 200, standards
cache warms 239 entries as before).

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

## Connection Pool Scaling Fix — FIXED (Sep 2026), fully tested
Audit item 3.2: `pool` (15) + `admin_pool` (10) = 25 connections/instance vs the DB's 60-connection
ceiling meant only 2 safe concurrent app instances. Confirmed (via `SEC-DB-001` above) that
`with_admin()` is now only a handful of genuinely-brief operations (super_admin requests,
login/MFA/refresh identity lookup, delete/org-admin flows, the job worker) — never held several
at once per request (grep-confirmed no `asyncio.gather`/`create_task` fan-out over `with_admin()`
within a single request handler), so shrinking its pool can't self-deadlock a request.
- **Fix**: `database.py`'s `admin_pool` `max_size` reduced 10 → 5. New per-instance ceiling:
  15 (main) + 5 (admin) = 20, restoring 3 safe concurrent instances under the 60-connection cap
  (up from 2).
- **Verified via `testing_agent`** (iteration_126): 10/10 tests — source-config checks, 4-role
  login regression, token refresh + super-admin org list (both `with_admin()`-dependent flows),
  10-concurrent-login burst (0 failures), live `pg_stat_activity` sampling under sustained load
  confirming `admin_pool` never exceeded its 5-slot cap and `app_default` (main pool) peaked at
  exactly 15. No pool-exhausted errors, no 500s, no timeouts. New regression suite:
  `tests/test_iter126_pool_size.py`.

## Export PDF/CSV PII Redaction — FIXED (Sep 2026), fully tested
Audit item (Issue 1, P1): every export endpoint correctly redacted the transcript body and AI
analysis text using a meeting's saved `pii_redactions`, but the attendee names and manager name
printed in the PDF/CSV header/metadata rows were pulled from the RAW (unredacted)
`meeting.attendees`/`sign_off_manager_name` fields — so a person's identity could still leak via
the metadata even though their name was redacted from the body text right below it.
- **Fix**: all 6 export functions now build a redacted COPY of the attendee list/manager
  name/signed-by name (via the existing `utils/redaction.py::apply_redactions_deep`/
  `apply_redactions_to_text` helpers, same ones already used for the body) before rendering,
  leaving the original DB row dict untouched: `admin.py`'s `export_evidence` (PDF+CSV),
  `export_cqc_excerpts`, `export_cc_excerpts`, `export_transcripts`; `review.py`'s `export_pdf`
  (also covers `sign_off_record.signed_by_name`) and `export_transcript`.
- **Deliberately unchanged**: `admin.py::export_cc_excerpts`'s `staff_label` (built from a
  separate `/users` query when a `staff_ids` filter is passed) — that's a UI filter label from a
  different data source, not meeting-specific redacted content.
- **Verified via `testing_agent`** (iteration_127): seeded a meeting with `pii_redactions`
  targeting the manager/attendee name and a control meeting with none; 12/12 tests pass — redacted
  meeting shows `[Redacted]` (not the raw name) in every PDF/CSV metadata field across all 6
  endpoints, control meeting's exports are byte-for-byte unaffected (no regression). New
  regression suite: `tests/test_pii_export_redaction.py`.

## Manual RLS Drift on 4 System Tables — FIXED (Sep 2026), fully tested
Audit item 3.3: `jobs`, `login_attempts`, `password_reset_tokens`, `schema_migrations` had RLS
enabled live (`relrowsecurity=true`) with `relforcerowsecurity=false` and zero policies — the
exact signature of someone toggling Supabase Dashboard's "Enable RLS" switch by hand (never sets
FORCE), not this codebase's own migration pattern (every table the code *does* manage always
pairs `ENABLE`+`FORCE` in one statement). None of these 4 are legitimate RLS candidates: the first
two are looked up by raw email/token pre-auth (no org context exists yet), `jobs` is a
background-worker/system table, `schema_migrations` is an internal ledger touched only by the
bootstrap connection.
- **Found a live (not just theoretical) consequence while investigating**: `app_rls_user` (used
  by `with_org()`) already has full table grants on all 4 tables via `m003`, so RLS-with-no-policy
  was the only thing blocking it — and it WAS actively blocking a real code path.
  `meetings.py::delete_meeting()`'s defense-in-depth `DELETE FROM jobs WHERE meeting_id=...`
  (runs inside `with_org()`) was silently a no-op: reproduced directly (seeded a job row, ran the
  exact delete, got `DELETE 0` despite the row existing). Not a data-loss bug — `m014`'s
  `ON DELETE CASCADE` FK (which bypasses RLS by design) was doing the real cleanup — but it proved
  the gap was already live, not just a future risk.
- **Fix**: new migration `m020_disable_rls_drift.py` — `ALTER TABLE ... DISABLE ROW LEVEL
  SECURITY` on all 4, with an in-file comment explaining why so it can't silently drift back.
  Zero new access granted (grants already existed); this only removes a row filter.
- **Verified via `testing_agent`** (iteration_128): 13/13 tests — live schema state (`relrowsecurity=
  false` confirmed on all 4, `auth.schema_migrations` correctly untouched as it's a different
  Supabase-managed table), migration ledger idempotent (re-run applies 0 new rows), full 4-role
  auth regression, `login_attempts` writes + lockout still correct, forgot-password still writes
  `password_reset_tokens` correctly, meeting-delete's `jobs` cleanup now genuinely deletes the row
  (previously silent no-op), `super_admin::delete_org`'s totals now correctly counts it. Zero
  regressions. New regression suite: `tests/test_iter128_rls_drift.py`.

## Dashboard Split into 6-Tile Hub + /meetings — SHIPPED (Sep 2026), fully tested
User found the old `/dashboard` page (meetings list + due-this-month widget + overdue banner +
stats cards) too busy. Mockups were shown and approved before any code was written.
- **New `/dashboard`**: instant-load 6-tile hub, zero data fetch (pure `user` from AuthContext).
  Admin/manager see all 6 (Meetings, Matrix→`/supervision-matrix`, People→`/organisation`,
  Evidence→`/admin/team` Team Themes, Resources→new `/resources`, Settings→`/settings`). Other
  roles (attendee) see 3 (Meetings, Resources, My Portfolio→`/portfolio/{own id}`). Meetings tile
  has a small "+" quick-add straight to `/meetings/new`.
- **New `/meetings`** (`Meetings.js`): the old Dashboard.js content, simplified per user's explicit
  instruction — "Due This Month" widget, overdue-actions banner, and the 3 stat cards all deleted
  entirely (not relocated). Kept: list, New Meeting button, search (title+attendee), status chips,
  date range, sort, org/team filter, load-all, historical section, admin-only inline delete. Same
  `/api/dashboard/` backend call + `/dashboard` cache key reused (backend untouched).
- **New `/resources`**: honest "coming soon" placeholder (Downloads + Supervision Course cards,
  no fake links) — no real content yet per user ("there will be useful downloads and supervision
  course in the future").
- Supervision Matrix (`/supervision-matrix`) unchanged, added small "View Schedules" link top-right
  per user request.
- Sidebar (`Layout.js`) unchanged otherwise — added one new "Meetings" nav item (user explicitly
  wanted everything else left where it is: "the idea of the tiles is to provide shortcuts to the
  most used pages... we could always add 3 more tiles in future if import/inspection/induction are
  as well used").
- All `navigate("/dashboard")` call sites that meant "back to my meetings list" (NewMeeting cancel,
  RecordingScreen stuck-recording buttons, MeetingReport back-arrow) repointed to `/meetings`
  with copy updated to "Back to Meetings". Login/logout/invite/reset redirects still correctly
  target `/dashboard` (the new hub) unchanged.
- **Verified via `testing_agent`** (iteration_130, frontend-only): 100% pass across admin/manager/
  attendee — tile visibility/routing, quick-add, simplified Meetings page, Resources placeholder,
  Matrix link, sidebar nav, all repointed back-buttons, no stray `/dashboard`-as-meetings-list
  references left in the codebase. Two flagged minor observations were self-verified by main agent
  as false positives: mobile 390px viewport has zero horizontal overflow on all 3 pages, and
  attendee's `/portfolio/{id}` page renders full portfolio content correctly (was a Playwright
  timing artifact in the test script, not a real bug).

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
- Refresh stale `tests/test_idor_sec001.py` fixtures (hardcoded passwords/meeting IDs are outdated)
  — explicitly deferred by user this session, skip until asked again.
- Orphan `teams` row with `setting_id=NULL` stays invisible in dashboard filters/dropdown.
- Extract `_DETAIL_COLS`/`_MEETING_DETAIL_COLS` duplication (meetings.py vs review.py) into a
  shared columns module — non-blocking code-review suggestion from iteration_119.
- Code-review notes from iteration_136 security audit (non-blocking, defence-in-depth):
  admin.py's 4 debug/repair endpoints (`debug-by-email`, `debug-user`, `debug-meeting-attendees`,
  `add-attendee`) still fetch via `with_admin()` then gate with an in-Python org_id compare —
  works, but a future refactor could accidentally delete the check with no DB-level backstop
  (unlike `delete_standard`, which uses `with_org()` so RLS enforces it structurally). Consider
  adding a unit test that guards the org_id-compare line, or splitting into a with_org() probe +
  with_admin() fallback only for super_admin. Also: `export_cc_excerpts` silently drops
  foreign-org staff_ids via RLS with no log line — consider `logger.warning(...)` when
  dropped-id-count > 0 for security visibility.

## Environments
Preview only in this session (`supervision-preview.preview.emergentagent.com`, Supabase project
`orsxhtlpybxoexdjrbnx`). Production is 1two.one — separate Supabase project `niapfxyeynkxxotgzweq`;
no DB credentials obtained this session, schema fixes have NOT been applied there yet.
