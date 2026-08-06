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
- **Auth:** JWT (Bearer token in localStorage), Email OTP 2FA

---

## Jurisdiction Model (Single-Deployment, Multi-Region)
- `organisations.jurisdiction` column: `'england'` | `'wales'` | `'scotland'` | `'northern_ireland'`
- `organisations.service_type` column: `'residential'` | `'domiciliary'` | `NULL` — **required for NI, NULL for other jurisdictions**
- `standards_entries.jurisdiction` column: same 4 values
- `standards_entries.service_type` column: `'residential'` | `'domiciliary'` | `NULL` — NI RQIA standards tagged by service_type; NISCC (NULL = shared)
- England orgs: CQC (47) + Care Certificate (16) = 63 standards
- Wales orgs: CIW (23) + AWIF (7) + SCW (6) = 36 standards
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

### P1 (Next)
- Super Admin "Edit Org" form needs Jurisdiction + Service Type fields (NI orgs need to be able to update service_type post-creation)

### P1
- Jurisdiction-aware frontend labels: show "RQIA Evidence" and "NISCC Evidence" (instead of "CQC/Care Cert") in MeetingReport, InspectionPrep pages for NI orgs

### P2 (Upcoming)
- **AWIF granularity review** (Wales consultation pending): Current AWIF sub-outcomes are section headings (topic level). Decision pending from Welsh users on whether to drill down to the specific "I can/I understand" practice learning outcome statements. All 7 workbook .docx files available in job assets for re-extraction when ready.
- **Scotland NIF** — parked indefinitely. Content entirely behind Turas login wall (launched May 2025, no public docs). Add as `type='nif'`, `jurisdiction='scotland'` when source material surfaces.
- Role-specific competency framework upload (admin uploads per-role competency doc; AI maps evidence against it)
- Skills for Care Effective Supervision Guide — per-org upload option

### P2 (Future)
- Pending invites dashboard
- Usage dashboard (meeting counts, last activity, storage per org)
- Billing hooks (Stripe — tie orgs to plan/subscription)
- Impersonate org feature for Super Admins
- Meeting duplicate / template feature
- Bulk export of evidence reports
