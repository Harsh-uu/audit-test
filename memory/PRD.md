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
