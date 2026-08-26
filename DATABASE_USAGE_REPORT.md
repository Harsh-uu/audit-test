# Database Usage Report — evidence-link-4 (1two.one)

**Generated:** 26 August 2026  
**App Name:** evidence-link-4  
**Live URL:** https://1two.one  
**Deployment:** transcript-vault-2  
**Template:** FastAPI + React + MongoDB (FARM stack)

---

## Executive Summary (Plain English)

This application ("Supervision 2.0") uses **two separate database systems**:

1. **Supabase (PostgreSQL)** — This is the real, active database. Every single feature in the app (login, meetings, audio, reviews, admin, etc.) reads and writes data here. It is hosted by Supabase in the EU.

2. **Emergent Shared MongoDB** — This is an old, unused database that the hosting platform automatically creates. It has 23 collections of stale data from July/August 2026 (before the app was migrated to Supabase). **No part of the running application talks to it.**

Additionally, the app uses **Supabase Storage** (for audio recordings and documents) and **Emergent Object Storage** (for organisation logo images).

**Bottom line:** Supabase PostgreSQL is the only database that matters. The MongoDB is dead weight from an earlier version of the app.

---

## Part 1: Where Supabase Is Used — File by File

### 1.1 Database Connection Setup

| What | File | Line(s) | What It Does | Any Issues? |
|------|------|---------|--------------|-------------|
| Connection pool creation | `database.py` | 26–45 | Opens a pool of 2–15 connections to Supabase PostgreSQL using the `DATABASE_URL` environment variable. Uses SSL encryption. | ✅ **Good** — Statement cache disabled (line 42) which is correct for Supabase's connection pooler. Without this, random errors would occur. |
| Connection pool shutdown | `database.py` | 48–52 | Cleanly closes all database connections when the app shuts down. | ✅ No issues |
| Organisation-scoped access | `database.py` | 59–102 | The `with_org()` function. Every time a user does something, this locks the database to only show data for their organisation. This is the security barrier. | ✅ **Good security pattern** — Uses PostgreSQL Row Level Security (RLS). Any failure to switch roles causes a hard crash rather than silently showing wrong data. |
| Admin access (no org filter) | `database.py` | 105–118 | The `with_admin()` function. Used for login, seeding, background jobs — operations that need to see all organisations. | ✅ No issues |
| JSONB codec registration | `database.py` | 16–23 | Teaches the database driver how to read/write JSON data. | ⚠️ **Minor risk** — The code comments (lines 68–85) warn that JSONB columns can come back as raw text strings after role switching. Every developer must manually add safety guards when reading JSON data. This has caused bugs before (see data migrations in `init_db.py` lines 697–760 that fix double-encoded JSON). |

### 1.2 App Startup

| What | File | Line(s) | What It Does | Any Issues? |
|------|------|---------|--------------|-------------|
| Load environment variables | `server.py` | 1–2 | Loads `DATABASE_URL`, `SUPABASE_URL`, etc. from the `.env` file baked into the app image. | ✅ No issues |
| Create database pool | `server.py` | 182–184 | On startup, connects to Supabase PostgreSQL. Logs "PostgreSQL pool ready". | ✅ Confirmed working in production logs |
| Run schema creation | `server.py` | 193–194 | Runs `init_db.create_schema()` — creates all tables if they don't exist, runs migrations. | ⚠️ **Performance note** — Runs on EVERY startup (every deployment), not just the first time. It's safe (idempotent) but adds 1–2 seconds to boot time. Not a real problem. |
| Seed data | `server.py` | 196–202 | Loads standard CQC/Care Certificate regulations into the database. Wrapped in try/catch so a seeding failure doesn't crash the whole app. | ✅ Good pattern |
| Warm standards cache | `server.py` | 204–205 | Pre-loads standards into memory so the app doesn't hit the database every time it needs them. | ✅ Good for performance |
| Start background worker | `server.py` | 213 | Starts the job queue that processes audio transcriptions in the background. | ✅ No issues |

### 1.3 Schema & Tables (init_db.py)

The app creates **22 tables** in Supabase PostgreSQL. Here is every table, what it stores, and any issues:

| Table | Line(s) | What It Stores | RLS? | Issues |
|-------|---------|---------------|------|--------|
| `organisations` | 29–45 | Company/org records (name, branding, jurisdiction) | ✅ Yes | ✅ No issues |
| `users` | 47–72 | All user accounts (email, password hash, role, MFA settings) | ✅ Yes | ✅ Has unique index on email |
| `meetings` | 74–117 | Core meeting records (title, date, attendees, status, recording events, PII redactions) | ✅ Yes | ⚠️ Very wide table — 30+ columns. Many JSONB columns. Acceptable for this use case but could be split if it grows further. |
| `transcripts` | 119–134 | Audio transcription text, speaker-labelled text, speaker colours | ✅ Yes | ✅ No issues |
| `analyses` | 136–157 | AI-generated meeting analysis — summary, actions, risks, evidence mappings | ✅ Yes | ✅ No issues |
| `audio_files` | 159–179 | Metadata about uploaded audio files (path, size, deletion status) — actual audio stored in Supabase Storage | ✅ Yes | ✅ No issues |
| `review_edits` | 181–196 | Audit trail of who edited what in a meeting review | ✅ Yes | ✅ No issues |
| `reviewer_comments` | 198–213 | Post-sign-off comments on meetings | ✅ Yes | ✅ No issues |
| `standards_entries` | 218–243 | CQC/Care Certificate standards — both system-wide and org-custom | ✅ Yes (special) | ✅ Good — RLS allows org-custom entries to be scoped while system entries (org_id IS NULL) are visible to everyone |
| `standards_documents` | 246–271 | Uploaded standards documents (metadata + parsed AI criteria) | ✅ Yes | ✅ No issues |
| `login_attempts` | 274–279 | Brute-force login protection (count + lockout time) | ❌ No RLS | ✅ Correct — this tracks by IP+email, not org |
| `password_reset_tokens` | 282–288 | One-time password reset tokens | ❌ No RLS | ✅ Correct — tokens are looked up by value, not by org |
| `invitations` | 291–305 | Invite tokens for onboarding new users | ✅ Yes | ✅ No issues |
| `settings` | 308–318 | Key-value store (supervision templates per org) | ✅ Yes | ✅ No issues |
| `jobs` | 321–330 | Background job queue for audio processing | ❌ No RLS | ✅ Correct — background worker processes all orgs |
| `audit_logs` | 333–348 | System-level event log (speaker edits, PII reviews, etc.) | ✅ Yes | ✅ No issues |
| `org_settings` | 351–364 | Org structural settings (departments/care homes) | ✅ Yes | ✅ No issues |
| `teams` | 366–381 | Teams within a department | ✅ Yes | ✅ No issues |
| `schedules` | 383–399 | Recurring supervision schedules per staff member | ✅ Yes | ✅ No issues |
| `meeting_types` | 401–415 | Configurable meeting type definitions (Supervision, Appraisal, etc.) | ✅ Yes | ✅ No issues |
| `meeting_prep` | 417–435 | Dynamic Supervision prep agendas and coverage results | ✅ Yes | ✅ Has UNIQUE constraint on meeting_id |
| `focus_topics` | 437–451 | Org-scoped focus topics for Dynamic Supervision | ✅ Yes | ✅ No issues |
| `supervision_uploads` | 453–480 | Imported historical supervision documents | ✅ Yes | ✅ No issues |
| `evidence_feedback` | 582–605 | Training data log for AI evidence quality (manager accept/reject decisions) | ✅ Yes | ✅ No issues |

### 1.4 Indexes

| Index | Line(s) | What It Speeds Up | Issues |
|-------|---------|-------------------|--------|
| `idx_meetings_org_status_date` | 650–651 | Composite: org + status + date. The main dashboard query. | ✅ **Well designed** — Covers the most common query pattern (list meetings for an org, filtered by status, sorted by date). Replaced two single-column indexes (lines 656–657). |
| `idx_meetings_created_at` | 484 | Sorting meetings by date | ✅ No issues |
| `idx_users_email` | 486 | Looking up users by email (login) | ✅ Essential — also has UNIQUE constraint |
| `idx_users_org_id` | 487 | Finding all users in an organisation | ✅ No issues |
| `idx_transcripts_meeting_id` | 488 | Finding the transcript for a meeting | ✅ No issues |
| `idx_analyses_meeting_id` | 489 | Finding the analysis for a meeting | ✅ No issues |
| `idx_review_edits_meeting_id` | 490 | Finding edit history for a meeting | ✅ No issues |
| `idx_reviewer_comments_meeting_id` | 491 | Finding comments for a meeting | ✅ No issues |
| `idx_audit_logs_meeting_id` | 492 | Finding audit trail for a meeting | ✅ No issues |
| `idx_standards_type` | 493 | Looking up standards by type + reference | ✅ No issues |
| `idx_jobs_status` | 494 | Finding pending background jobs | ✅ No issues |
| `idx_schedules_org_id` | 495 | Finding schedules for an org | ✅ No issues |
| `idx_meeting_types_org_id` | 496 | Finding meeting types for an org | ✅ No issues |
| `idx_supervision_uploads_org_id` | 497 | Finding uploads for an org | ✅ No issues |
| `idx_supervision_uploads_staff_id` | 498 | Finding uploads for a specific staff member | ✅ No issues |

**Missing Indexes (Potential Performance Gaps):**

| What's Missing | Why It Might Matter |
|----------------|---------------------|
| No index on `audio_files.meeting_id` | Audio files are looked up by meeting_id. With RLS filtering on org_id, the planner may do a sequential scan on this table. Low priority if the table is small. |
| No index on `invitations.token` | Token lookups happen during invite acceptance. The UNIQUE constraint on `token` column implicitly creates an index, so this is actually fine. |
| No index on `evidence_feedback.meeting_id` | Feedback is queried per meeting. Low priority — this table is likely small. |
| No index on `meeting_prep.org_id` | RLS filters on org_id but there's no index for it. The UNIQUE constraint on `meeting_id` helps for direct lookups but not for org-wide listing. |

### 1.5 Feature-by-Feature Database Usage (Every Router)

#### Authentication (`routers/auth.py` — 710 lines)

| Feature | Lines | DB Operations | Tables Touched | Access Mode |
|---------|-------|--------------|----------------|-------------|
| Login | 208–328 | Read user by email, check/update login attempts, generate MFA code | `users`, `login_attempts` | `with_admin()` |
| MFA Verification | 336–387 | Read user, verify code, update attempt count, clear code | `users` | `with_admin()` |
| MFA Toggle | 406–434 | Read user, verify code, enable/disable MFA | `users` | `with_admin()` |
| Get Current User | 441–475 | Read user, read org name/branding | `users`, `organisations` | `with_admin()` |
| Refresh Token | 478–528 | Read user to verify still active | `users` | `with_admin()` |
| Forgot Password | 531–595 | Read user by email, create reset token | `users`, `password_reset_tokens` | `with_admin()` |
| Reset Password | 598–617 | Verify token, update password hash | `password_reset_tokens`, `users` | `with_admin()` |
| Change Password | 625–639 | Verify old password, update to new | `users` | `with_admin()` |
| Validate Invite | 645–669 | Read invite, user, and org details | `invitations`, `users`, `organisations` | `with_admin()` |
| Accept Invite | 673–700 | Update user password+name, mark invite used | `invitations`, `users` | `with_admin()` |

**Note:** All auth operations use `with_admin()` (no org filtering) because login/password operations must work before the user's org is known.

#### Meetings (`routers/meetings.py` — 519 lines)

| Feature | Lines | Tables Touched | Access Mode |
|---------|-------|----------------|-------------|
| List meetings | 114–186 | `meetings`, `users` | `with_admin()` for attendee lookup, `with_org()` for meeting listing |
| Get single meeting | 195–243 | `meetings`, `transcripts`, `analyses`, `audio_files` | `with_admin()` / `with_org()` |
| Create meeting | 267–332 | `meetings` | `with_org()` |
| Update meeting | 335–431 | `meetings` | `with_org()` |
| Get meeting transcript | 435–448 | `transcripts` | `with_org()` |
| Get transcript text | 451–465 | `transcripts` | `with_org()` |
| Get analysis | 468–484 | `analyses` | `with_org()` |
| Delete meeting | 486–516 | `meetings`, `transcripts`, `analyses`, `audio_files`, `review_edits`, `reviewer_comments`, `audit_logs`, `meeting_prep` | `with_org()` |

#### Dashboard (`routers/dashboard.py` — 137 lines)

| Feature | Lines | Tables Touched | Access Mode |
|---------|-------|----------------|-------------|
| Get dashboard stats | 42–95 | `meetings` (count by status), `users` (count) | `with_org()` |

#### Recording (`routers/recording.py` — 237 lines)

| Feature | Lines | Tables Touched | Access Mode |
|---------|-------|----------------|-------------|
| Start/stop/pause recording events | 52–237 | `meetings` (update recording_events JSONB) | `with_org()` |

#### Audio Processing (`routers/processing.py` — 360 lines)

| Feature | Lines | Tables Touched | Storage Used | Access Mode |
|---------|-------|----------------|-------------|-------------|
| Upload audio | 38–89 | `meetings`, `audio_files`, `jobs` | **Supabase Storage** (`put_audio`) | `with_org()` |
| Get processing status | 91–120 | `meetings`, `jobs` | — | `with_org()` |
| Start analysis | 122–190 | `meetings`, `transcripts`, `analyses` | — | `with_org()` |
| Get analysis result | 202–260 | `analyses` | — | `with_org()` |
| Retranscribe audio | 271–360 | `meetings`, `audio_files`, `transcripts`, `analyses`, `jobs` | **Supabase Storage** (`get_audio`) | `with_org()` / `with_admin()` |

#### Review (`routers/review.py` — 2422 lines)

| Feature | Lines | Tables Touched | Access Mode |
|---------|-------|----------------|-------------|
| Complete PII review | 160–204 | `meetings` | `with_admin()` |
| Update analysis (summary, actions, risks, evidence) | 216–570 | `analyses`, `review_edits`, `evidence_feedback` | `with_org()` / `with_admin()` |
| Add/edit reviewer comments | 572–620 | `reviewer_comments` | `with_org()` |
| Sign off meeting | 625–700 | `meetings` | `with_org()` / `with_admin()` |
| Speaker text editing | 718–1000 | `transcripts`, `audit_logs` | `with_org()` |
| Evidence rescan (AI re-analysis) | 1072–1200 | `analyses`, `meetings`, `standards_entries`, `standards_documents` | `with_org()` |
| Reopen meeting | 1228–1370 | `meetings`, `review_edits` | `with_admin()` / `with_org()` |
| PII redaction management | 1385–1530 | `meetings` (pii_redactions JSONB) | `with_org()` |
| Audio deletion lifecycle | 1543–1620 | `meetings`, `audio_files` | `with_org()` |
| Transcript safety warnings | 1789–1910 | `transcripts`, `meetings` | `with_admin()` / `with_org()` |
| Sharing meetings | 2219–2420 | `meetings` (shared_with JSONB), `users` | `with_org()` |

#### Admin (`routers/admin.py` — 2326 lines)

| Feature | Lines | Tables Touched | Storage Used | Access Mode |
|---------|-------|----------------|-------------|-------------|
| User management (CRUD) | 98–508 | `users`, `invitations` | — | `with_admin()` / `with_org()` |
| Standards management | 329–480 | `standards_entries`, `standards_documents` | **Supabase Storage** (`put_document`) | `with_org()` |
| Org settings (departments) | 891–1025 | `org_settings`, `teams`, `users` | — | `with_org()` / `with_admin()` |
| Meeting types | 1266–1414 | `meeting_types` | — | `with_org()` |
| Audit log viewing | 1446–1580 | `audit_logs`, `review_edits` | — | `with_admin()` / `with_org()` |
| Data export | 1612–1705 | `meetings`, `transcripts`, `analyses` | — | `with_admin()` / `with_org()` |
| Super admin operations | 2013–2326 | `organisations`, `users`, multiple tables for cascade deletes | — | `with_admin()` |

#### Portfolio (`routers/portfolio.py` — 559 lines)

| Feature | Lines | Tables Touched | Access Mode |
|---------|-------|----------------|-------------|
| Get staff portfolio (meetings history, evidence, actions) | 37–315 | `users`, `meetings`, `analyses`, `supervision_uploads` | `with_admin()` / `with_org()` |

#### Organisation (`routers/org.py` — 485 lines)

| Feature | Lines | Tables Touched | Storage Used | Access Mode |
|---------|-------|----------------|-------------|-------------|
| Get/update org settings | 93–345 | `organisations`, `settings` | — | `with_org()` / `with_admin()` |
| Upload org logo | 378–479 | `organisations` | **Emergent Object Storage** (`put_object`) | `with_admin()` |
| Get org logo | 472–479 | — | **Emergent Object Storage** (`get_object`) | `with_admin()` |

#### Super Admin (`routers/super_admin.py` — 358 lines)

| Feature | Lines | Tables Touched | Access Mode |
|---------|-------|----------------|-------------|
| List all orgs | 66–88 | `organisations`, `users` | `with_admin()` |
| Create org | 89–136 | `organisations`, `users` | `with_admin()` |
| Manage users across orgs | 137–253 | `users` | `with_admin()` |
| Delete org (cascade) | 254–358 | All tables (cascade delete by org_id) | `with_admin()` |

#### Schedules (`routers/schedules.py` — 378 lines)

| Feature | Lines | Tables Touched | Access Mode |
|---------|-------|----------------|-------------|
| CRUD schedules | 170–378 | `schedules`, `meeting_types`, `users` | `with_org()` / `with_admin()` |

#### Document Uploads (`routers/doc_uploads.py` — 380 lines)

| Feature | Lines | Tables Touched | Access Mode |
|---------|-------|----------------|-------------|
| Upload/list/manage supervision documents | 74–380 | `supervision_uploads`, `standards_entries`, `standards_documents` | `with_org()` / `with_admin()` |

#### Meeting Prep (`routers/prep.py` — 668 lines)

| Feature | Lines | Tables Touched | Access Mode |
|---------|-------|----------------|-------------|
| Generate/manage prep agendas | 112–668 | `meeting_prep`, `meetings`, `users`, `focus_topics`, `supervision_uploads`, `analyses` | `with_org()` / `with_admin()` |

#### Background Workers

| Feature | File | Lines | Tables Touched | Storage Used | Access Mode |
|---------|------|-------|----------------|-------------|-------------|
| Job queue processing | `utils/job_worker.py` | 24–163 | `jobs`, `meetings`, `audio_files` | — | `with_admin()` |
| Audio transcription pipeline | `utils/transcription_pipeline.py` | 164–428 | `meetings`, `transcripts`, `analyses`, `audio_files`, `jobs`, `standards_entries` | **Supabase Storage** (`get_audio`) | `with_admin()` / `with_org()` |
| Data seeding (standards) | `utils/seed.py` | 188–3891 | `standards_entries`, `meeting_types`, `users` | — | `with_admin()` |
| Standards cache | `utils/standards_cache.py` | 1–108 | `standards_entries` | — | Read via passed connection |
| Rate limiting | `utils/rate_limit.py` | 29–42 | `login_attempts` | — | `with_admin()` |

### 1.6 File/Object Storage

| Storage System | Used By | What For | Files |
|---------------|---------|----------|-------|
| **Supabase Storage** (bucket: `audio-recordings`) | `processing.py:79`, `processing.py:311`, `transcription_pipeline.py:175` | Uploading and downloading meeting audio recordings | `utils/supabase_storage.py` |
| **Supabase Storage** (bucket: `supervision-documents`) | `admin.py:361` | Uploading custom standards documents | `utils/supabase_storage.py` |
| **Emergent Object Storage** | `org.py:454`, `org.py:479` | Uploading and serving organisation logo images | `utils/storage.py` |

---

## Part 2: Supabase Features Used vs. Not Used

| Supabase Feature | Used? | Details |
|-----------------|-------|---------|
| **PostgreSQL Database** | ✅ YES | The entire app's data layer. Direct connection via `asyncpg`. |
| **Storage (File Buckets)** | ✅ YES | Two buckets: `audio-recordings` and `supervision-documents`. |
| **Row Level Security (RLS)** | ✅ YES | Custom implementation using `app_rls_user` role + `app.current_org_id` session variable. Not using Supabase's built-in Auth-based RLS. |
| **Supabase Auth** | ❌ NO | App has its own JWT authentication system (`deps.py`, `routers/auth.py`). |
| **Supabase Realtime** | ❌ NO | Not used. |
| **Supabase Edge Functions** | ❌ NO | Not used. |
| **Supabase Client SDK (JS)** | ❌ NO | Only the Python `supabase` library is used, and only for Storage. Database access is direct via `asyncpg`. |

---

## Part 3: The MongoDB Situation

### Why Does MongoDB Exist?

The Emergent hosting platform uses a "FARM" template (FastAPI + React + MongoDB). This template **automatically creates a MongoDB database** on Emergent's shared Atlas cluster for every deployed app, regardless of whether the app actually uses MongoDB.

### What's in the MongoDB?

The Emergent shared MongoDB (`customer-apps.getrvb.mongodb.net`) has 23 collections with data:

| Collection | Document Count | Most Recent Write |
|-----------|---------------|-------------------|
| `meetings` | At least 5 | 2026-08-01 |
| `users` | At least 5 | 2026-08-01 |
| `transcripts` | At least 3 | 2026-08-01 |
| `analyses` | At least 3 | 2026-08-01 |
| `organisations` | At least 3 | 2026-06-28 |
| `audit_logs` | At least 3 | Unknown (no `created_at` in sample) |
| ... 17 more collections | — | All before 2026-08-01 |

**This is stale data.** The app was originally built on MongoDB (the `DB_SCHEMA.md` file documents the old MongoDB schema, dated Feb 2026). It was migrated to Supabase PostgreSQL, and the last MongoDB write was on 2026-08-01. All activity since then (and there is plenty — active users, meetings being processed daily) goes to PostgreSQL.

### Does Any Code Use MongoDB?

**No.** Here is the evidence:

1. **Zero MongoDB driver imports** in production code. A search for `pymongo`, `motor`, or `MongoClient` across all non-test `.py` files returns **zero results**.
2. **Zero MongoDB log entries** in production pod logs. A search for `mongo|Motor|pymongo` in runtime logs returns **zero results**.
3. **Production startup logs** show only `"PostgreSQL pool created"` — no MongoDB connection.
4. The `MONGO_URL` environment variable exists in the production container (injected by the Emergent deployer pipeline) but **no code reads it**.
5. The `DB_NAME` environment variable (`transcript-vault-2-supervision_db`) exists but **no code reads it**.

The only references to MongoDB in the codebase are:
- **Test files** (e.g., `tests/test_phase34_prep.py`) — old tests from the pre-migration era
- **DB_SCHEMA.md** — old documentation that hasn't been updated to reflect the PostgreSQL migration

### The User's Own MongoDB Atlas

The `backend/.env` file also contains a separate `MONGO_URL` pointing to the user's own Atlas cluster (`supervision2.fkgw5ye.mongodb.net`). This is different from Emergent's shared MongoDB. Neither is used by any production code.

---

## Part 4: Issues Found

### 🔴 Critical Issues

None found. The app is functioning correctly.

### 🟡 Medium Issues

| # | Issue | Where | Impact | Recommendation |
|---|-------|-------|--------|----------------|
| 1 | **Stale documentation** — `memory/DB_SCHEMA.md` documents MongoDB collections but the app now uses PostgreSQL | `/app/memory/DB_SCHEMA.md` | Developers working on the code could be confused about which database is the real one. | Update `DB_SCHEMA.md` to reflect the PostgreSQL schema in `init_db.py`. |
| 2 | **JSONB double-encoding risk** — The RLS role switch causes asyncpg to return JSONB as strings. Multiple data migrations exist to fix past occurrences. | `database.py:68–85`, `init_db.py:697–760` | Data corruption if a developer forgets to add safety guards when reading/writing JSONB. | Consider using a helper function that always parses JSONB safely, applied at the database layer rather than per-router. |
| 3 | **Wasted resources** — The `mongodb_migrate` pipeline step runs on every deployment but serves no purpose. | Deployer pipeline | Minor — adds a few seconds to each deployment. | Not user-actionable. The platform always runs this step for FARM template apps. |
| 4 | **Health check returning 404** — Production logs show `GET /health HTTP/1.0" 404 Not Found` every few seconds. The health endpoint is at `/api/health` but probes check `/health`. | `server.py:150`, K8s probes | Kubernetes liveness/readiness probes are failing, which could eventually restart the pod. The nginx config likely proxies `/health` to the backend where it's mounted at `/api/health`. | Verify the nginx config correctly proxies `/health` to `/api/health`, or add a `/health` route directly. |

### 🟢 Low/Informational Issues

| # | Issue | Where | Impact |
|---|-------|-------|--------|
| 5 | **Missing index on `audio_files.meeting_id`** | `init_db.py` | Minor — audio files are looked up by meeting_id but no index exists. Performance impact is minimal if the table is small. |
| 6 | **Missing index on `meeting_prep.org_id`** | `init_db.py` | Minor — RLS filters by org_id but there's no supporting index. Only matters if there are many prep records. |
| 7 | **`MONGO_URL` and `DB_NAME` cluttering the environment** | `backend/.env`, Deployer secrets | No functional impact but creates confusion. Could be cleaned up. |
| 8 | **Sensitive credentials in `.env` file baked into Docker image** | `backend/.env`, `Dockerfile` | The Supabase credentials (`DATABASE_URL`, `SUPABASE_SERVICE_KEY`) are stored in the `.env` file which is copied into the Docker image. These are NOT in the Emergent secrets store, so they can't be rotated without a code change + redeploy. |

---

## Part 5: Connection & Caching Summary

| Concern | Status | Details |
|---------|--------|---------|
| **Connection Pooling** | ✅ Good | Pool of 2–15 connections via asyncpg. Proper SSL. Statement cache disabled for Supabase pooler compatibility. |
| **Connection Leaks** | ✅ Good | All connections use `async with` context managers that auto-release on completion or error. |
| **Caching** | ✅ Good | Standards data is pre-loaded into memory at startup (`standards_cache.py`). No other caching needed — Supabase connection pooler handles query plan caching. |
| **Redundancy** | ⚠️ Single point | Single Supabase PostgreSQL instance. If Supabase has an outage, the entire app goes down. This is typical for apps at this scale. |
| **Query Performance** | ✅ Good | Proper indexes exist for the main query patterns. The composite index on `meetings(org_id, status, created_at)` covers the dashboard query well. |
| **Schema Migrations** | ✅ Good (idempotent) | All schema changes use `IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`. Safe to re-run. |

---

## Part 6: Environment Variable Map

### Variables the App Actually Uses (from `.env` file baked into Docker image)

| Variable | What It Connects To | Used By |
|----------|-------------------|---------|
| `DATABASE_URL` | Supabase PostgreSQL | `database.py`, `init_db.py` |
| `SUPABASE_URL` | Supabase API (for Storage) | `utils/supabase_storage.py` |
| `SUPABASE_SERVICE_KEY` | Supabase service role auth | `utils/supabase_storage.py` |
| `JWT_SECRET` | App's own JWT signing | `deps.py`, `routers/auth.py` |
| `EMERGENT_LLM_KEY` | Emergent Object Storage + AI | `utils/storage.py`, `utils/ai.py` |
| `OPENAI_API_KEY` | OpenAI API | `utils/ai.py` |
| `ASSEMBLYAI_API_KEY` | Audio transcription service | `utils/transcription_pipeline.py` |
| `RESEND_API_KEY` | Email sending | `routers/auth.py` |
| `GCP_SERVICE_ACCOUNT_JSON` | Google Vertex AI (Gemini) | `utils/ai.py` |
| `LOKI_URL/USER/TOKEN` | Log shipping to Grafana Loki | `loki_logging.py` |

### Variables That Exist But Are NOT Used by Code

| Variable | Source | Why It Exists | Is It Needed? |
|----------|--------|--------------|---------------|
| `MONGO_URL` (Emergent shared) | Deployer pipeline auto-injection | Platform always creates this for FARM apps | ❌ No |
| `MONGO_URL` (user's Atlas) | `backend/.env` file | Left over from the MongoDB era | ❌ No |
| `DB_NAME` | Deployer pipeline auto-injection | Platform always creates this for FARM apps | ❌ No |
