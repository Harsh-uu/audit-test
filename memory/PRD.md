# Supervision 2.0 - PRD & Project Memory

## Product Overview
Supervision 2.0 is a web-based compliance evidence platform for UK adult social care providers. Users record supervision meetings, and the system automatically generates transcripts, summaries, CQC compliance mappings, and Care Certificate competency evidence.

**Deployment URL Identifier:** supervison2
**Product Name:** Supervision

---

## Architecture
- **Frontend:** React (JavaScript), Tailwind CSS, Shadcn UI, Lucide React icons
- **Backend:** FastAPI (Python), MongoDB, Motor (async MongoDB driver)
- **AI:** OpenAI GPT-4o (via emergentintegrations) for analysis, OpenAI Whisper-1 for transcription (with care/clinical domain terminology prompt for accuracy)
- **Email:** Resend ✅ (configured with live API key)
- **Storage:** Emergent Object Storage (for audio files and standards documents)
- **Auth:** JWT (Bearer token in localStorage + httpOnly cookies)

---

## User Roles
| Role | Description |
|------|-------------|
| admin | Full access, manage users and standards library |
| manager | Create meetings, sign-off, view all meetings |
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
- [x] Read-only transcript

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
- None outstanding

### P1 (Important)
- Meeting search and filtering on the Dashboard

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

*Last Updated: 2026-Feb*
