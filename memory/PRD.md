# Supervision 2.0 - PRD & Project Memory

## Product Overview
Supervision 2.0 is a web-based compliance evidence platform for UK care providers (England, Wales, Scotland, **Northern Ireland**) in a **single multi-jurisdiction deployment**. Users record supervision meetings, and the system automatically generates transcripts, summaries, and compliance mappings against the correct regional regulatory framework.

**Deployment URL Identifier:** supervison2
**Product Name:** Supervision
**Live URL:** https://1two.one

---

## Architecture
- **Frontend:** React (JavaScript), Tailwind CSS, Shadcn UI, Lucide React icons
- **Backend:** FastAPI (Python), PostgreSQL (Supabase) via asyncpg, native DB-level RLS
- **AI:** Direct OpenAI SDK (`o4-mini` reasoning_effort=high for analysis; `gpt-4o` for speaker mapping/diarisation/PII/prep)
- **Transcription:** AssemblyAI EU endpoint only (Dublin) — strict data governance, no Whisper
- **Email:** Resend (hardcoded `noreply@notify.1two.one`)
- **Storage:** Supabase Storage for audio + supervision docs; Emergent Object Storage for org logos only
- **Auth:** JWT (HttpOnly Secure Cookies since P3b fix Aug 2026), Email OTP 2FA. Cookie names: `supervision_access` (30min), `supervision_refresh` (7d). Backend supports Bearer token fallback for backward compat.

---

## Jurisdiction Model (Single-Deployment, Multi-Region)
- `organisations.jurisdiction` column: `'england'` | `'wales'` | `'scotland'` | `'northern_ireland'`
- `organisations.service_type` column: `'residential'` | `'domiciliary'` | `NULL` — **required for NI, NULL for other jurisdictions**
- `standards_entries.jurisdiction` column: same 4 values
- `standards_entries.service_type` column: `'residential'` | `'domiciliary'` | `NULL` — NI RQIA standards tagged by service_type; NISCC (NULL = shared)
- England orgs: CQC (47) + Care Certificate (16) = 63 standards
- Wales orgs: CIW (23) + AWIF (67) + SCW (12) = 102 Wales standards
- Scotland orgs: CI Quality Indicators (18) + SSSC Code (6) = 24 standards
- NI Domiciliary orgs: RQIA Dom (16) + NISCC Code (12) + NISCC Induction (7) = 35 standards
- NI Residential orgs: RQIA Res (15) + NISCC Code (12) + NISCC Induction (7) = 34 standards
- Schema migrations run on startup via `seed_all()` using `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`

---

## User Roles
| Role | Description |
|------|-------------|
| super_admin | Manage all organisations (fixed account) |
| admin | Full org access, manage users and standards library |
| manager | Create meetings, sign-off, view all meetings, upload org-specific documents |
| attendee | Record meetings, review assigned meetings |
| shared_reviewer | View signed-off meetings, add comments |

---

## Changelog (Recent)
- **Aug 2026 (37)**: **Meeting Report page redesign — reduce cognitive load, standardise style, background-friendly layout.** User's own words: page "does a lot and displays a lot," buttons/actions "too complicated" without explanation. Approved via static HTML mockups (not code) before implementation, per user's explicit request. Changes:
  - **Merged header**: meeting title + date moved into the shared org-colour bar (`Layout.js` gained an optional `headerCenter` prop, only used by `MeetingReport.js` — all other pages unaffected). Title uses `line-clamp-2 sm:line-clamp-1` (single line on desktop, up to 2 lines only on mobile where space is tight); org name truncates to 90px and hides its edit-pencil below `sm` to make room.
  - **No permanent sidebar, ever**: the always-visible right-hand "Compliance Evidence" panel was removed entirely. Compliance is now a tab, at every viewport width (was previously sidebar-on-desktop / tab-on-mobile only).
  - **Tab order**: Overview, Transcript, Compliance, Comments, Prep Agenda, Audit Trail (user-specified order). Comments tab shows a numeric count badge; Compliance tab shows a pulsing "Processing" badge only while `rescan_status==='processing'`; no other tab gets a badge. Tab row and content column both wrapped in the same `max-w-5xl mx-auto px-6` container so they left-align at wide viewports.
  - **Action consolidation**: the old wide row of buttons (Mark Reviewed / Sign Off / Export PDF / +Full text checkbox / Transcript / Send to Attendees / Share, all visible at once once signed off) replaced with ONE contextual primary button that changes through the lifecycle (Mark Reviewed → Sign Off → Send to Attendees) plus a "•••" more-actions dropdown (managers/admins only, only once signed off) containing Include-full-transcript checkbox, Export PDF, Export Transcript, Share with team.
  - Design blueprint generated via `design_agent` (see `/app/design_guidelines.json` — note: its font/typography suggestions were intentionally NOT adopted, kept existing app-wide Montserrat for cross-page consistency, which was the user's actual goal).
  - Verified via `testing_agent` across two passes (`/app/test_reports/iteration_68.json` then `iteration_69.json` after fixes) — 100% pass on final pass. Fixed during this work: mobile header overflow (title/org-name clamping), duplicated date, "You reviewed this" hidden below `md`, tab-row/content misalignment at wide viewports.
  - **Bonus bug fixes found + fixed this session**: `GET /api/dashboard` (no trailing slash) caused a 307→http redirect blocked by CSP on some loads — `Dashboard.js` now calls `/dashboard/`. `mark_reviewed` in `review.py` had the same JSONB double-encoding bug class as the PII-redactions fix below — fixed the same way.
- **Aug 2026 (36)**: **PII confidentiality check moved earlier in the processing flow (UX improvement).** Previously the manager waited through all 3 processing steps (Upload → Transcribe → Map Compliance Evidence) before the "Confidentiality Check" PII gate appeared as a 4th blocking step. Now the gate appears as soon as the transcript is ready (`meeting.status='analyzing'`) — while compliance mapping is still running in the background — so the manager reviews/redacts PII instead of staring at a spinner. `RecordingScreen.js` now hands off to the report page as soon as status leaves `processing`/`transcribing` (was waiting for `analyzing` too). `MeetingReport.js` `shouldShowPIIGate` no longer requires `meeting.analysis` — only requires `meeting.transcript` and excludes `recording`/`processing`/`transcribing`/`processing_failed`. If the manager finishes the PII check before mapping completes, they fall through to the existing 3-step progress-bars screen (step 3 active) unchanged, then auto-transition to the full report — no new UI built, existing bars screen reused per user's request to preserve current design. No backend changes needed: `/api/review/{id}/scan-pii` and `complete-pii-review` already only depended on the transcript, not the analysis. PIIReviewGate.js visual design untouched. Verified via testing_agent (4 scenarios: mid-mapping PII check + auto-transition, non-manager unaffected, processing_failed suppresses gate, sign-off/PDF/redaction regression) — all passed.
  - **Bug fix (found during this testing pass): stale attendees blocked sign-off.** `markReviewed()` in `MeetingReport.js` only patched `meeting.status` locally and never refetched `meeting.attendees`, so the sign-off confirm modal showed a false "attendee has not reviewed" warning until a manual page refresh. Fixed by calling `fetchMeeting()` after a successful mark-reviewed POST.
  - **Bug fix (found during this testing pass): `pii_redactions` double-JSON-encoded on write.** `complete_pii_review` in `review.py` called `json.dumps(clean_redactions)` before passing it to a `$N::jsonb` parameter — but asyncpg already has a `jsonb` type codec (`encoder=json.dumps`) registered in `database.py`, so the value was serialized twice, leaving `jsonb_typeof(pii_redactions)='string'` instead of `'array'` in Postgres (confirmed via direct query). Reads were defensively unwrapping the extra layer so it was not user-visible, but fragile. Fixed by passing `clean_redactions` (the raw list) directly — codec now encodes it once. Verified via direct DB check post-fix: `jsonb_typeof` now correctly returns `'array'`. **Note for future agents**: this same `json.dumps(...)` + `::jsonb` pattern exists in many other write call sites across `processing.py`/`review.py`/`meetings.py` (analyses.actions/risks/mappings, transcripts.safety_warnings, etc.) and is very likely also double-encoding those columns the same way — it currently causes no visible bugs because every read path already goes through `_jlist`/`_jdict`/`_ensure_list` guards (built for the *documented* `with_org()` RLS-role-switch codec-reset issue, see `CONTRIBUTING.md`) which incidentally also unwrap this extra encoding layer. Flagged in backlog as a systemic cleanup item, not fixed everywhere — low risk today, but worth an eventual full audit.
- **Feb 2026 (35)**: **AI Safeguarding Prompt — Three new detection layers added to `ANALYSIS_SYSTEM_PROMPT` in `ai.py`**: (1) **SAFEGUARDING BOUNDARY VIOLATIONS** — flags any person going through a service user's personal belongings/drawers/private spaces, with high severity if financial gain is implied; (2) **STAFF PASSIVITY IN SAFEGUARDING SITUATIONS** — flags separately when a worker describes witnessing a safeguarding concern but not escalating/challenging/reporting it; (3) **COLLECTIVE NORMALISATION (team-wide)** — flags when a team-wide pattern of accepting a concerning behaviour is described (e.g. "staff don't say anything, it's just become normal") as systemic cultural drift. Also updated the existing **NORMALISATION** communication pattern block to explicitly include physical boundary violations, team-wide signals, and reference to the new dedicated risks above. Prompt length: 39,783 chars. All 6 targeted phrases confirmed present in prompt.
- **Aug 2026 (34)**: **ROOT CAUSE FOUND + FIXED — Production login bounce fully resolved.** `REACT_APP_BACKEND_URL` was being baked at build-time into the JS bundle as the PREVIEW URL (`https://evidence-link-4.preview.emergentagent.com`). On production (`1two.one`), all API calls went to the PREVIEW origin (cross-site). `SameSite=Lax` HttpOnly cookies are never sent for cross-site XHR → every post-login API call returned 401 → `setUser(null)` → bounce. **Fix**: Changed ALL 7 files (`AuthContext.js`, `Login.js`, `TranscriptTab.js`, `Layout.js`, `AcceptInvite.js`, `ResetPassword.js`, `SuperAdminDashboard.js`) from `process.env.REACT_APP_BACKEND_URL` to a relative `"/api"` path. K8s ingress routes `/api/*` to the backend on both environments. The built bundle now contains ZERO references to the preview URL — same-origin cookies work on any domain.


- **Aug 2026 (33)**: Production login bounce fix — three layered fixes: (1) **SW `skipWaiting` + `clientsClaim`** added to `vite.config.mjs` Workbox config — new SW now activates immediately on install and claims all open clients, eliminating the stale-chunk crash (old index.html referencing old content-hash chunks → MIME-type error → React crash → login bounce); (2) **RouteErrorBoundary** updated to nuke all SW caches (`caches.keys → caches.delete`) before `window.location.reload()` on chunk errors — belt-and-suspenders so even if old Workbox precache entries survive an update, they are cleared before the fresh-chunk reload; (3) **AuthContext.js `loginGracePeriodEnd` ref** — 10-second post-login grace period added to the interceptor catch block; `setUser(null)` is suppressed within 10 s of login completing, covering the `_prewarmDashboard()` race condition (unawaited fire-and-forget calls that complete after `isLoggingIn` is cleared). Both `login()` and `completeLogin()` set the grace period in their `finally` blocks.


- **Aug 2026 (32)**: Production audio upload fix — root cause identified: `RecordingScreen.js` sends `Content-Type: application/octet-stream`; production Supabase bucket had strict MIME allowlist that excluded it → 400 Bad Request. User removed allowlist restriction (immediate fix). Code hardened in `processing.py`: content-type now normalised to `audio/webm` for any non-audio MIME type before Supabase upload, so re-adding the allowlist (`audio/webm`) will work correctly in future.
- **Aug 2026 (31)**: Dashboard performance — combined `GET /api/dashboard` endpoint (asyncio.gather), pre-warm on login in AuthContext, paginated meetings (first 50, "Load all" button), font preload hint for Montserrat (Work Sans headings + IBM Plex Sans body) with a single unified **Montserrat** (400/600/700) loaded once from Google Fonts. Removed `@import` from `App.css`, updated `index.html` link. Deleted dead CRA leftover `public/index.html`. Cleaned up all temp mockup HTML files from `public/`.
- **Aug 2026 (30)**: Font cleanup — replaced dual-font setup (Work Sans headings + IBM Plex Sans body) with a single unified **Montserrat** (400/500/600/700). Fixed in App.css, index.css, tailwind.config.js, index.html. Deleted dead CRA public/index.html.
- **Aug 2026 (29)**: Service Worker cache via vite-plugin-pwa (Workbox). 55 build assets precached. Runtime strategies: NetworkOnly for auth/recording/processing, StaleWhileRevalidate for /admin/standards + /org/structure (1h TTL), NetworkFirst for /meetings + /review (5 min TTL, 4s timeout), CacheFirst for Google Fonts. SW file served with Cache-Control: no-cache for update checks. autoUpdate mode — silent installs, no user prompt needed.

: Cache key collision fix. `apiCache.js` `cachedGet` now includes serialised query params in the cache key via `_cacheKey(url, config)`. Root cause: `TeamInsights.js` was calling `cachedGet("/admin/standards", { params: { type: "care_cert" } })` which stored the care-cert-only response under the bare `/admin/standards` key; `AdminLibrary.js` subsequently fetched the same key (no type filter) and received the stale care-cert-only response → CQC (0). Fix: `_cacheKey` appends `?type=care_cert` to the key when params are present, so each distinct query is cached independently. `invalidateCache` patterns still work because they use `key.includes(pattern)` substring matching.

: Three targeted fixes. (1) **Repetition checker false positives**: sentence-level threshold raised 3→5 occurrences, minimum sentence length raised 5→20 chars — natural filler repetitions ("yeah yeah", "I see") no longer trigger hallucination warnings; consecutive-chunk looping threshold raised from 3→4 identical consecutive chunks to reduce false positives; (2) **Phantom first audit-trail entry**: `_parse_turns()` in `review.py` now handles continuation lines (lines without a speaker colon) by appending them to the previous turn body — matches the frontend `parseSpeakerText()` behaviour, so the round-trip comparison is stable and GPT-4o multi-line output no longer generates phantom `transcript_text_edited` audit entries; (3) **Processing page text**: changed "you can safely leave and come back" to "Do not close or refresh this page whilst processing the meeting" in both `RecordingScreen.js` and `MeetingReport.js`.


- **Aug 2026 (26)**: SEC-001, SEC-003 fixes + RLS optimisation + P3d CORS. (1) **SEC-001 scope bypass**: `list_users` (`admin.py`) now ignores `?ignore_scope=true` for managers — `ignore_scope` is only honoured for admins; managers always get their server-derived team/setting scope regardless of the URL flag; (2) **SEC-003 manager out-of-scope transcript access**: `get_review_data` (`review.py`) now applies the same `get_scoped_staff_ids` scope guard for team/setting-limited managers — returns 404 if none of the attendees fall within the manager's assigned scope; (3) **RLS `current_setting()` performance**: all `init_db.py` policies updated from `current_setting(...)` → `(SELECT current_setting(...))` — live DB confirmed all 10+ `pg_policies` rows now use the subquery form (evaluated once per statement, not per row); (4) **P3d CORS**: `https://1two.one` added to `CORS_ORIGINS` in backend `.env`. All 24 JWT+IDOR security tests still green post-fixes.

 Security regression suite created (`backend/tests/test_security_jwt_idor.py`) — replaces planned Strix pentest targeting the two identified gaps (JWT weaknesses + IDOR). 24 tests across 3 classes: `TestJWTAttacks` (9 JWT tests: alg=none, wrong secret, expired, refresh/mfa_pending/no-type token confusion, non-existent sub, JWT role escalation payload bypass — all return 401/no escalation); `TestIDORHorizontal` (8 tests: staff blocked from meeting details, review data, comments GET/POST, processing retry, sign-off, and admin/team-insights endpoints for a meeting they are not on); `TestIDORCrossTenant` (6 tests: Org A token blocked from Org B meeting, review, comments GET/POST, processing, and no Org B data in team-insights). Fixtures create and tear down test data directly via asyncpg. Session fixture clears rate-limit table before suite. Also fixed `job_worker.py` backoff query: `updated_at < (CURRENT_TIMESTAMP...)` → `updated_at::timestamptz < ...` (was comparing text to timestamptz, throwing a PostgreSQL type error on every poll cycle).

 Five LOW code review findings resolved. (1) **API cache cleared on logout** — added `clearCache()` export to `apiCache.js` (wipes the entire `_cache` Map); called in `AuthContext.js` `logout()` so a second user logging in on the same tab is never served the previous user's cached `/admin/*`/`/org/*` data; (2) **TeamInsights stale-request guard** — both `load` and `loadRegisters` callbacks in `TeamInsights.js` now use a per-callback `useRef` counter; responses that arrive after a newer request was dispatched are discarded before `setData`/`setRegisters`; `setLoading(false)` also only fires if the ref still matches, preventing spinner flicker; (3) **Input length validation** — added Pydantic `Field(max_length=...)` constraints to `CommentRequest.text` (2 000), `UpdateSummaryRequest.summary` (10 000), `FindReplaceRequest.find` (500), `FindReplaceRequest.replace` (1 000), `UpdateEvidenceRequest.notes` (2 000), `UpdateRiskRequest.notes` (2 000), `FocusTopicCreate.topic` (500), `GeneratePrepRequest.focus_topic` (500), `PrepSave.focus_topic` (500); oversized payloads now return HTTP 422 before reaching the DB; (4) **Silent failure in forgot-password** — `except Exception: pass` changed to `except Exception as e: logger.error(...)` so email delivery outages surface in logs; (5) **Dead code removal** — `MFA_REQUIRES_ROLES` constant deleted; `_mfa_required_for_role` `mfa_enabled` parameter removed (was always ignored); call site updated.

 Medium security fix — comment endpoints access control. `POST /{meeting_id}/comments` and `GET /{meeting_id}/comments` previously checked only org membership (RLS), allowing any authenticated org member to read or post comments on colleagues' private supervision meetings. Both endpoints now apply the same attendee/creator/shared-reviewer guard used by `get_review_data` for non-admin/manager roles: fetches `attendees`, `shared_with`, `created_by` columns and returns 404 if the caller is none of those. Admins and managers bypass the guard (unchanged). Regression-tested: attendee calling GET/POST on a meeting they are not part of returns HTTP 404.

 Four LOW code review findings resolved. (1) **sign_off stats cache bust** — `sign_off` in `review.py` now calls `_admin_stats_cache.pop(org_id, None)` immediately after the status update (was missing; mark_reviewed and approve_reopen already had it — lagging 60 s stat count fixed); (2) **Rate-limit off-by-one** — `utils/rate_limit.py` CASE WHEN changed from `count + 1 >= $3` → `count + 1 > $3`; effective allowance now equals the declared `max_attempts` value (was `max_attempts - 1`; meeting creation was capping at 29/hr not 30, MFA at 4 not 5); (3) **Find & Replace single-occurrence invisible in Speaker View** — `find_replace_transcript` with `replace_one=True` previously skipped the `speaker_text` field, so the replacement was invisible in the diarised UI; the `if field != "text": continue` guard removed so both fields are updated at the same occurrence index; (4) **`_meeting_types_cache` TTL** — changed from an indefinite module-global `dict[str, list]` to `dict[str, tuple[float, list]]` with a 5-minute TTL (`time.monotonic()`), matching the `_admin_stats_cache` pattern in `admin.py`; stale data now auto-expires across worker restarts even if an explicit `pop` is missed.

 Job queue retry hardening — two targeted fixes to `job_worker.py`. (1) **Stuck-at-max-attempts jobs now permanently fail**: `_recover_stuck_jobs()` previously skipped jobs stuck in `processing` with `attempts >= MAX_ATTEMPTS` (they stayed stuck forever, silently lost). Now runs a second UPDATE that transitions these to `status='failed'` with an explanatory error message; (2) **Linear retry backoff added**: `_claim_next_job()` now applies a per-row SQL backoff of `attempts × 30 seconds` before re-claiming a retried job (`OR updated_at < CURRENT_TIMESTAMP - (attempts * interval '30 seconds')`). Fresh jobs (attempts=0) are claimed immediately. No schema change required.


- **Aug 2026 (20)**: Performance hardening — three improvements. (1) **GZip middleware** added to `server.py` (`GZipMiddleware, minimum_size=500`) — compresses all API JSON ≥500 bytes; verified 83% compression ratio on representative payloads; (2) **13 frontend cache misses fixed** — 9 pages (`AdminLibrary`, `CareCertPrep`, `MeetingPrep`, `NewMeeting`, `OrgSettings`, `RecordingScreen`, `Schedules`, `SetPassword`, `UploadSupervision`) had TTL entries in `apiCache.js` but called raw `axios.get`; all converted to `cachedGet`; (3) **3 DB indexes added** — `meetings(org_id, status, created_at DESC)` composite, `schedules(staff_user_id)`, `audit_logs(org_id, timestamp DESC)`. One planned index (`login_attempts`) dropped — identifier is already the PRIMARY KEY.
- **Aug 2026 (19)**: Code audit fixes — 4 confirmed defects resolved. (1) **Admin password reset 404 fixed** — `reset_user_password` in `admin.py` was missing its `@router.post("/users/{user_id}/reset-password")` decorator; also upgraded weak-length check to full `validate_password_strength` + sets `must_change_password=TRUE`; (2) **Silent audio loss on storage failure fixed** — `processing.py` now raises HTTP 502 if `put_audio` throws, instead of swallowing the error and enqueuing a doomed job; (3) **Invite accept refresh token fixed** — `accept_invite` was issuing refresh tokens with `pwd_ts=0.0` while setting `password_changed_at=now`, causing every invited user to be logged out ~30 min after accepting; now passes `_to_pwd_ts({"password_changed_at": now})`; (4) **GDPR audio deletion now restart-safe** — `_sweep_audio_deletions()` added to `job_worker.py`; sweeps meetings stuck in `grace_period` (>5 min elapsed) on startup and every ~60 s; belt-and-suspenders alongside the existing BackgroundTask.
- **Aug 2026 (18)**: Dead code cleanup + payload size hardening. (1) Removed dead cookie read from `POST /api/auth/refresh` — only Authorization header used; (2) Removed dead `localStorage.setItem("supervision_user_refresh","1")` from `SetPassword.js`; (3) Removed `refresh_tokens` table entirely — CREATE TABLE, all DELETE queries in `auth.py`/`super_admin.py`, and GRANT reference removed; `DROP TABLE IF EXISTS refresh_tokens` migration added to `init_db.py` to clean up existing deployments; (4) Added `ContentSizeLimitMiddleware` to `server.py` — path-aware Content-Length header check: `/api/processing/` → 360 MB, `/api/doc-uploads/` → 26 MB, `/api/admin/standards/upload` → 30 MB, `/api/org/branding/logo` → 3 MB, all other endpoints → 1 MB; (5) Added early Content-Length pre-check in `processing.py` audio upload handler — rejects oversized audio before streaming into memory (413). Verified: 413 fires for oversized Content-Length, normal requests pass through cleanly.
- **Aug 2026 (17)**: API Response Trimming — all 7 findings from response audit. (1) `GET /meetings/` list now uses explicit `_LIST_COLS` SELECT (23 columns) — excludes `recording_events`, `paused_periods`, `sign_off_record`, `reopen_record`, `audio_deletion_status`, `audio_grace_period_started_at`, `audio_deleted_at`, `recording_notice_shown_at`, `pii_redactions`, `diarize_status`, `rescan_status`, `retranscribed_at`; `_parse_meeting_row` updated to only touch keys present in row; (2) `GET /meetings/{id}` and `GET /review/{id}` strip raw `text` from transcript when `speaker_text` is present (~50KB saving per report load); (3) reviewer_comments SELECT changed to explicit columns (drops `org_id`, `meeting_id`); (4) `GET /auth/me` strips `password_changed_at`, `is_active`, `updated_at`; (5) `POST /auth/login` MFA path no longer echoes `email` in response; (6) `GET /admin/standards` strips `org_id`, `jurisdiction`, `service_type`, `created_at`, `is_active` from each row; (7) `logging` module added to auth.py for non-critical rate-limit warning.
- **Aug 2026 (16)**: API Rate Limiting — all 6 endpoints. Backend: Injected `check_rate_limit` from `utils/rate_limit.py` into 6 unprotected endpoints: (1) `POST /auth/login` — secondary IP-wide limit 20/15min using `login_ip:{ip}` identifier (harvested via X-Real-IP/X-Forwarded-For rightmost hop, spoofing-safe); (2) `POST /auth/verify-mfa` — 5/30min per `mfa_uid:{user_id}` (MFA brute-force protection); (3) `POST /org/invite-user` — 20/60min per `invite:{org_id}` (email spam prevention); (4) `POST /meetings/` — 30/60min per `create_meeting:{user_id}` (DB exhaustion prevention); (5) `POST /schedules/bulk` — 5/60min per `bulk_sched:{org_id}` (bulk abuse prevention); (6) `POST /admin/export-evidence` and `POST /admin/export-transcripts` — shared 10/60min bucket per `export:{user_id}` (storage exhaustion prevention). All limits use the existing `login_attempts` DB table. All 6 limits verified via curl testing against live DB.
- **Aug 2026 (15)**: Optimistic rendering — Tier 1 & 2. MeetingReport: `updateEvidence` now patches `analysis.evidence_mappings` inline with functional setState snapshot + revert on error (eliminates full fetchMeeting on every evidence toggle); `markReviewed` flips badge to 'reviewed' immediately then corrects to server's authoritative status ('in_review' if not all reviewed); `signOff` flips badge to 'signed_off' immediately, full refetch only on success to get sign_off_record; `addComment` appends a temp comment + clears input immediately, replaces with server record on success, reverts on error; `saveSummary` closes edit mode and updates `analysis.edited_summary` inline, no refetch; `handleReopenRequest` sets `reopen_requested:true` immediately; `handleApproveReopen` sets `status:'reviewed'` immediately. Schedules: `deleteSchedule` filters the row out immediately, restores full list on error. Build: ✓ clean in 4.1s, 0 warnings.
- **Aug 2026 (14)**: Stats cache hook + Tier 3 skeletons. Backend: imported `_admin_stats_cache` into `review.py` and `processing.py`; bust the 60s per-org cache at all 4 status-transition write sites: `mark_reviewed` (→reviewed/in_review), `sign_off` (→signed_off), `approve_reopen` (→reviewed), and the AI processing complete (→in_review). Frontend: added `<Skeleton>` shimmer loaders to TeamInsights (filter bar + 6 matrix row stubs with avatar circles), PeopleHub staff table (stat strip + search bar + 8 avatar/name/badge rows), InspectionPrep (page header + filter pills + 6 evidence card outlines), SupervisionMatrix (header + status chips + filter tabs + 6 schedule row cards with progress bar). Build: ✓ clean in 3.7s, 0 warnings.
- **Aug 2026 (13)**: Skeleton loaders for Tier 1 & 2 pages. Imported `<Skeleton>` (Shadcn `animate-pulse bg-primary/10`) into 5 pages. Dashboard: 6 shimmer meeting cards (title bar + date row + status badge pill) replace the centred spinner in the meeting list area. MeetingReport: full sticky top-bar skeleton (back + title + date + badge + action buttons) + 5-tab shimmer row + 7/5 two-panel content skeleton. StaffPortfolio: avatar circle + name/role + 5-stat strip + two-column evidence grid skeleton. AdminLibrary: page h1/subtitle + 4 shimmer tabs + 8 table-row skeletons (replaces bare "Loading…" text with no Layout). OrgStructure: page header + two-panel (3 setting card skeletons with team rows + unassigned panel with 5 avatar rows). Build: ✓ clean in 4.3s, 0 warnings.
- **Aug 2026 (12)**: P3 hardening. H1: Added `Content-Security-Policy` meta tag to `index.html` covering the SPA shell — `script-src 'self'` plus SHA-256 hash of the DataCloneError suppressor inline script; `font-src` allows Google Fonts; `object-src 'none'`; `form-action 'self'`. H2: Fixed `forgot-password` IP extraction to prefer `X-Real-IP`, fall back to rightmost `X-Forwarded-For` hop (proxy-set, not client-controlled), then `request.client.host`. H3: Tightened FastAPI CORS from `allow_methods=["*"], allow_headers=["*"]` to explicit allowlists (`GET/POST/PUT/PATCH/DELETE/OPTIONS`, `Authorization/Content-Type/Accept`); added startup `CRITICAL` log if `CORS_ORIGINS` ever contains `*`.
- **Aug 2026 (11)**: Security audit fixes. SEC-001: `create_refresh_token` now embeds `pwd_ts` (Unix float of `password_changed_at`). Refresh endpoint rejects tokens with no `pwd_ts` claim and any token where `pwd_ts < db password_changed_at`, cutting off stolen tokens immediately after a password reset. SEC-002: Loki log line in `ai.py` changed from logging the full `warnings` list (containing verbatim transcript excerpts) to a count-only message — no PHI/PII leaves the app boundary. SEC-003: Added `_assert_setting_scope` and `_assert_team_scope` helpers to `org.py`; applied to all 8 write handlers: `create_setting` (org-level only), `update_setting`, `create_team` (blocks team-scoped managers), `update_team`, `delete_team`, `add_member`, `remove_member`, `assign_user_to_team`. Backend healthy, token and scope behaviour verified via curl.
- **Aug 2026 (10)**: Client-side cache audit. Extended `apiCache.js` TTL_MAP with `/schedules/due` (30s), `/schedules/` (30s) ordered after the more-specific `/schedules/meeting-types` and `/schedules/due` entries. Switched 9 raw `axios.get` calls to `cachedGet` across Dashboard, AdminLibrary, InspectionPrep, SupervisionMatrix, StaffPortfolio, OrgStructure. Added `invalidateCache()` calls before post-mutation `fetchAll()`/`refreshData()` in AdminLibrary (5 handlers), Schedules (2 handlers), OrgStructure (6 handlers via new `refreshData` wrapper). StaffPortfolio now embeds `?type=care_cert` directly in the URL string so the cache key is unique. Build clean — 0 warnings.
- **Aug 2026 (9)**: In-memory caching implemented. `admin.py` `get_stats`: 5 COUNT(*) queries now cached per `org_id` with 60-second TTL using `time.monotonic()` (no new dependency). `schedules.py` `list_meeting_types`: results cached indefinitely per `org_id` in `_meeting_types_cache`; explicit invalidation on POST/PUT/DELETE meeting-type writes. Pattern matches `standards_cache.py`. Backend verified healthy (200 OK), meeting-types endpoint tested and returning correct results.
- **Aug 2026 (8)**: P0/P1 Security Audit fixes applied. SEC-001: `deps.py` now rejects `mfa_pending`/`refresh` JWT tokens on all guarded endpoints (type != "access" → 401). SEC-002: `utils/seed.py` emits a CRITICAL log warning at startup if `SUPER_ADMIN_PASSWORD` is default/weak (<12 chars or in known-weak list). SEC-003: `admin.py` `update_user` endpoint — managers blocked from modifying admin/super_admin accounts; email field stripped from manager updates; admins blocked from modifying super_admin accounts. SEC-004: `review.py` `update_risk` and `get_risk_suggestions` now require manager/admin role (attendees get 403). SEC-005: `server.py` validates `JWT_SECRET` at startup — RuntimeError if absent, CRITICAL warning if <32 chars or known default. All 5 fixes curl-tested and confirmed.
- **Aug 2026 (7)**: CRA → Vite 5 migration complete. Removed react-scripts, @craco/craco, cra-template. Installed vite@5.4.21, @vitejs/plugin-react@4.3.4. Created /app/frontend/vite.config.js (esbuild.include + loader:jsx for .js files, define for REACT_APP_BACKEND_URL, allowedHosts:true, hmr.clientPort:443). Moved index.html to project root. Updated package.json scripts (start→vite, build→vite build). Cleaned webpack/CRA resolutions. Result: 66 vulns → 8 (ALL dev-toolchain, zero production bundle). Build time: ~4s (was 30+s). Testing 100% pass (iteration 65).
- **Aug 2026 (6)**: Security hardening — XSS audit confirmed (React auto-escape, Pydantic, `saxutils.escape`). Prompt injection hardening: `_PROMPT_INJECTION_GUARD` prepended to all 6 AI system prompts; transcript/document content wrapped in XML delimiters (`<transcript>`, `<document>`) in all user prompts; `custom_prompt` field sanitized via `_safe_custom_prompt()`; supervisee names sanitized via `_safe_name()` before embedding in system prompts. All in `ai.py`.
- **Aug 2026 (5)**: Hardened login rate limiting — threshold reduced 5→3 failed attempts; attempt INSERT now committed in its own transaction (was rolling back inside `with_admin()` transaction on HTTPException); identifier changed from `IP:email` to `email-only` (Kubernetes ingress pod IPs are unreliable across replicas); 2nd-failure response now shows amber "Forgot Password" hint in UI; 3rd-failure response shows lock message; 4th+ returns HTTP 429. only working on first click — `highlightKey` counter increments on every click, forcing scroll to re-fire.
- **Aug 2026 (3)**: Fixed confidentiality checker — title abbreviation matching (Mr/Mr.) + all named colleagues flagged + better AI excerpt selection.
- **Aug 2026 (2)**: Fixed `cannot extract elements from a scalar` error crashing the processing pipeline — JSONB scalar guard on all `jsonb_array_elements(attendees)` call sites.
- **Aug 2026**: Fixed `PUT /api/schedules/{id}` crashing with `asyncpg DataError: expected str, got date`.

---

## Core Features Implemented

### Auth & Security
- [x] JWT authentication with role-based access control
- [x] Email OTP 2FA — mandatory for super_admin, optional for admin/manager
- [x] Brute force protection, is_active check on every request
- [x] Password policy (10+ chars, upper, lower, number, special)
- [x] Force password change for super_admin-created users

### Multi-Tenancy / Super Admin
- [x] `super_admin` role — single fixed account seeded from env vars
- [x] Organisations collection with status (active/suspended)
- [x] Data isolation via org_id + PostgreSQL RLS (session-variable, `with_org()`)
- [x] Super Admin dashboard: org grid, user panel, create org/user modals
- [x] Invite admin flow: branded email via Resend, 72-hour token, AcceptInvite page

### Organisation Structure (Sub-Tenant RBAC)
- [x] Settings (branches) and Teams hierarchy
- [x] Drag-and-drop org structure page
- [x] Scoped managers see only their branch/team staff and meetings
- [x] Schedule write guards — 403 for out-of-scope staff

### Meeting Lifecycle
- [x] New Meeting: single-step form, auto-generated title, browser local time, Meeting type first field, title preview + Create button at top
- [x] Recording: MediaRecorder API, pause/resume, notice logging
- [x] Post-meeting processing: AssemblyAI EU transcription → o4-mini analysis (background async)
- [x] Review workflow: attendee mark-reviewed, manager sign-off
- [x] Re-open flow: two-party consent (request + approve)
- [x] Audio deleted after 5-min grace period post sign-off (GDPR)

### AI Analysis (utils/ai.py)
- [x] **Strengthened evidence framework** — o4-mini now maps described practice, explained reasoning, confirmed observations, and identified learning needs. No longer requires explicit regulation citation.
- [x] Care Certificate: maps to most specific sub-outcome ref; practice narration = strongest evidence
- [x] `reasoning_effort="high"` for analysis and doc evidence
- [x] CQC + Care Certificate + custom/org standards in single pass
- [x] PII scan: full transcript (no truncation), regex + GPT-4o, chunked at 40K chars

### Transcript & Review
- [x] Speaker diarisation (AssemblyAI) + name mapping (GPT-4o)
- [x] Speaker View / Full Text toggle; per-turn reassignment; split turn
- [x] Find & Replace (single + all), Ctrl+H shortcut
- [x] Manual anonymisation (highlight → first initial)
- [x] PII review gate (first open only)
- [x] Inline transcript editing

### Evidence & Compliance
- [x] CQC Inspection Prep page (per-regulation coverage bars, gaps)
- [x] Care Certificate Prep page
- [x] "View in transcript" from evidence cards (fuzzy quote matching)
- [x] Staff Portfolio (evidence by standard, meeting history, PDF export)
- [x] Team Intelligence matrix (CC drill-down modal, date-range filter)
- [x] Evidence export CSV/PDF

### Dynamic Supervision Prep
- [x] Focus Topics (org-level, with active_month locking)
- [x] Focus Topic locked/read-only in Meeting Prep when active month topic exists
- [x] Context sources: previous meetings, uploaded docs, org standards
- [x] AI question generation (GPT-4o, background)
- [x] Prep coverage check post-analysis; carry-forward missed questions as actions
- [x] Prep Agenda tab on Meeting Report (read-only for supervisees)

### Document Import
- [x] Upload previous supervision doc (PDF/DOCX) → async o4-mini evidence scan
- [x] DocUploadReport page; portfolio "Imported Documents" section
- [x] Doc scoped to specific org_id + staff member

### Scheduling
- [x] Recurring schedule templates per staff member
- [x] Supervision Matrix page (colour-coded grid: red/amber/green)
- [x] Due schedule cards on Dashboard with "Start" button
- [x] Custom weeks frequency (weeks_N format)

### Other
- [x] PDF export (signed-off meetings, optional transcript)
- [x] Email report to attendees (Resend)
- [x] Actions rollover (outstanding from previous meetings)
- [x] Org branding (logo + brand colour)
- [x] Custom supervision template (org-wide steps checklist)

---

## Backend File Structure
```
/app/backend/
├── server.py
├── deps.py
├── database.py          — asyncpg pool + with_org() RLS context manager
├── init_db.py           — schema + migrations + seed
├── routers/
│   ├── auth.py          — login, register, MFA, invites, seed_admin
│   ├── meetings.py      — CRUD, attendees, manager assignment
│   ├── recording.py     — notice, start, pause, resume, stop
│   ├── processing.py    — audio upload, background transcription+analysis
│   ├── review.py        — review workflow, sign-off, sharing, comments
│   ├── admin.py         — users, standards, team-insights, export
│   ├── org.py           — org structure, teams, branding
│   ├── schedules.py     — schedule templates
│   ├── prep.py          — dynamic supervision prep, focus topics
│   ├── doc_uploads.py   — supervision document import
│   ├── portfolio.py     — staff portfolio
│   └── super_admin.py   — org management
└── utils/
    ├── ai.py            — OpenAI direct SDK (o4-mini + gpt-4o); AssemblyAI EU
    ├── supabase_storage.py — Supabase Storage wrapper
    ├── job_worker.py    — PostgreSQL async job queue worker
    └── seed.py          — CQC + Care Certificate standards data
```

## Frontend File Structure
```
/app/frontend/src/
├── App.js
├── context/AuthContext.js
├── components/
│   ├── Layout.js
│   ├── admin/           — StandardsTab, DocumentsTab, TemplateTab, UsersTab, ExportTab
│   └── report/          — EvidenceTab, TranscriptTab, CommentsTab, AuditTrailTab, EvidenceSidebar, EmailModal
└── pages/
    ├── Login.js, Dashboard.js, NewMeeting.js, RecordingScreen.js
    ├── MeetingReport.js, MeetingPrep.js, OrgSettings.js
    ├── TeamInsights.js, InspectionPrep.js, CareCertPrep.js
    ├── StaffPortfolio.js, Schedules.js, SuperAdminDashboard.js
    ├── DocUploadReport.js, AcceptInvite.js, SupervisionMatrix.js
```

---

## Key DB Tables (PostgreSQL / Supabase)
- `users` — org_id, role, mfa_enabled, mfa_code, mfa_code_expires_at
- `meetings` — org_id, attendees (JSONB), sign_off_manager_id, rescan_status
- `focus_topics` — org_id, text, is_current, active_month (YYYY-MM)
- `organisations` — name, slug, status, **jurisdiction** ('england'|'wales'|'scotland'|'northern_ireland'), **service_type** ('residential'|'domiciliary'|NULL)
- `invitations` — org_id, token, expires_at
- `meeting_prep` — meeting_id, sections (JSONB), focus_topic, coverage_results
- `standards_entries` — type, reference, name, description, sub_outcomes, is_system, **jurisdiction** ('england'|'wales'|'scotland'|'northern_ireland'), **service_type** ('residential'|'domiciliary'|NULL)
- `standards_documents` — org_id scoped custom/org standards

---

## Environment Variables (backend/.env)
- `MONGO_URL`, `DB_NAME` — legacy keys (PostgreSQL now via asyncpg)
- `JWT_SECRET`
- `CORS_ORIGINS`
- `ADMIN_EMAIL`, `ADMIN_PASSWORD`
- `SUPER_ADMIN_EMAIL`, `SUPER_ADMIN_PASSWORD`
- `OPENAI_API_KEY` — user's own key, direct SDK
- `ASSEMBLYAI_API_KEY` — EU endpoint only
- `RESEND_API_KEY`
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
- `FRONTEND_URL` — https://1two.one

---

## Prioritized Backlog

### P0 (Done this session)
- FFmpeg leading/trailing silence trim added to `_compress_to_mp3` to prevent AssemblyAI hallucinations (Option C: start_periods=1:start_threshold=-50dB with areverse chain; internal gaps preserved)
- PDF export labels made jurisdiction-aware: Wales → CIW / AWIF/SCW, Scotland → Care Inspectorate / SSSC, NI → RQIA (dom/res) / NISCC; `_generate_pdf` now accepts `jurisdiction` + `service_type` params
- RLS hardening: `with_org()` now raises `RuntimeError` (→ HTTP 500) if `SET LOCAL ROLE app_rls_user` fails, instead of silently degrading to superuser
- Fixed: `GRANT app_rls_user TO CURRENT_USER` added to `init_db.py` — required on Supabase where `postgres` is not a true superuser; applied live to staging DB

- Team Intelligence `_jlist()` defensive JSONB parsing — fixes AttributeError when asyncpg prepared-statement cache is reset by `SET LOCAL ROLE` (production fix)
- Upload evidence Accept/Reject/Flag → now feeds Team Intelligence accumulators (UUID/str key mismatch fixed)

### P0 (Done — Aug 2026)
- Fixed "No users found" in meeting attendee picker for managers with `team_id`: `NewMeeting.js` now calls `/admin/users?ignore_scope=true` so all org users are visible when creating a meeting, regardless of manager's team scope

### P0 (Done — Aug 2026, Session 3)
- **Removed Re-transcribe Audio button** from MeetingReport toolbar — was a legacy workaround; AssemblyAI EU endpoint now reliable; backend endpoint dormant as a recovery tool
- **Jurisdiction-aware labels**: `org_jurisdiction` + `org_service_type` added to `/api/auth/me` and `/api/admin/team-insights` responses. EvidenceSidebar and InspectionPrep now show correct framework labels per jurisdiction:
  - England → "CQC Regulations" / "Care Certificate" / "CQC Inspection Prep"
  - Wales → "CIW / AWIF Regulations" / "AWIF / SCW Standards" / "CIW Inspection Prep"
  - Scotland → "Care Inspectorate Standards" / "SSSC Code Standards" / "Care Inspectorate Prep"
  - NI → "RQIA Standards" / "NISCC Standards" / "RQIA Inspection Prep"
- **Super Admin Edit Org**: Confirmed Jurisdiction + Service Type fields already present in modal — P1 complete

### P0 (Done — Aug 2026, Session 4)
- **Full JSONB audit & hardening**: Applied `_jlist()`/`_jdict()` guards to ALL unprotected JSONB column reads across `processing.py`, `review.py`, `prep.py`, and `admin.py`. Specific fixes:
  - `processing.py`: `analyses.actions` (crash fix), `settings.data`, `meeting_prep.sections`
  - `review.py`: `analyses.risks`, `analyses.actions`, `analyses.cqc/care_cert/custom_mappings`, `meetings.attendees` (mark_reviewed, sign_off, approve_reopen, scan_pii, share, PDF exports), `meetings.shared_with`, `settings.data` (rescan background)
  - `prep.py`: `meetings.attendees`, `analyses.actions` (context + generate), `meeting_prep.sections/coverage_results` (carry_forward), get_prep return now parses sections/coverage_results before sending to frontend
  - `admin.py`: Added module-level `_jlist`/`_jdict` helpers; guarded `analyses.actions`, `meetings.attendees`, `meetings.pii_redactions` across all export/PDF endpoints

### P0 (Done — Aug 2026, Session 4 cont.)
- **Full meetings table migration guards**: Added `ALTER TABLE meetings ADD COLUMN IF NOT EXISTS` guards for ALL 22 columns that existed only in `CREATE TABLE` (recording_events, paused_periods, total_paused_duration_seconds, sign_off_record, pii_redactions, shared_with, audio_deletion_status, transcript_has_warnings, diarize_status, reopen_record, rescan_status, etc). Root cause: `CREATE TABLE IF NOT EXISTS` doesn't add new columns to existing tables — columns silently missing in production, causing recording events to fail on write.
- **meeting_prep migration guards**: Added guards for coverage_results, coverage_checked_at, shared_with_attendees.
- **Transcript warning dismiss**: Added `×` button to red warning banner; dismissal stored in localStorage per meeting, persists across page loads.
- **Unified processing progress screen**: Merged 3 separate upload/processing screens into one. All 3 steps visible from start; real upload % on step 1; animated fake-progress bars for steps 2–3; polling every 3s; auto-navigates to report only when processing is fully done.
- **Speaker colors persistent**: meetings.py was missing `_ensure_dict(speaker_colors)` when loading transcript — raw string from asyncpg was being used as initial React state, corrupting Object.entries spread on save.
- **needs_review fires correctly**: Flipped confidence default to `needs_review` as baseline; `likely_evidence` now requires 3 explicit criteria. Applied to both main prompt and rescan/fallback prompt.

### P1 (Next)
- ~~Super Admin "Edit Org" form needs Jurisdiction + Service Type fields~~ — DONE (was already implemented)
- ~~Jurisdiction-aware frontend labels~~ — DONE (Aug 2026, Session 3)

### P0 (Done — Session 5)
- **Achievements PDF export**: Achievements section added to signed-off meeting PDF (`review.py` `_generate_pdf`).
- **Audit Trail split-query fix**: `review.py` meeting fetch split into two separate queries — safe text columns first, JSONB columns second — to bypass asyncpg RLS double-stringification that caused blank Audit Trail.
- **`_normalize_rec_events` flattener**: Robust helper added to flatten `recording_events` JSONB arrays of strings (double/triple encoded by asyncpg + RLS) into proper dicts for Audit Trail rendering.
- **ALTER TABLE guards**: Added `ALTER TABLE meetings ADD COLUMN IF NOT EXISTS` for `created_by_name`, `transcript_id`, `analysis_id` — prevents silent 500 errors on production schema drift.
- **`_parse_analysis_row` in meetings.py**: Added defensive JSONB row parser + `Array.isArray` guards in `EvidenceTab.js` to fix blank-screen React crash when analysis columns return as strings.
- **Branding 500 fix**: Added `_jdict()` helper to `org.py`; applied to all 4 branding endpoint reads (`GET /branding`, `PUT /branding`, `POST /branding/logo`, `GET /branding/logo/{org_id}`). Root cause: asyncpg returning `organisations.branding` JSONB as a string even via `with_admin()`.
- **`standards_entries` JSONB sweep**: Added `_parse_std_row()` helper to `processing.py`, `review.py`, `doc_uploads.py`. Fixed inline parse in `admin.py` team-insights. Guards `sub_outcomes`, `key_questions`, `keywords` JSONB columns which come from `with_org()` RLS and were previously iterated raw — would crash AI analysis and team-insights for any Care Certificate org.

### P1 (Remaining)
- ~~Wales, Scotland, Northern Ireland AI prompt rewrites~~ — DONE (Aug 2026, Session 4): Full intent-first domain guides written for Wales (105 lines), Scotland (85 lines), NI (92 lines), matching England depth.

### P0 (Done — Aug 2026, Session 6)
- **Team Intelligence Register Tabs**: Added 3 new tabs to Team Intelligence page — Learning Needs (teal), Risks (red), Actions (amber). Each tab shows a filterable register with: stat strip (4 colour-accented stat cards), search + staff + status filter bar, and per-item rows with tick/resolve toggles. Actions and Learning Needs show checkboxes to mark complete/addressed; Risks use CheckSquare to mark resolved (matching meeting report UX). New backend endpoints: `GET /admin/team-insights/registers`, `PATCH /admin/team-insights/actions/{meeting_id}/{action_id}`, `PATCH /admin/team-insights/learning_needs/{meeting_id}/{ln_id}`. Optimistic UI updates with revert-on-failure.

### P1.5 (Upcoming)
- **Achievements section — DONE** (Aug 2026, Session 4): AI extracts 1–5 specific achievement moments from meeting transcripts; rendered between Summary and Actions in the Evidence tab with emerald green/star visual styling. DB migration applied.
- **AWIF granularity: DONE** (Aug 2026, Session 9): Replaced 7 AWIF workbook-level entries with 67 granular section-level entries (AWIF 1.1–7.10), each containing specific "You are able to..." practice learning outcomes and "The worker knows..." sub-outcomes extracted from all 7 official Welsh Government workbooks. Standards cache now shows `awif: 67`. Migration-aware: future deployments auto-detect and apply the upgrade.
- **Scotland NIF** — parked indefinitely. Content entirely behind Turas login wall (launched May 2025, no public docs). Add as `type='nif'`, `jurisdiction='scotland'` when source material surfaces.
- Role-specific competency framework upload (admin uploads per-role competency doc; AI maps evidence against it)
- Skills for Care Effective Supervision Guide — per-org upload option

### P0 (Done — Aug 2026, Session 7)
- **NewMeeting.js mobile responsiveness**: Two-panel layout now stacks vertically on mobile (`flex-col md:flex-row`, `w-full md:w-80`, `border-b md:border-b-0 md:border-r`).
- **Backend `people-stats` 500 fix**: SQL query was referencing non-existent `name` column in `settings` table. Fixed to query `org_settings` (which does have a `name` column). `GET /api/admin/people-stats` now returns successfully.

### P1 (Done — Aug 2026, Session 7)
- **People Hub complete**: Unified `/organisation` page with 4 tabs:
  - **People & Usage**: Staff table with stat strip (total/active/inactive/avg), 8-week sparkline activity per person, filters (role/team/status), pending-invite badges, right sidebar with pending invite cards + Resend/Revoke actions, inactive staff warning.
  - **Structure**: Embedded `OrgStructure` drag-and-drop tree (loading state bug fixed for `embedded` prop).
  - **Invites**: Pending invite table with Resend/Revoke wired to `DELETE /api/admin/users/{user_id}` endpoint.
  - **Settings**: Embedded `OrgSettings` with all sub-tabs (loading state bug fixed for `embedded` prop).
- **`DELETE /api/admin/users/{user_id}`**: New endpoint — deletes pending (must_change_password) users entirely; deactivates active users.

### P2 (Future)
- Pending invites dashboard
- Usage dashboard (meeting counts, last activity, storage per org)
- Billing hooks (Stripe — tie orgs to plan/subscription)
- Impersonate org feature for Super Admins
- Meeting duplicate / template feature
- Bulk export of evidence reports
- Role-specific competency framework upload
- Skills for Care Effective Supervision Guide integration
- **Systemic JSONB double-encoding audit** (found Aug 2026, Session 13): audit every `json.dumps(x)` + `$N::jsonb` write call site across `processing.py`/`review.py`/`meetings.py` and remove the redundant `json.dumps()` (asyncpg's registered codec already serializes). Low risk today (reads defensively unwrap it), but root-cause cleanup would let raw SQL (`jsonb_typeof`, `jsonb_array_elements`, etc.) work directly on these columns without defensive CASE WHEN guards.
- **MeetingReport.js size**: still ~1180 lines after the redesign (flagged again by testing_agent, Session 13/14). Header/tabs/action-menu logic added this session; still a good candidate for splitting into smaller components (e.g. `components/report/PageHeader.js`, `ActionsMenu.js`) — not done, low risk today, discuss with user before touching.

### P0 (Done — Aug 2026, Session 8 — patch)
- **`/api/auth/me` branding crash fix**: When the production `organisations.branding` column contains `"null"` or any non-dict JSON value, `json.loads("null")` returned Python `None` which then crashed `b.get("logo_path")` with `AttributeError`. This silently prevented `org_name` and `org_branding` from being set on the frontend, showing "Organisation" fallback. Fixed with `if not isinstance(b, dict): b = {}` guard.
- **`_jdict` helper hardened**: Same `json.loads("null") → None` bug existed in `_jdict` in `admin.py`. Now returns `{}` for any non-dict parsed result.
- **Debug endpoint 500 fix**: `GET /api/admin/users/debug-by-email` no longer crashes when user has null org_id. Root cause was passing empty string `""` to a UUID column. Fixed: now queries by user_id only (no org_id filter). Both debug endpoints improved with structured `issues` array.
- **Meeting visibility for invited users (null org_id)**: `list_meetings` now handles attendees/shared_reviewers with null org_id by using `with_admin()` context (bypassing RLS) and filtering by user_id directly. Previously they saw no meetings at all.
- **accept_invite sets org_id**: `POST /api/auth/accept-invite` now writes `org_id` from the invitation record into the user row, ensuring future invited users always have org_id set.
- **New repair endpoint**: `POST /api/admin/users/fix-org-by-email?email=<email>` + body `{org_id}` lets admins/super_admins fix existing users with null org_id (e.g., Connor in production).
- **BrandingTab re-fetches on mount**: `BrandingTab.js` now calls `GET /api/org/branding` on mount so saved brand color is always shown — even immediately after a fresh login (not just after a hard browser refresh).
- **AuthContext fetches full profile after login**: `login()` and `completeLogin()` in `AuthContext.js` now call `GET /api/auth/me` after setting the initial user state, ensuring `org_branding`, `org_name`, `org_jurisdiction` are populated in the context from the first page load after login.


### P0 (Done — Aug 2026, Session 9 — Security P3b/P3c)
- **P3b HttpOnly Cookies**: JWT tokens moved from `localStorage` to HttpOnly+Secure+SameSite=Lax cookies (`supervision_access` 30min, `supervision_refresh` 7d). All auth endpoints updated (`login`, `verify-mfa`, `accept-invite`, `refresh`, `logout`). `deps.py` reads cookie first, falls back to Bearer header for backward compat. Frontend `AuthContext.js` sets `axios.defaults.withCredentials = true` globally; all stale `localStorage.getItem("supervision_token")` calls removed from 9 files; `fetch()` calls updated with `credentials: 'include'`. Eliminates XSS token theft risk.
- **P3c Sign-off Gate**: `POST /api/review/{meeting_id}/signoff` now strictly requires `status == "reviewed"` (all attendees reviewed). Attempting sign-off when `status == "in_review"` returns HTTP 400 with a list of pending reviewers. No admin override — if outstanding, the record shows as incomplete. Frontend MeetingReport.js disables the Sign Off button with a tooltip when `isInReview`. Sign-off confirmation modal shows blocking red warning with attendee names.
- **Security test suite updated**: `test_security_jwt_idor.py` `login()` helper updated to read token from `supervision_access` cookie. 2 new `TestSignOffGate` tests added. All 26 tests pass.


### RLS Completion (Aug 2026, Session 10)
- **4 tables hardened with RLS**: `organisations`, `invitations`, `settings`, `evidence_feedback` — all now have `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` + `CREATE POLICY ... USING (col = (SELECT current_setting('app.current_org_id', TRUE)))`. Resolves remaining Supabase security advisor warnings. `with_admin()` still bypasses RLS via `SET LOCAL row_security = off` for all admin/super-admin operations.
- **2 redundant indexes dropped**: `idx_meetings_org_id` and `idx_meetings_status` — both covered by the composite `idx_meetings_org_status_date`. Unused-index advisor warnings cleared.
- **`evidence_feedback` added to explicit GRANT** for `app_rls_user`.

### P0 Meeting Load Fix Verified (Aug 2026, Session 11)
- **`operator does not exist: text = uuid` fix confirmed**: `meetings.py` line 314 `$1::uuid[]` cast changed to `$1::text[]` (users.id is TEXT not UUID type). End-to-end verified: `POST /api/meetings/` then `GET /api/meetings/{id}` returns 200 with correct data. Manager account password (Manager123!) confirmed and MFA bypass approach documented in test_credentials.md.

### Form Accessibility + Tooltips (Aug 2026, Session 12)
- **Form field audit complete**: Added `id`, `name`, `htmlFor`, and `autoComplete` attributes across 8 files (Login, AcceptInvite, ResetPassword, SetPassword, ChangePasswordModal, NewMeeting, UsersTab, SuperAdminDashboard). All labels now semantically linked to their inputs — fixes DevTools Issues warnings and enables password manager autofill.
- **Tooltip system added**: `TooltipProvider` added to App.js root. Info-icon (`HelpCircle`) tooltips added to: Meeting Type (AI analysis description per type), Sign-off Manager (explains attendee requirement), Password fields on ResetPassword & AcceptInvite (5-point requirements checklist), Role selector on UsersTab & SuperAdminDashboard (per-role permission descriptions).

### Preview: Production Build (Aug 2026, Session 12)
- **Root cause of 90-second blink permanently fixed**: Switched Preview environment from `vite dev` (HMR WebSocket, K8s ingress kills at 90 s → `location.reload()`) to `vite build && vite preview` (static file server, zero WebSocket, zero HMR). `package.json` `start` script updated; `vite.config.mjs` `preview` block added (`host`, `port`, `strictPort`, `allowedHosts: true`). Build completes in ~4.5 s on supervisor restart. Preview now mirrors production (`1two.one`) exactly. Option A (suppress reload shim) was rejected in favour of this permanent, clean fix.

### HMR WebSocket Keepalive Fix (Aug 2026, Session 11)
- **Root cause of "52 requests per blink"**: Vite's HMR WebSocket uses `server.hmr.timeout` as its **ping interval** (default 30 s). The K8s ingress times out idle WebSockets at ≤30 s. When the WS drops, Vite's client (`client.mjs:962`) calls `waitForSuccessfulPing()` (which succeeds immediately since the server is still up), then unconditionally calls `location.reload()`. This is why a full page reload (52 requests) happened on a fixed cadence. Fix: set `server.hmr.timeout: 5000` in `vite.config.mjs`. Confirmed: `const hmrTimeout = 5000` injected into served `@vite/client`. 3-minute monitoring: zero new log lines, zero errors, PID stable.

### Dep Pre-bundling Fix (Aug 2026, Session 11)
- **Root cause of RecordingScreen reload**: Vite 6's initial rolldown dep scan fails silently (rolldown can't parse JSX in `.js` files). Only 14/53 deps were pre-bundled. As the user navigated to new pages (lazy-loaded components importing `@radix-ui/*`, `recharts`, `react-hook-form`, etc.), Vite discovered unbundled deps at runtime and triggered "Re-optimizing dependencies" → full page reload. This was the hardest-to-diagnose blink: it only happened when loading a specific page for the first time. Fixed by adding all 53 deps to `optimizeDeps.include` in `vite.config.mjs` (Vite uses esbuild — not rolldown — for explicit includes, so JSX parsing works). Also installed missing `date-fns@^3` peer dep for `react-day-picker`. Verified: 3-minute monitoring, all 53 deps in `.vite/deps`, zero re-optimization events.

### Auth Interceptor + Proactive Refresh Fix (Aug 2026, Session 11)
- **Root cause of `/auth/me` 401 blink**: Interceptor condition was `!url.includes("/auth/")` — this excluded `/auth/me` from the refresh retry path. When the 30-min access token cookie expired, `/auth/me` got 401, interceptor skipped it, `setUser(null)` fired → ProtectedRoute redirected to `/login` → visible blink. Fixed by switching to an explicit NO_RETRY_PATHS list: `[/auth/refresh, /auth/login, /auth/register, /auth/verify-mfa, /auth/logout, /auth/forgot-password, /auth/reset-password]`. Now `/auth/me` is retried on 401 (refreshes token → replays request → user stays logged in).
- **Proactive 20-min refresh timer**: Added `setInterval(silentRefresh, 20min)` in AuthContext so the 30-min cookie never expires mid-session during long recordings with no API activity (previously only refreshed reactively on 401).

### React StrictMode Removed (Aug 2026, Session 11)
- **Double-mount blink + 2× DB requests**: React 18 Strict Mode mounts → unmounts → remounts every component in dev. This caused: (1) visible "blink" on RecordingScreen with page state reset, (2) every `useEffect` ran twice → 2× API requests → 2× DB queries, (3) MediaRecorder cleanup effect would stop recording on the forced unmount. Fixed by removing `<React.StrictMode>` wrapper from `index.js`. Zero effect on production builds. Verified: Vite picked up change (`page reload src/index.js`).

### CSP + Vite Config ESM Fix (Aug 2026, Session 11)
- **Root cause of site reload**: Two layered issues. (1) `vite.config.js` loaded as CJS forcing `@vitejs/plugin-react`'s CJS build → `@rolldown/pluginutils` missing → Vite internal "server restart failed" every ~2 min → HMR disconnect → browser reload. Fixed by renaming to `vite.config.mjs` (ESM). (2) Remaining reload caused by CSP in `index.html` blocking Vite 6's inline HMR bootstrap script and Cloudflare CDN injected scripts — HMR WebSocket never connected, causing continuous reconnect/reload loop. Fixed by switching `script-src` to `'unsafe-inline'` (safe since JWT tokens now in HttpOnly cookies, no localStorage exposure). Both fixes verified: 2+ minute monitoring, zero new errors, zero new reloads, PID stable.

### Vite 6 Upgrade (Aug 2026, Session 10)
- **Upgraded Vite 5.4.21 → 6.4.3**: Resolves all 3 GitHub Dependabot CVE alerts (server.fs.deny bypass, path traversal in .map, launch-editor NTLMv2). Cleared the 90-second blink/reload cycle caused by Vite 5.4.x's experimental "native" config loader failing when rolldown was partially installed in node_modules. Vite 6's rolldown integration is first-class — no more `@rolldown/pluginutils` crash.
- `@vitejs/plugin-react@4.3.4` already declared Vite 6 support (`^6.0.0`) — no plugin or config changes needed.
- Vite 7/8 migration remains P2 (blocked by Rolldown JSX compiler issue for the main bundler).

