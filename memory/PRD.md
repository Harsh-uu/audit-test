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

### P1 (Remaining)
- Wales, Scotland, Northern Ireland AI prompt rewrites: Apply "Intent-first" conceptual framework (deployed for England) to the other jurisdictions

### P1.5 (Upcoming)
- **Achievements section — DONE** (Aug 2026, Session 4): AI extracts 1–5 specific achievement moments from meeting transcripts; rendered between Summary and Actions in the Evidence tab with emerald green/star visual styling. DB migration applied.
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
