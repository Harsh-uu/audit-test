# Supervision 2.0 - PRD & Project Memory

## Product Overview
Supervision 2.0 is a web-based compliance evidence platform for UK adult social care providers. Users record supervision meetings, and the system automatically generates transcripts, summaries, CQC compliance mappings, and Care Certificate competency evidence.

**Deployment URL Identifier:** supervison2
**Product Name:** Supervision

---

## Architecture
- **Frontend:** React (JavaScript), Tailwind CSS, Shadcn UI, Lucide React icons
- **Backend:** FastAPI (Python), MongoDB, Motor (async MongoDB driver)
- **AI:** OpenAI GPT-4o (via emergentintegrations) for analysis + speaker name mapping; **Deepgram Nova-3** for transcription + speaker diarisation (audio-based); OpenAI Whisper-1 as fallback if Deepgram unavailable
- **Email:** Resend ✅ (configured with live API key)
- **Storage:** Emergent Object Storage (for audio files and standards documents)
- **Auth:** JWT (Bearer token in localStorage + httpOnly cookies)
- **Audio Upload:** Raw `application/octet-stream` (bypasses Cloudflare WAF multipart block)

---

## User Roles
| Role | Description |
|------|-------------|
| admin | Full access, manage users and standards library |
| manager | Create meetings, sign-off, view all meetings, upload org-specific standards documents |
| attendee | Record meetings, review assigned meetings |
| shared_reviewer | View signed-off meetings, add comments |

---

## Core Features Implemented (v1)

### Foundation (Phase 1)
- [x] JWT authentication with role-based access control
- [x] User registration, login, logout
- [x] Admin auto-seeded on startup
- [x] Test users seeded (manager, staff)
- [x] MongoDB with indexed collections
- [x] Object storage initialization

### Standards Library (Phase 2)
- [x] CQC regulations pre-seeded (14 regulations: Reg 9-20, Reg 20A, CQC Reg 12)
- [x] Care Certificate standards pre-seeded (16 standards, 2025 version)
- [x] Admin can add/deactivate individual standards
- [x] Admin can upload reference documents
- [x] Manager can upload org-specific standards documents (Custom Standards tab) — Skills for Care Supervision Guide uploaded per-org

### Find & Replace in Transcript (Phase 5d)
- [x] "Find & Replace" button in Transcript tab toolbar (Ctrl+H shortcut also works)
- [x] Two-row bar: Search input with match counter (e.g. "2 / 7") + Prev/Next navigation; Replace input with Replace (current) and Replace All buttons
- [x] All matches highlighted in yellow; current (active) match highlighted in amber
- [x] Auto-scrolls to current match on Prev/Next
- [x] Speaker View: Replace modifies `localTurns` client-side → dirty flag → uses existing Save flow to persist
- [x] Full Text: Replace All calls `POST /api/review/{id}/find-replace`, saves to DB, refreshes transcript
- [x] Full Text: Replace (single) passes `replace_one: true` — backend replaces only the first occurrence (count=1) instead of all
- [x] Audit trail entry `transcript_text_edited` with detail "Find & Replace: 'X' → 'Y' (N occurrences)"
- [x] Escape closes bar; Enter navigates to next match

### PII / Confidentiality Review Gate (Phase 5c)
- [x] Appears on FIRST open only for managers/admins (once cleared, never shows again)
- [x] AI (GPT-4o) scans for third-party names + sensitive context; regex scans for UK phone, email, postcode, NHS/NI numbers
- [x] Meeting participants' names excluded from AI scan so they're never incorrectly flagged
- [x] Manager can accept/modify/deselect each flag before applying
- [x] `POST /api/review/{id}/scan-pii` — returns AI + regex flags
- [x] `POST /api/review/{id}/complete-pii-review` — saves redactions, sets `pii_review_status = "reviewed"`
- [x] Original transcript preserved in DB; redacted view applied on-the-fly for non-privileged viewers
- [x] Privileged access = meeting creator + listed attendees (see original); everyone else sees redacted
- [x] Skip path records "acknowledged" in audit trail with date/time
- [x] Audit trail shows "Confidentiality review completed" / "skipped (acknowledged)" events

### Super Admin User Management (Phase 5b)
- [x] Delete User with full cascade (schedules + refresh tokens cleaned up) — backend `DELETE /api/super-admin/orgs/{org_id}/users/{user_id}`
- [x] Confirmation modal before deletion (shows user name, warns about cascade)
- [x] `toast.success` / `toast.error` feedback via sonner after delete completes
- [x] Org user count auto-refreshes after deletion

### Document Import (Phase 2b)
- [x] Managers/admins can upload a previous supervision document (PDF or DOCX) via `/upload-supervision`
- [x] Document linked to a specific staff member with supervision date + label
- [x] AI (o4-mini) scans extracted text and maps to CQC + Care Certificate + custom standards (evidence mapping only, no summary/actions)
- [x] Background async processing with 3-second frontend polling
- [x] `DocUploadReport` page shows evidence sidebar for imported doc
- [x] Staff portfolio shows "Imported Documents" section with Document Import badge, always visible regardless of signed-off meeting count
- [x] "Import Supervision" sidebar link for admin/manager roles
- [x] Max 20MB, PDF + DOCX supported, stored in `supervision_uploads` collection

### Recording (Phase 3)
- [x] Recording notice display and logging
- [x] Browser MediaRecorder API integration
- [x] Start/Pause/Resume/Stop controls
- [x] Pause/Resume timestamp logging
- [x] Paused period duration calculation
- [x] Audio upload to object storage
- [x] Recording events timeline

### Processing (Phase 4)
- [x] Post-meeting audio transcription (Whisper-1)
- [x] AI meeting summary (GPT-4o)
- [x] Action item extraction
- [x] Risk/concern extraction
- [x] CQC regulation mapping with evidence excerpts + confidence labels
- [x] Care Certificate standard mapping
- [x] Background processing with status tracking
- [x] Processing states: processing → transcribing → analyzing → in_review

### Review & Sign-off (Phase 5)
- [x] In-app review workflow for attendees
- [x] Edit summary, actions, evidence wording
- [x] Accept/Reject/Flag evidence items
- [x] Mark-reviewed per attendee
- [x] All-attendees-reviewed check before sign-off
- [x] Manager-only sign-off
- [x] Shared reviewer commenting post-sign-off
- [x] Read-only transcript with paragraph formatting
- [x] Manual transcript anonymisation (manager/admin highlights name → first initial, persisted to DB, audit logged)

### Audio Deletion (Phase 6)
- [x] 5-minute grace period after sign-off
- [x] Automatic audio deletion background task
- [x] Audio lifecycle status: none → grace_period → deleted
- [x] GDPR-compliant audio management

### Admin
- [x] User management (create, list, update)
- [x] Standards library management
- [x] Document upload

---

## Backend File Structure
```
/app/backend/
├── server.py          - FastAPI app, startup, CORS, router registration
├── deps.py            - get_db(), get_current_user(), require_roles()
├── routers/
│   ├── auth.py        - Login, register, logout, me, refresh, seed_admin
│   ├── meetings.py    - CRUD, attendees, manager assignment
│   ├── recording.py   - Notice, start, pause, resume, stop events
│   ├── processing.py  - Audio upload, background transcription+analysis
│   ├── review.py      - Review workflow, sign-off, sharing, comments
│   └── admin.py       - Users, standards, documents, stats
└── utils/
    ├── storage.py     - Emergent object storage wrapper
    ├── ai.py          - Whisper transcription + GPT-4o analysis
    └── seed.py        - CQC + Care Certificate standards data
```

## Frontend File Structure
```
/app/frontend/src/
├── App.js                    - Routes with ProtectedRoute
├── context/AuthContext.js    - JWT auth, user state
├── components/
│   ├── Layout.js             - Sidebar navigation
│   └── ProtectedRoute.js     - Auth guard with role checking
└── pages/
    ├── Login.js              - Login/register
    ├── Dashboard.js          - Meeting list with stats
    ├── NewMeeting.js         - 2-step meeting creation
    ├── RecordingScreen.js    - Recording controls with notice
    ├── MeetingReport.js      - Split-view report (transcript + evidence)
    └── AdminLibrary.js       - Standards and user management
```

---

## DB Collections
- `users` - User accounts
- `meetings` - Meeting records (includes attendees, events, sign-off)
- `audio_files` - Audio file metadata and deletion status
- `transcripts` - Transcription results
- `analyses` - AI analysis (summary, actions, risks, CQC/CC mappings)
- `review_edits` - Audit log of edits
- `reviewer_comments` - Post-sign-off comments
- `standards_entries` - CQC and Care Certificate reference data
- `standards_documents` - Uploaded reference documents
- `login_attempts` - Brute force protection

---

## Environment Variables (backend/.env)
- MONGO_URL, DB_NAME - MongoDB connection
- JWT_SECRET - JWT signing key
- CORS_ORIGINS - Allowed origins
- ADMIN_EMAIL, ADMIN_PASSWORD - Initial admin credentials
- EMERGENT_LLM_KEY - Universal key for OpenAI (GPT-4o + Whisper)
- RESEND_API_KEY - Email sending (needs real key from user)
- SENDER_EMAIL - From email address
- FRONTEND_URL - For CORS and email links

---

## What's Working (Tested v1 + v2 + v3)
- All auth flows (3 roles tested)
- Meeting creation (2-step with attendees + manager)
- Recording notice, start, pause, resume, stop
- Meeting listing and status tracking
- Admin: standards library (30 entries), user management
- Meeting report: evidence cards, summary editing, sign-off
- Audio deletion grace period (5 min)
- Comments tab: add/view comments (admin/manager always, others post-sign-off)
- Audit Trail tab: chronological log of all events (recording, transcription, edits, sign-off, comments)
- Transcript anonymization: names replaced with initials in transcript text only; full names shown throughout all UI elements
- Care Certificate outcome references: all 16 standards seeded with specific outcome refs (1.1, 2.1, etc.), AI includes outcome_ref in evidence mappings, EvidenceCard displays "Outcome X.X: name" badge
- CQC Five Key Questions: all 14 regulations tagged with key questions (Safe/Effective/Caring/Responsive/Well-led), coloured badges shown on CQC evidence cards, existing analyses back-filled on startup
- Admin Library Custom Standards: upload PDF/DOCX/TXT documents, AI extracts criteria (~15s), active docs included in all future meeting analyses as 'Organisational Standards' evidence section; auto-rescan runs against existing meetings after each new document is parsed
- PDF Export: signed-off meetings only, toggle to include/exclude transcript, generates professional reportlab PDF with all sections
- Resend Email: manager sends report link to attendees after sign-off via noreply@1two.one, optional personal message
- Actions rollover: outstanding incomplete actions from previous meetings for same attendees prepended to new meeting's action list (amber styling, 'Carried over from' label); checkbox UI to mark complete/incomplete
- Supervision Template: admin configures org-wide supervision steps in Admin Panel; shown as collapsible checklist in RecordingScreen; AI uses steps as context in summary and evidence mapping

---

## Prioritized Backlog

### P0 (Critical)
- None — all resolved

### P1 (Important)
- None outstanding — all resolved

### P2 (Future/Backlog)
- CQC inspection preparation summary view
- Date-range filter on Team Intelligence matrix

### P2 (Future)
- Internal evidence framework (job descriptions, company values, targets)
- Role-specific competency framework upload
- Meeting duplicate / template feature
- Bulk export of evidence reports
- CQC inspection preparation summary view

---

## Next Steps
1. Test with real audio files to validate full processing pipeline
2. Configure Resend API key: user needs key from https://resend.com
3. Consider adding PDF export via reportlab or weasyprint
4. Future: Internal evidence framework (staff job descriptions, company targets)

---

- Team Intelligence page (`/admin/team`) — Evidence Matrix (staff × standards heatmap with coverage % row) + Team Themes (coverage gaps as progress bars, recurring risks, outstanding actions). Accessible to admin + manager roles.
- Staff Portfolio page (`/portfolio/:userId`) — evidence grouped by CQC / Care Cert / Organisational standards + chronological meeting history + PDF export
- Evidence Export in Admin Library — CSV/PDF bulk export with staff filter, date range, and specific meeting picker
- Custom evidence (Organisational Standards): accept/reject/flag/edit buttons now work correctly — `custom_mappings` added to backend update loop (review.py)
- Whisper transcription upgraded with care/clinical domain terminology prompt (CQC, safeguarding, MCA, DoLS, etc.) for improved accuracy

- Code quality review applied: `useMemo` for AuthContext value, error logging on all silent catch blocks, `eslint-disable` comments for intentional `[]` deps, stable keys in lists, role-array constants in App.js

- Regression test (iteration 14) after code quality fixes: 9/9 frontend scenarios PASS, zero JS runtime errors

- Granular Care Certificate sub-outcomes (2025): all 16 standards now have flat `sub_outcomes` list (216 total, e.g. 2.1a, 2.1b, 2.2h). Standard 16 correctly has 1 sub-outcome (training compliance per CQC Reg 18, matching official March 2025 PDF). AI maps evidence to specific sub-outcome refs. Team Intelligence matrix only shows green when ALL sub-outcomes evidenced; partial shows covered/total fraction in amber. Standard names updated to 2025 edition. DB migrated on startup.

- Dashboard search & filtering: search by title + attendee name, quick status chips with live counts (All/Draft/In Review/Reviewed/Signed Off), date range picker (from/to), sort newest/oldest, result count + clear-all button. All client-side via useMemo.

- Backend `flake8` linting — zero errors achieved (2026-Feb). Fixes: duplicate imports removed (`processing.py` F811), unused imports/variables removed (`review.py` F401/F841 — TA_LEFT, TA_CENTER, styles, h2_style, h3_style, label_style), E402 `# noqa` for `load_dotenv`-before-imports pattern in `server.py`, blank-line E302/E303 formatting, E221 alignment spacing in `admin.py`/`portfolio.py`, E701 multi-statement lines in `admin.py`, F541 bare f-strings in test files, W291/W293/W391 whitespace issues, very-long lines broken or annotated with `# noqa: E501`. Created `.flake8` config with `max-line-length=120` and `per-file-ignores` for data/test files (seed.py, ai.py, review.py, portfolio.py, tests/*).

- Refactored `AdminLibrary.js` (825 → 371 lines) and `MeetingReport.js` (1015 → 382 lines) to reduce cyclomatic complexity (2026-Feb). Extracted 5 admin tab components under `src/components/admin/` (StandardsTab, DocumentsTab, TemplateTab, UsersTab, ExportTab) and 6 report sub-components under `src/components/report/` (EvidenceTab, TranscriptTab, CommentsTab, AuditTrailTab, EvidenceSidebar, EmailModal). 14/14 frontend regression tests passed.

- Manual transcript anonymisation (2026-Feb): managers/admins highlight any name in the transcript, a floating navy pill button "Anonymise" appears — clicking it calls `PATCH /api/review/{meeting_id}/anonymise` which replaces all occurrences of the phrase with first initial (e.g. "Robert Smith" → "R."), persists to `db.transcripts`, and logs to `review_edits` audit trail. Frontend: `formatTranscript()` splits blob transcripts into readable paragraphs (3 sentences each). 10/10 tests passed (iteration_17).

- Care Certificate sub-outcome drill-down (2026-Feb): Three-part feature — (A) EvidenceSidebar: `CareCertDrillDown` groups CC evidence by standard with per-sub-outcome covered/gap expansion. (B) Team Intelligence Matrix: all 16 CC cells are clickable, opening `CcDrillDownModal` with staff × standard view, progress bar, evidenced sub-outcomes (green check) and gaps (dimmed). (C) Staff Portfolio: Care Cert tab replaced with `CareCertGroupedView`, grouped by standard with sub-outcome expansion and gap toggle. Also fixed a duplicate-declaration build error in `EvidenceSidebar.js`. "Observation" added to New Meeting type dropdown.

- Speaker Identification (2026-Feb): `POST /api/processing/{id}/diarize` endpoint calls GPT-4o to label each speaker turn as Manager:/Worker: (or actual names). For new meetings, diarization runs in parallel with analysis (`asyncio.gather`). For existing meetings, an "Identify Speakers" button in the Transcript tab calls the endpoint on-demand. The transcript tab now has a Full Text / Speaker View toggle; navy pills = Manager, emerald pills = Worker. PDF export now renders speaker-labeled turns as two-column tables (colored label pill | turn text) when `speaker_text` is available, falling back to plain text otherwise.

- Speaker Name Correction (2026-Feb v2): Replaced per-turn pencil editing with a global `SpeakerManagerPanel` above the transcript. Shows all unique detected speakers with turn counts and rename input fields. Renaming any field immediately relabels ALL turns with that speaker. "Swap all" button swaps the two main speakers in one click (only shown when exactly 2 unique speakers). Save/Discard appear only when changes are pending. Save calls `PATCH /api/review/{id}/speaker-text`.

- Typography (2026-Feb): Added Work Sans to Google Fonts (weights 400-700). Registered `font-sans` (Poppins) and `font-display` (Work Sans) in Tailwind config. Removed all 17 `style={{ fontFamily: ... }}` inline overrides and replaced with `font-display` Tailwind class. Stripped redundant Poppins inline styles from Login, ResetPassword, and Layout (they inherit from `body`).

## Multi-Tenancy / Super Admin (2026-Jun)
- New `super_admin` role — single fixed account (`superadmin@1two.one`) seeded from SUPER_ADMIN_EMAIL/SUPER_ADMIN_PASSWORD env vars.
- New `organisations` MongoDB collection — each org: name, slug, status (active/suspended), created_at.
- Data isolation: `org_id` field added to `users`, `meetings`, `org_settings`, `teams`. All queries scoped by org.
- Startup migration: existing data auto-assigned to "Test Company" org via `seed_default_org()`.
- New router `routers/super_admin.py`: GET/POST `/api/super-admin/orgs`, PATCH `/api/super-admin/orgs/{id}`, GET/POST `/api/super-admin/orgs/{id}/users`.
- Existing routers (meetings.py, admin.py, org.py) updated to filter by current_user.org_id.
- New page `/super-admin` (SuperAdminDashboard.js): org grid with stats, slide-over user panel, create org/user modals.
- Layout.js: super_admin gets a distinct dark navy sidebar with only "Organisations" nav. Login.js: redirects super_admin to /super-admin post-login.

## Invite Admin Flow (2026-Jun)
- Super admin can invite a new org admin via email: `POST /api/super-admin/orgs/{id}/invite` creates an inactive user + 72-hour single-use token stored in `invitations` collection.
- Branded HTML invite email sent via Resend with an "Accept Invitation →" button linking to `/accept-invite?token=xxx`.
- If email fails, the invite link is returned in the API response so super admin can share it manually (with copy button in UI).
- New public page `AcceptInvite.js` at `/accept-invite`: validates token (GET /api/auth/invite/{token}), shows org name + email, collects name + password, POST /api/auth/accept-invite activates user + returns JWT (auto-login).
- SuperAdminDashboard org management panel: "Invite Admin" (email flow) + "Add User" (direct password) buttons side by side.

- Mobile date input overflow (NewMeeting.js + Dashboard.js): added `min-w-0 max-w-full` + `overflow-hidden` wrapper on `datetime-local` input; dashboard date filter made `flex-wrap`.
- Speaker per-turn reassignment: clickable speaker pills open inline dropdown to reassign any turn; "Flip speakers from here" swaps all turns from that index to end (fixes cascade mis-sync).
- Speaker turn splitting: select any text within a turn in Speaker View → "Split turn here ✂" popup extracts it as a new standalone turn; user can then reassign each part. Uses browser `range.startOffset`/`endOffset` for character-accurate splitting.
- Full speaker state refactored to `localTurns` mutable array — single source of truth replacing `speakerMap + turnOverrides` layered state.

## Changelog (Recent)
- **2026-Jul** — Manager access to Admin Library (Standards Library + Document Import tabs; Users/Branding hidden)
- **2026-Jul** — Import Supervision Document: PDF/DOCX upload linked to staff, async o4-mini evidence scan, `DocUploadReport` page, portfolio "Imported Documents" section
- **2026-Jul** — Custom weeks frequency for schedules (`weeks_N` format, e.g. six-weekly)
- **2026-Jul** — Supervision Matrix page: colour-coded grid (red/amber/green) of all staff schedules, auto-fill responsive grid, filter bar, sidebar link
- **2026-Jul** — CQC Inspection Prep page: per-regulation coverage bars, expandable gap details (which staff have no evidence), stats chips, section tabs (CQC / Care Cert), filter (All / Gaps / Evidenced)
- **2026-Jul** — Meeting summary AI prompt updated: intro sentences + bullet points + closing sentences format; `SummaryBody` renderer in EvidenceTab parses and displays structured format
- **2026-Jul** — Schedule pills right-aligned in Schedules page; status pills right-aligned in Dashboard meeting cards

## Changelog (Continued)
- **2026-Jun** — Mobile responsive fix: Added "Compliance" as a 5th mobile-only tab on Meeting Report page.
- **2026-Jun** — Hidden mobile instruction box (yellow/amber) on TranscriptTab on small screens (`hidden sm:flex`).
- **2026-Jun** — Action toggle bug fixed: all AI-generated actions now assigned a unique `id` (`action_{uuid}`) at analysis creation time in `processing.py`; previously only rolled-over actions had IDs, causing regular actions to fail with 404 on toggle.
- **2026-Jun** — Inline Transcript Editing: In Speaker View, managers/admins can click a pencil icon (appears on hover) on any speaker turn to edit the raw transcribed text. The textarea saves locally to `localTurns`; the existing "Save" button in the Speaker Manager Panel persists all changes (speaker labels + text) to DB via `PATCH /api/review/{id}/speaker-text`. Escape cancels, Ctrl+Enter saves. Split-turn popup is suppressed while editing.
- **2026-Jun** — AI model upgrade: Switched `analyze_meeting` and `analyze_custom_only` from `gpt-4o` to `o4-mini` with `reasoning_effort="high"`. Speaker name mapping, diarisation, and document extraction functions remain on `gpt-4o` (speed-sensitive). This improves accuracy of compliance evidence mapping by leveraging o4-mini's extended reasoning to interpret nuanced discussion context.
- **2026-Jun** — Organisation Structure admin page rebuilt: two-panel drag-and-drop layout (`@hello-pangea/dnd`). Left panel: full settings+teams tree (all expanded, collapsible). Right panel: Unassigned Staff pool with search and amber header. Drag users between teams or to/from unassigned with optimistic UI. Inline "Add Team" always visible per setting. "Add User" modal creates users directly from org page (managers: attendee/manager/reviewer; admins: all roles). New endpoints: `PATCH /org/users/{id}/assign-team`, `POST /org/invite-user`. Bug fixed: assign-team used wrong collection `db.settings` → corrected to `db.org_settings`.
- **2026-Jun** — Fixed ALL toast notifications being silently swallowed: `<Toaster richColors position="top-right" />` was never mounted in `App.js`. Added it to the root. Now sign-off success/error, speaker save confirmation, action toggle errors, and mark-reviewed all show visible notifications regardless of which tab the user is on. (triggered by Sign Off, Mark Reviewed, etc.) because the `useEffect([meeting.transcript?.speaker_text])` had no `isDirty` guard. Fix: added `if (isDirty) return` guard so `fetchMeeting` never overwrites in-progress edits; `handleSave` now explicitly calls `setLocalTurns(finalTurns)` + `setIsDirty(false)` after a successful PATCH so the post-save reset path is clean. Added `toast.success("Speaker labels saved")` and `toast.error(...)` for user feedback.
- **2026-Jun** — Action toggle error surfaced: `toggleActionComplete` now shows `toast.error()` instead of silently swallowing failures.
- **2026-Jun** — Org-level custom branding: logo upload + brand colour. Applied to sidebar active nav items + mobile top bar. Branding tab added to Admin Panel. `GET /api/auth/me` enriched with `org_branding`. Public logo proxy endpoint added.
- **2026-Jun (Security Hardening)** — Pre-deployment security fixes:
  - CRITICAL: `POST /api/auth/register` now hardcodes `role="attendee"` regardless of client input. Elevated roles (admin/manager) can only be assigned by authenticated admins via `POST /api/admin/users`.
  - HIGH: All meeting-scoped endpoints (`meetings.py`, `review.py`, `recording.py`, `processing.py`) now enforce `org_id == current_user.org_id` in every `find_one`/`update_one`/`delete_one` query — cross-tenant meeting access returns 404.
  - HIGH: Admin user-mutation endpoints (`update_user`, `reset_user_password`) now scoped by `org_id`. Analytics/export/stats queries (`team-insights`, `meetings-brief`, `export-evidence`, `stats`) also filtered by `org_id`.
  - HIGH: `list_meetings` now returns `[]` for users with no `org_id` instead of leaking all meetings.
  - MEDIUM: `get_current_user` (deps.py) now checks `is_active` on every authenticated request. Deactivated users receive 401 immediately.
  - MEDIUM: Token refresh also checks `is_active` before issuing new tokens.
  - DEPLOYMENT: Removed `.env` / `.env.*` / `*.env` lines from root `.gitignore` so `.env` files are tracked and available for Emergent deployment.


- **2026-Jun** — Meeting Schedules feature: Managers/admins can create recurring schedule templates per staff member (Monthly Supervision, Quarterly Appraisal, etc.) and bulk-assign them to all staff or a specific team. Due schedules appear on the Dashboard as compact colour-coded cards (red=overdue, blue=due-this-month) with a "Start" button that pre-fills NewMeeting with schedule_id, title, and attendee. Meeting types are fully configurable per org (name, frequency, colour). New pages: /admin/schedules (Schedules.js). New backend router: schedules.py. New DB collections: schedules, meeting_types.
- **2026-Jun** — Speaker panel "Last saved by" badge: After saving speaker labels via `PATCH /api/review/{id}/speaker-text`, the Speaker Manager Panel shows "Last saved by [name] · [datetime]" in the panel header. Badge hides when there are unsaved changes (isDirty=true) and reappears after save with the updated timestamp.
- **2026-Jun (Security fixes — code review)** — Fixed 4 HIGH + 1 MEDIUM issues: (1) `toggle_action_complete` and `get_comments` in review.py now scope meeting lookup by org_id; (2) `list_meetings_brief` in admin.py now filters by org_id; (3) `standards_documents` upload now stores org_id, and list/update/delete/rescan are all scoped to the uploading org; (4) All settings/teams endpoints in org.py (update, delete, create-team, update-team, delete-team, add-member, remove-member) now verify org_id before acting; (5) `get_portfolio` and `export_portfolio_pdf` in portfolio.py now verify the target user belongs to the caller's org; (6) PDF export in review.py, admin.py, portfolio.py now imports `xml.sax.saxutils.escape` and escapes all dynamic user/AI text in `Paragraph()` calls to prevent 500 crashes on markup-like content.

- **2026-Jul (Terminology + Code Review Fixes)** — (1) Renamed all UI-facing "sub-outcomes" to "outcomes" and "Sub-outcome Coverage" to "Specific Outcomes" across TeamInsights.js, StaffPortfolio.js, EvidenceSidebar.js (DB field `sub_outcomes` unchanged). (2) PII redaction now case-insensitive (re.sub with IGNORECASE, previously str.replace). (3) Find & Replace "Replace One" now sends `replace_one: true` to backend which limits substitution to count=1. (4) Removed duplicate `update_org` route from super_admin.py. (5) `delete_org` cascade fixed: `invites` → `invitations`, plus now also deletes reviewer_comments, review_edits, audio_files per org. (6) Attendee lookup in `create_meeting` and `update_attendees` now org-scoped. (7) `delete_meeting` cascade now also deletes audit_logs entries.

- **2026-Jul (Stable Release Code Review — all issues resolved)** — (1) HIGH: Cross-tenant custom standards leak fixed — `processing.py` + `review.py` now filter `standards_documents` by `org_id`. (2) HIGH: CC excerpt export now applies `sign_off_manager_id` exclusion (evidence attributed to supervisees only — same rule as team-insights/portfolio/export-evidence). (3) MEDIUM: Supervision template now org-scoped (`supervision_template:{org_id}` key) with fallback to legacy global for existing orgs; both analysis paths updated. (4) LOW: Meeting count in excerpt PDFs now uses distinct IDs not titles. (5) LOW: Auth cookies set to `secure=True`. (6) LOW: Unused `KeepTogether` import and `BLUE_MID` constant removed. (7) LOW: CC excerpt frontend reads `Content-Disposition` filename from server response.