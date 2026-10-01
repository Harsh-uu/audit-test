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
- Multi-tenant: each organisation is fully isolated by `org_id` with PostgreSQL Row Level Security (RLS)
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
| Frontend | React (JavaScript), Vite 5, Tailwind CSS, Shadcn UI, Lucide React |
| Backend | FastAPI (Python 3.11), asyncpg |
| Database | PostgreSQL via **Supabase** (with Row Level Security on all tables) |
| Transcription | AssemblyAI (speaker diarisation) |
| AI Analysis | Google Vertex AI — Gemini 2.5 Flash (primary, UK/EU data residency) with automatic OpenAI GPT-4o fallback — compliance mapping, PII scan, speaker ID, diarisation |
| Email | Resend |
| Storage | Supabase Storage (audio files, uploaded documents) |
| Auth | JWT Bearer tokens (access + refresh), Email OTP 2FA |
| Logging | Grafana Cloud Loki (GB South — EU data residency) |

---

## Project Structure

```
/
├── backend/
│   ├── server.py              # FastAPI app entry point, CORS, security headers, startup
│   ├── deps.py                # get_current_user(), role guards (access token type enforced)
│   ├── database.py            # asyncpg pool, with_admin() / with_org() context managers
│   ├── init_db.py             # Runs the versioned migration ledger on startup
│   ├── migrations/            # Numbered schema chunks (RLS, FKs, indexes) + schema_migrations ledger
│   ├── loki_logging.py        # Non-blocking Grafana Loki log handler
│   ├── routers/
│   │   ├── auth.py            # Login, register, logout, invite flow, 2FA, password change
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
│       ├── ai.py              # AssemblyAI + Vertex AI (Gemini, primary) + OpenAI GPT-4o (fallback), prompt injection guards
│       ├── seed.py            # CQC + Care Certificate + SSSC + CIW standards seed data
│       ├── anonymise.py       # Transcript anonymisation
│       ├── redaction.py       # PII redaction helpers
│       ├── file_security.py   # Upload validation and sanitisation
│       └── storage.py         # Supabase Storage integration
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
| `manager` | Create meetings, sign off, view all meetings, upload standards docs, manage risks |
| `attendee` | Record meetings, review assigned meetings |
| `shared_reviewer` | View signed-off meetings, add comments |

---

## Environment Variables

### Backend (`backend/.env`)

```env
# Database (Supabase PostgreSQL)
MONGO_URL=postgresql://postgres:[password]@[host]:5432/postgres
DB_NAME=postgres

# Auth
JWT_SECRET=your-32-char-minimum-random-secret
CORS_ORIGINS=https://yourdomain.com

# Seed accounts
ADMIN_EMAIL=admin@yourorg.com
ADMIN_PASSWORD=YourAdminPassword1!
SUPER_ADMIN_EMAIL=superadmin@yourdomain.com
SUPER_ADMIN_PASSWORD=YourSuperAdminPassword1!

# AI & Transcription
GCP_PROJECT_ID=your-gcp-project-id        # Vertex AI (Gemini 2.5 Flash) — primary AI provider
GCP_LOCATION=europe-west2                 # Vertex AI region — UK/EU data residency
GCP_SERVICE_ACCOUNT_JSON={...}            # Vertex AI service account credentials (JSON, single line)
OPENAI_API_KEY=your-openai-key            # GPT-4o — automatic fallback if Gemini fails, also used for speaker ID/diarisation
ASSEMBLYAI_API_KEY=your-assemblyai-key    # Transcription + diarisation
EMERGENT_LLM_KEY=your-emergent-key        # Emergent-managed object storage (audio/document uploads) — NOT used for AI calls

# Email
RESEND_API_KEY=your-resend-key
SENDER_EMAIL=noreply@yourdomain.com
FRONTEND_URL=https://yourdomain.com

# Logging (Grafana Cloud Loki — EU region)
LOKI_URL=https://logs-prod-035.grafana.net
LOKI_USER=your-loki-tenant-id
LOKI_TOKEN=your-loki-write-token
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
- Supabase project (PostgreSQL) — [supabase.com](https://supabase.com)
- API keys for: AssemblyAI, Google Cloud (Vertex AI service account), OpenAI (fallback), Resend, Emergent LLM Key (object storage)

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn server:app --reload --port 8001
```

The schema, RLS policies, admin account, and all CQC/Care Certificate standards are created and seeded automatically on first startup — no manual SQL step required.

### Frontend

```bash
cd frontend
yarn install
yarn dev
```

---

## Third-Party Services

| Service | Purpose | Get Key |
|---|---|---|
| Supabase | PostgreSQL database + file storage | [supabase.com](https://supabase.com) |
| AssemblyAI | Audio transcription + speaker diarisation | [assemblyai.com](https://www.assemblyai.com) |
| Google Cloud Vertex AI | Gemini 2.5 Flash — primary AI provider (UK/EU data residency) | [console.cloud.google.com](https://console.cloud.google.com/vertex-ai) |
| OpenAI (GPT-4o) | Automatic fallback if Gemini fails; also used for speaker ID, diarisation | [platform.openai.com](https://platform.openai.com) |
| Resend | Email invites and report sharing | [resend.com](https://resend.com) |
| Grafana Cloud | Log management (EU — GB South region) | [grafana.com](https://grafana.com/products/cloud/) |

---

## Password Policy

All user passwords must meet:
- Minimum 10 characters
- At least 1 uppercase letter
- At least 1 lowercase letter
- At least 1 number
- At least 1 special character

---

## Security

- **Row Level Security** — all 25 PostgreSQL tables have RLS enabled; org-scoped tables enforce `org_id` isolation at the database layer
- **JWT token types** — `type=access` strictly enforced on all guarded endpoints; `mfa_pending` and `refresh` tokens rejected
- **Role hierarchy** — managers cannot modify admin accounts; admins cannot modify super_admin accounts
- **Security headers** — `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Strict-Transport-Security` (2yr + preload via Cloudflare)
- **No cookies** — JWT stored in `localStorage`, sent as `Authorization: Bearer` header; CSRF not applicable
- **Parameterised queries** — all SQL uses asyncpg `$N` bound parameters; no string interpolation of user input
- **Prompt injection guards** — XML delimiters around all untrusted input passed to LLMs
- **PII redaction** — AI + regex scan gates every report before any user can view it
- **Audit trail** — every recording event, edit, sign-off, and comment logged with timestamp and user
- **Audio deletion** — files automatically deleted after sign-off grace period (GDPR)
- **Startup validation** — weak `JWT_SECRET` and default `SUPER_ADMIN_PASSWORD` both cause CRITICAL log warnings at boot

---

## Deployment

The app is deployed at **[1two.one](https://1two.one)** via Cloudflare (GB South data residency) with:
- FastAPI backend on port 8001
- React (Vite 5) frontend on port 3000
- PostgreSQL database on Supabase (EU region)
- Logs shipped to Grafana Cloud Loki (GB South)

All heavy AI operations (compliance mapping, document extraction) use FastAPI `BackgroundTasks` to avoid Cloudflare's 100-second gateway timeout.

---

## Licence

Private — all rights reserved. © 1two.one
