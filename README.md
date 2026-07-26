# Supervision2

**AI-powered supervision and compliance evidence platform for UK adult social care providers.**

Supervision2 (1two.one) records supervision meetings, generates transcripts and summaries, and automatically maps discussion content to CQC regulations and Care Certificate standards — producing audit-ready evidence for CQC inspections.

---

## Features

### Recording & Transcription
- In-browser meeting recording with pause/resume controls
- Automatic audio upload and background transcription via **AssemblyAI** with speaker diarisation
- Speaker diarisation hint based on attendee count for improved accuracy
- "Re-scan Audio" button to re-transcribe an existing recording without losing analysis
- Speaker identification panel — rename, reassign, swap, and split speaker turns
- Inline transcript editing and Find & Replace (with single/all occurrence modes)
- Manual anonymisation — highlight any name → replace with initial, persisted and audit-logged

### AI Compliance Mapping
- **CQC Regulations** — 14 regulations (Reg 9–20, 20A, 12) mapped with evidence excerpts and confidence labels
- **48 CQC Quality Statements** — all seeded from the latest CQC framework
- **Care Certificate Standards** — all 16 standards (2025 edition) with 216 granular outcomes (e.g. 2.1a, 2.1b)
- **Organisational Standards** — managers upload custom PDF/DOCX reference documents; AI extracts criteria and maps evidence automatically
- Re-scan evidence button re-runs AI mapping against the current transcript (runs in background, no timeout)
- AI-generated meeting summary (intro + bullets + closing), action items, and risk/concern extraction

### Review & Sign-off Workflow
- PII Review Gate — AI + regex scans for third-party names, phone numbers, emails, postcodes, NHS/NI numbers before anyone can view the report
- Attendees mark themselves as reviewed; manager can sign off once all attendees confirm
- Edit summary, action wording, and evidence text
- Accept / Reject / Flag individual evidence items
- Shared reviewer role — post-sign-off comment access without editing rights
- Full audit trail — every recording event, edit, sign-off, and comment logged with timestamp and user

### Staff Portfolios & Team Intelligence
- **Staff Portfolio** — per-staff evidence grouped by CQC / Care Cert / Organisational standards, with meeting history and PDF export
- **Team Intelligence Matrix** — staff × standards heatmap with coverage %, gap analysis, recurring risks, and outstanding actions
- **CQC Inspection Prep** — per-regulation coverage bars with expandable gap details
- **Supervision Matrix** — colour-coded schedule compliance grid (red = overdue, amber = due, green = up to date)

### Scheduling
- Recurring schedule templates per staff member (Monthly Supervision, Quarterly Appraisal, etc.)
- Bulk-assign schedules to all staff or a specific team
- Due schedules surface on the Dashboard with "Start" button pre-filling the new meeting form

### Document Import
- Import existing supervision PDFs/DOCX documents linked to a staff member
- AI evidence mapping runs on the extracted text; evidence appears in staff portfolio

### Exports
- **PDF Report** — full meeting report with summary, actions, risks, evidence, and optional transcript
- **Transcript-only PDF** — standalone export per meeting or bulk download for all signed-off meetings
- **Care Certificate Evidence PDF** — staff-picker export of evidenced outcomes across all signed-off meetings

### Admin & Organisation
- Multi-tenant: each organisation is fully isolated by `org_id`
- Org-level custom branding (logo + brand colour applied to the sidebar)
- Organisation Structure page with drag-and-drop team management
- Supervision template — admin configures meeting steps shown as a checklist during recording
- Invite admin flow — Super Admin sends branded email invite; accepts via secure single-use link

### Super Admin
- Manage all organisations and users from a single dashboard
- Create orgs, invite admins, add users directly
- Suspend/activate organisations

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React (JavaScript), Tailwind CSS, Shadcn UI, Lucide React |
| Backend | FastAPI (Python 3.11), Motor (async MongoDB driver) |
| Database | MongoDB |
| Transcription | AssemblyAI (speaker diarisation) |
| AI Analysis | OpenAI o4-mini (compliance mapping) / GPT-4o (speaker ID, diarisation) |
| Email | Resend |
| Storage | Object storage (audio files, uploaded documents) |
| Auth | JWT (Bearer token + httpOnly refresh cookie) |

---

## Project Structure

```
/
├── backend/
│   ├── server.py              # FastAPI app entry point, CORS, startup
│   ├── deps.py                # get_db(), get_current_user(), require_roles()
│   ├── routers/
│   │   ├── auth.py            # Login, register, logout, invite flow, password change
│   │   ├── meetings.py        # Meeting CRUD, attendees
│   │   ├── recording.py       # Start/pause/resume/stop recording events
│   │   ├── processing.py      # Audio upload, transcription, AI analysis (background)
│   │   ├── review.py          # Review workflow, sign-off, evidence editing, exports
│   │   ├── admin.py           # Users, standards library, evidence exports
│   │   ├── org.py             # Org settings, teams, branding, schedules
│   │   ├── portfolio.py       # Staff portfolios, CC evidence PDF
│   │   ├── schedules.py       # Meeting schedules and types
│   │   ├── doc_uploads.py     # Supervision document import
│   │   └── super_admin.py     # Super admin org/user management
│   └── utils/
│       ├── ai.py              # AssemblyAI + OpenAI integration
│       ├── seed.py            # CQC + Care Certificate standards seed data
│       ├── anonymise.py       # Transcript anonymisation
│       └── redaction.py       # PII redaction helpers
│
└── frontend/src/
    ├── App.js                 # Routes with ProtectedRoute
    ├── context/AuthContext.js # JWT auth, token refresh
    ├── components/
    │   ├── Layout.js          # Sidebar navigation (org branding applied here)
    │   ├── PIIReviewGate.js   # PII scan UI
    │   ├── admin/             # Admin tab components (Standards, Users, Export, Template, Branding, Transcript)
    │   └── report/            # Meeting report sub-components (Evidence, Transcript, Comments, Audit, Sidebar, Email)
    └── pages/
        ├── Login.js
        ├── Dashboard.js
        ├── NewMeeting.js
        ├── RecordingScreen.js
        ├── MeetingReport.js
        ├── AdminLibrary.js
        ├── OrgSettings.js
        ├── StaffPortfolio.js
        ├── TeamInsights.js
        ├── InspectionPrep.js
        ├── CareCertPrep.js
        ├── SupervisionMatrix.js
        ├── Schedules.js
        └── SuperAdminDashboard.js
```

---

## User Roles

| Role | Access |
|---|---|
| `super_admin` | Manage all organisations and users (separate dashboard) |
| `admin` | Full access within their org — users, standards, branding, exports |
| `manager` | Create meetings, sign off, view all meetings, upload standards docs |
| `attendee` | Record meetings, review assigned meetings |
| `shared_reviewer` | View signed-off meetings, add comments |

---

## Environment Variables

### Backend (`backend/.env`)

```env
MONGO_URL=mongodb://localhost:27017
DB_NAME=supervision2

JWT_SECRET=your-secret-key
CORS_ORIGINS=http://localhost:3000

ADMIN_EMAIL=admin@yourorg.com
ADMIN_PASSWORD=YourAdminPassword1!

SUPER_ADMIN_EMAIL=superadmin@yourdomain.com
SUPER_ADMIN_PASSWORD=SuperAdminPassword1!

EMERGENT_LLM_KEY=your-emergent-key        # OpenAI GPT-4o + o4-mini
ASSEMBLYAI_API_KEY=your-assemblyai-key    # Transcription + diarisation

RESEND_API_KEY=your-resend-key            # Email (invites, report sharing)
SENDER_EMAIL=noreply@yourdomain.com
FRONTEND_URL=https://yourdomain.com
```

### Frontend (`frontend/.env`)

```env
REACT_APP_BACKEND_URL=https://yourdomain.com
```

---

## Getting Started

### Prerequisites
- Node.js 18+
- Python 3.11+
- MongoDB (local or Atlas)
- API keys for: AssemblyAI, OpenAI (or Emergent LLM Key), Resend

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn server:app --reload --port 8001
```

The admin account and all CQC/Care Certificate standards are seeded automatically on first startup.

### Frontend

```bash
cd frontend
yarn install
yarn start
```

---

## Third-Party Services

| Service | Purpose | Get Key |
|---|---|---|
| AssemblyAI | Audio transcription + speaker diarisation | [assemblyai.com](https://www.assemblyai.com) |
| OpenAI (GPT-4o / o4-mini) | Compliance mapping, PII scan, speaker ID | [platform.openai.com](https://platform.openai.com) |
| Resend | Email invites and report sharing | [resend.com](https://resend.com) |

---

## Password Policy

All user passwords must meet:
- Minimum 10 characters
- At least 1 uppercase letter
- At least 1 lowercase letter
- At least 1 number
- At least 1 special character

---

## Security Notes

- All meeting and user queries are scoped by `org_id` — cross-tenant access returns 404
- `POST /api/auth/register` always assigns `role=attendee`; elevated roles require admin action
- Deactivated users are rejected on every authenticated request (not just at login)
- Audio files are automatically deleted after a 5-minute grace period post sign-off (GDPR)
- PII Review Gate runs before any report is viewable; original and redacted transcripts stored separately
- Auth cookies set to `Secure` + `HttpOnly`

---

## Deployment

The app is deployed at **[1two.one](https://1two.one)** via Cloudflare with a FastAPI backend on port 8001 and a React frontend on port 3000.

All heavy AI operations (compliance mapping, document extraction) use FastAPI `BackgroundTasks` to avoid Cloudflare's 100-second gateway timeout.

---

## Licence

Private — all rights reserved. © 1two.one
