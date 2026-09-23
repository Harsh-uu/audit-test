# PRD — Supervision Meeting Compliance App

## Original Problem Statement
React + FastAPI + PostgreSQL (Supabase) app for UK adult social care providers. Managers record/upload supervision meeting audio; AI (Gemini primary, OpenAI fallback) transcribes, diarizes, and analyzes transcripts to surface CQC/Care Certificate compliance evidence, risks, achievements, learning needs, and actions. Strict RLS multi-tenant isolation. Includes EULA acceptance flow, Super Admin management/reporting, public resources, MFA authentication.

## Architecture
- Frontend: React + Vite + PWA (`/app/frontend`). IMPORTANT: `yarn start` = `vite build && vite preview` — a STATIC PRODUCTION BUILD, NOT a dev server. Frontend does NOT hot-reload; any frontend source change requires `sudo supervisorctl restart frontend` (a full rebuild) to take effect.
- Backend: FastAPI + AsyncPG + Postgres/Supabase (`/app/backend`). Backend DOES hot-reload (uvicorn --reload via WatchFiles).
- RLS via `app_default` role; `DATABASE_URL` (superuser/migrations) vs `APP_DATABASE_URL` (RLS-scoped app queries) — never mix these
- AI: `emergentintegrations`-routed Gemini (Vertex AI, europe-west2/London) as primary, OpenAI as fallback, orchestrated in `/app/backend/utils/ai.py`

## Key DB Schema
- `eula_versions`, `meetings`, `analyses` (incl. `ai_provider`, `initial_ai_provider`), `teams`
- `organisations.branding` (JSONB): `{primary_color, logo_path, speaker_colors: {manager, attendees: [4 hex]}}`

## What's Been Implemented (with dates)

### Prior sessions (through 2026-09-22)
- Meeting type dropdown, EULA in-place update, DB perf (statement_cache_size, get_current_user yield-dependency), meetings page consolidation, AI provider tracking + Super Admin AI Usage report, AI fallback retry, prompt fixes, Grafana/Loki logging, confidentiality/PII checker timeout fix.

### This session (2026-09-23)
- **Gemini evidence-scan tuning** (Google engineer feedback): generation-config split in `utils/ai.py` — `temperature=0.0/top_p=0.1/top_k=1` (precise) for all extraction/classification/mapping calls (`analyze_meeting`, `analyze_doc_for_evidence`, `analyze_custom_only`, `scan_pii_in_transcript`, `diarize_transcript`, `map_speaker_numbers_to_names`, `extract_document_criteria`, `check_prep_coverage`); `temperature=0.3` (warm, unset top_p/top_k) kept ONLY for human-facing conversational calls (`generate_meeting_summary`, `generate_prep_questions`, `generate_risk_suggestions`). Added a "CRITICAL SCAN MANDATE" 2-step reasoning instruction to evidence-scan prompts (DRY'd into shared `_CRITICAL_SCAN_MANDATE` constant). Tested 27/27 (iteration_152.json). `gemini-3.1-flash-lite` migration NOT done — user pivoted to this approach instead; parked, not abandoned.
- **`GET /api/meetings/{id}` perf fix**: was opening 2-3 separate DB connection/transaction blocks sequentially (get_current_user's own `with_org()` + route's own `with_org()` + a third `with_admin()` just for attendee email lookup) — each block costs ~5-6 round trips. Refactored to reuse `get_current_user_conn`'s connection (like `page-data` already did) and moved attendee-email enrichment onto that same connection (safe: `users_rls` migration m006 already scopes `users` SELECT to `app.current_org_id`, so the RLS-bypass `with_admin()` was never actually required for that query). Measured ~2.0-2.8s → ~0.85-1.0s. Root-caused the user's "title takes an age to load" complaint on RecordingScreen. Tested (iteration_153.json), cross-org isolation confirmed intact.
- **"Impact on Practice" mandatory prep question** (`generate_prep_questions` in `ai.py`): new guaranteed section, decoupled from the 6 standard `PREP_SECTIONS` and from the "bonus" section, so it survives regardless of any org-level section/template customisation. Asks "What difference has [specific named training/guidance/feedback] made to your practice?" grounded in real context. Has a code-level fallback-injection safety net (if the LLM ever omits/mislabels it) since this is meant to be guaranteed CQC evidence, not opportunistic. Frontend: `MeetingPrep.js` SECTIONS + `PrepAgendaTab.js` SECTION_COLORS both updated (teal). Tested (iteration_154.json), verified via live screenshot after required frontend rebuild.
- **Org-wide Speaker Colours (Branding settings)**: removed the per-meeting speaker colour picker from the Transcript tab's Speaker Manager panel (rename/swap kept). Added a "Speaker Colours" section to Settings > Branding: 1 Manager colour + 4 rotating Attendee-slot colours, applied ROLE-based (matches transcript speaker label against `meeting.attendees[].name` where `role` is manager/admin) instead of per-meeting/per-name, so colours are now identical across every meeting org-wide. Old per-meeting custom `speaker_colors` data is now ignored everywhere (not migrated/deleted, just no longer read). New: `utils/transcriptHelpers.js` `getRoleBasedSpeakerColors()` + `DEFAULT_ORG_SPEAKER_COLORS`; backend `organisations.branding.speaker_colors` (via `PUT/GET /api/org/branding`, exposed on `/auth/me`); Pydantic hex-format + exactly-4-length validation on `SpeakerColorsUpdate`. Tested 100% (iteration_155.json), plus 2 hardening fixes (hex regex, length=4) applied post-review and re-verified via curl.
- **Settings > Download Audio**: new tab (admin + the meeting's own sign-off manager only) to download a meeting's raw recording "if circumstances require it" — deliberately NOT on every meeting page. Respects the existing 5-minutes-post-signoff audio auto-deletion policy as-is (only works pre-signoff, by user's explicit choice — did not extend retention). Requires ticking a "Data Protection Notice" consent checkbox (org name dynamically interpolated) before the download fires; every download is written to `audit_logs` (action=`audio_downloaded`, includes user name + IP). Backend: `GET /api/meetings/downloadable-audio` (list, role-scoped) + `GET /api/meetings/{id}/audio-download?consent=true` (streams via existing `utils.supabase_storage.get_audio`) in `routers/meetings.py`. Frontend: new self-contained `components/admin/DownloadAudioTab.js` wired into `OrgSettings.js`. Tested 100% backend+frontend (iteration_156.json, incl. manager-vs-manager cross-ownership 403 and signed-off-meeting rejection); 2 code-review nits fixed post-test (filename extension now matches real content-type via Content-Disposition parsing instead of hardcoded `.wav`; confirmed XFF IP parsing should stay last-element, consistent with the existing rate-limit convention in `auth.py` for this proxy setup, not changed).
- **Audio downloads surfaced in per-meeting Audit Trail tab**: `audio_downloaded` audit_logs rows (already being written) now render as a flagged red "Raw audio downloaded" entry (AlertTriangle icon, same treatment as `meeting_backdated`) with actor/timestamp/IP, instead of only existing silently in the DB. `routers/review.py`'s `label_map_audit` + `flagged` tuple, `AuditTrailTab.js`'s `AUDIT_EVENT_CONFIG` — no new endpoint/migration needed, the existing unfiltered audit_logs query already picked these rows up. Tested 100% (iteration_157.json).
- Fixed stale `manager@supervision.com` credential (was on old bcrypt path despite `supabase_password_set=TRUE`) via `utils.supabase_auth.set_password()`, not `reset_test_pw.py`.

## Prioritized Backlog

### P0 / P1
- Organisation UX overhaul — user reviewing proposal, deciding which of the 5 items to tackle next (drill-down nav / whole-tree search / manager-scope-grouped dropdowns / users.setting_id denormalization fix / destructive-delete hardening for Settings)

### P2
- Storage Reconciliation Job, Rejection Trend Alerts, Live Connection Dashboard (unchanged from prior sessions)
- Intermittent UI glitch on Meetings page (tile click bounce) — BLOCKED/parked by user, not reproducible
- 80,000-char transcript truncation cliff-edge in `analyze_meeting` — monitor, not yet an issue
- Long-meeting (60+ min) real-world retest of the Gemini precise/warm + scan-mandate tuning to confirm it closes the first-scan-vs-rescan evidence gap in practice (only tested on shorter fixtures so far)
- Apply the same connection-reuse perf fix from `get_meeting` to other multi-connection endpoints if any are found slow
- Region migration (Iowa → London) — user is following up directly with support@emergent.sh; not something main agent can action

### P3
- Course Completion Tracker (unchanged)
- Team Themes chart tracking "Impact on Practice" answers over time (user-suggested spark, not yet built)
- 3+ speaker (team meeting) UI verification of attendee-slot colour cycling was not exercised live (no ready fixture) — logic verified by code review only

### This session (2026-09-23, cont'd) — Organisation UX deep-dive + Mini-Project 1
- Delivered a detailed UX/data-model proposal for `OrgStructure.js`/`PeopleHub.js` (drill-down nav, whole-tree search, manager-scope-grouped dropdowns, `users.setting_id` denormalization risk, destructive-delete hardening) — **proposal only, not yet built**, awaiting user prioritisation of items 1-5 before further work.
- **Mini-Project 1 (approved & shipped): consolidated the two duplicated "Edit User" modals.** `OrgStructure.js`'s inline modal (had MFA toggle, no Team field) and `PeopleHub.js`'s separate `EditUserModal` (had Team field, no MFA toggle) merged into one shared `frontend/src/components/admin/EditUserModal.js`, used by both. Added `mfa_enabled` to `GET /admin/people-stats` response (1-line additive, was missing — root cause of the field-parity gap). `OrgStructure.js`'s `openEditUser` now sources the full user record from its already-loaded `allUsers` (from `/admin/users`) instead of the trimmed structure-tree object. `EditUserModal`'s save always invalidates all 3 relevant caches (`/admin/users`, `/org/structure`, `/admin/people-stats`) in a `finally` block (even on partial failure). Testing agent found 1 bug (iteration_158.json): cross-tab cache sync gap — saving from the embedded Structure tab didn't refresh PeopleHub's parent-level `/admin/people-stats` state. Fixed via a new `onUserChanged` prop threaded from `PeopleHub` → `<OrgStructure embedded onUserChanged={handleRefresh} />` → called inside `OrgStructure`'s `onUserSaved`. Re-verified via live screenshot: Structure-tab team reassignment now shows correctly on People tab without manual refresh, no page reload needed. Test data (Demo User's team) restored to original state after verification.

## Testing Status
- Test reports: `/app/test_reports/iteration_149.json` through `iteration_158.json`
- Known regressions: None
- Credentials: `/app/memory/test_credentials.md` (manager@supervision.com password was reset this session via Supabase Auth)
