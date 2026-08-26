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

## Recently Completed (Aug 2026)
- **Team Themes UI unification (P0, this session)**: Learning Needs, Attention (risks) and Actions
  tabs in `/app/frontend/src/pages/TeamInsights.js` now reuse the exact same person-grouped
  collapsible timeline layout as Achievements, via a new shared `PersonGroups` component driven by
  a `TYPE_CFG` map (icon/accent/noun/doneField per type). `AchievementsTimeline` itself now delegates
  to `PersonGroups` (type="achievements", no onToggle) so it stays visually/functionally identical.
  The old flat `renderItem` list was removed. Top stat-strip/search/staff-filter/status-filter/Export
  CSV bar is unchanged for Learning Needs/Attention/Actions.
  - Fixed during testing: cross-person inline-expansion sync (expandKey now scoped by person slug),
    data-testid collisions (toggle/item/view-meeting testids now include meetingId+itemId+personSlug),
    risk "Resolved by" not showing until reload (optimistic update now sets resolved_by), Overdue badge
    mis-firing on free-text due dates (now guarded by ISO-date regex). Added `invalidateCache` call
    after successful register toggle PATCH.
  - Tested via testing_agent — 2 rounds, all issues fixed, final pass 100% (iteration_94, iteration_95).
- Component splitting refactor of MeetingReport.js/TranscriptTab.js, speaker colour defaults, evidence
  tracking/audit bug fixes, bulk-accept tracking, EvidenceSidebar→ComplianceTab rename, Team Themes
  caching bug fix, security audit fixes (privilege escalation, export data-scope leaks).

## Recently Completed (Aug 2026, cont.)
- **Zip-bomb decompression guard (security hardening)**: Confirmed Standards Upload
  (`admin.py POST /admin/standards/upload`) and Import Supervision (`doc_uploads.py POST
  /doc-uploads/`) already shared the same `validate_upload()` magic-byte check. Added
  `guard_zip_bomb()` to `/app/backend/utils/file_security.py` — inspects the ZIP central
  directory (entry count, per-entry compression ratio, total uncompressed size) for
  docx/xlsx/pptx uploads before `python-docx` ever decompresses content. Wired into both
  endpoints right after `validate_upload()`. Verified end-to-end via curl: a crafted
  zip-bomb docx (50MB decompressed from a 50KB file) is rejected with 400 on both
  endpoints; a normal docx still uploads successfully (200) on both.

## Recently Completed (Aug 2026, cont. 2)
- **Security audit fixes (P2 + hardening)**: Ran full security_audit_agent review — verdict
  CONDITIONAL PASS, no critical/high issues, all prior fixes (SEC-001 IDOR, role
  self-escalation, export-scope leaks, zip-bomb guard) confirmed intact. Fixed the 3 items
  the user asked for:
  1. **[P2] Access token not revoked on password reset/logout** — `create_access_token`
     now embeds `pwd_ts` (password_changed_at timestamp), and `deps.py get_current_user`
     rejects any access token whose `pwd_ts` is missing or stale vs the DB value (mirrors
     the existing refresh-token protection). Verified end-to-end: old access token gets
     401 immediately after a password change; frontend's axios interceptor silently
     refreshes via the (also-rejected, forcing full re-login) refresh token — no code
     changes needed there. Updated `tests/test_security_jwt_idor.py` (forge_token default
     pwd_ts=0, role-escalation test reuses real pwd_ts) — full suite (26 tests) passes.
  2. **CORS**: dropped `http://localhost:3000` from `backend/.env` CORS_ORIGINS allowlist
     (now just preview + `https://1two.one`). Verified via direct OPTIONS request that
     localhost origin gets no `access-control-allow-origin` header.
  3. **Email HTML escaping**: `html.escape()` applied to user-controlled `name`/`org_name`
     before interpolation into MFA-code email (`auth.py`) and org-admin invite email
     (`super_admin.py::_build_invite_email`) — defense-in-depth against stored-content
     rendering, even though these are same-recipient-only emails.
  - Deferred (not requested this round): P3 items — MFA OTP per-IP throttle, audit-trail
    silent-exception swallowing (`review.py get_audit_trail`).
- **Known pre-existing test-data issue (unrelated to above)**: `tests/test_idor_sec001.py`
  has a hardcoded `TARGET_MEETING` UUID that no longer exists in the DB, causing 8
  failures + 2 precondition errors unrelated to any code change. `tests/test_security_fixes.py`
  has a `BASE_URL` scheme bug causing `MissingSchema` errors. Neither touched — flagging
  for whoever next needs that suite green.

## Recently Completed (Aug 2026, cont. 3)
- **Optimistic bulk-accept on Evidence page**: `bulkAcceptEvidence` in
  `useMeetingReport.js` now flips matching pending items to accepted + shows a success
  toast instantly on click, fires the API call in the background, reconciles with the
  server response on success, and reverts + shows an error toast on failure. No-pending
  case short-circuits with an info toast and no network call. Renamed `bulkAccepting`
  (bool) → `bulkAcceptingTier` (string|null) so the spinner/disabled state on
  "Accept all likely"/"Accept all possible" only affects the tier actually submitting,
  not both buttons. Tested via testing_agent — 100% (7/7 scenarios: happy path, no-pending
  short-circuit, forced-500 revert, server-truth reconciliation after reload, individual
  accept/reject regression, Team Themes cache-bust). No open issues.

## Known minor/optional items (not blocking)
- AchievementsTimeline's own search input / staff filter / 4 stat cards have no data-testid (unlike
  the register tabs) — cosmetic testability gap only.
- expandKey still includes array index `idx`; could drop since (personSlug, meeting_id, item.id) is
  already unique — no functional bug, just a code-review nit.
- `/app/frontend/src/pages/TeamInsights.js` is ~1500 lines — recommend splitting PersonGroups/
  RegisterView/AchievementsTimeline into separate files (P2, code-quality only).

## Backlog

### P1
- Session Expiry Notice: friendly "Your session expired" message instead of silent redirect.
- Toast Position Fix: move toasts above header menu so text isn't clipped.
- Meeting Templates: duplicate a past meeting's setup as a starting template.

### P2
- Full Code Review Pass (missing hook deps, index-as-key).
- CSV Export Polish: note about safety-escaped text in evidence export.
- Mobile Evidence Pass: mobile-spacing for Compliance Evidence card badges/links.
- Crash Reporting: lightweight client-side error logging.
- Split TeamInsights.js into smaller modules.

### P3
- Audit Trail Digest (filter/collapse routine recording events).
- Bulk Spelling Fix in Find & Replace (US→UK).
- Mobile Speaker Menu (full-width sheet instead of popover).
- Spark — Portfolio Progress Bar (progress ring per staff member).
- Super Admin Portfolio Access decision.
- "Undo Bulk Accept" toast action.
- Provider Comparison Log (which AI model generated each report).
- Vite 7/8 migration.
- Impersonate org feature for Super Admins.
- Prep Time Stamps (exact time when two context sources share a date).

## Environments
Preview only in this session. Production is 1two.one (separate, do not guess URLs — always use
REACT_APP_BACKEND_URL from frontend/.env).
