# Supervision 2.0 - PRD & Project Memory

## Product Overview
Supervision 2.0 is a web-based compliance evidence platform for UK adult social care providers. Users record supervision meetings, and the system automatically generates transcripts, summaries, CQC compliance mappings, and Care Certificate competency evidence.

**Deployment URL Identifier:** supervison2
**Product Name:** Supervision

---

## Architecture
- **Frontend:** React (JavaScript), Tailwind CSS, Shadcn UI, Lucide React icons
- **Backend:** FastAPI (Python), MongoDB, Motor (async MongoDB driver)
- **AI:** OpenAI GPT-4o (via emergentintegrations) for analysis, OpenAI Whisper-1 for transcription
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

### P0 (Critical - Next Session)
- Test full audio upload → transcription → analysis flow with real audio
- Verify Whisper transcription output quality
- Validate GPT-4o compliance mappings are relevant and accurate

### P1 (Important)
- Auto audio deletion confirmation workflow display improvements
- Add PDF export of approved reports
- Shared reviewer access control (share with specific users)
- Email/report sharing via Resend
- Admin Library: upload CQC/Care Cert reference documents for AI evidence matching
- Meeting search and filtering improvements
- Mobile-responsive recording screen

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

*Last Updated: 2025-06-26*
