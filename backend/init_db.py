"""
Create all PostgreSQL tables and RLS policies.
Run once on fresh database, safe to re-run (idempotent).
"""
import asyncpg
import asyncio
import json
import os
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

SCHEMA_SQL = """
-- ── RLS enforcer role ─────────────────────────────────────────────────────────
-- The backend connects as postgres (superuser, bypasses RLS).
-- with_org() does SET LOCAL ROLE app_rls_user so policies are enforced.
-- with_admin() stays as postgres (seed, super-admin, job worker).

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rls_user') THEN
    CREATE ROLE app_rls_user NOLOGIN;
  END IF;
END $$;

-- ── Core tables ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS organisations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT UNIQUE,
    status TEXT NOT NULL DEFAULT 'active',
    branding JSONB NOT NULL DEFAULT '{}',
    created_at TEXT,
    updated_at TEXT
);
-- RLS: with_org() connections can only see their own org row.
-- with_admin() bypasses via SET LOCAL row_security = off.
-- NOTE: the actual policy (DROP+CREATE POLICY) for every RLS-enabled table is
-- defined in the "Phase 2 id/FK data-type migration" block near the end of
-- this script, not here — it has to run AFTER the id-column type migration
-- (Postgres refuses to change a column's type while a policy depends on it),
-- so all 21 policies are dropped/recreated together in that one atomic block.
ALTER TABLE organisations ENABLE ROW LEVEL SECURITY;
ALTER TABLE organisations FORCE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'attendee',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    team_id TEXT,
    setting_id TEXT,
    must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
    password_changed_at TEXT,
    created_at TEXT,
    updated_at TEXT,
    mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    mfa_code TEXT,
    mfa_code_expires_at TEXT,
    mfa_code_attempts INTEGER NOT NULL DEFAULT 0
);
-- RLS: each org can only see its own users; auth ops (login, invite) use with_admin()
-- Policy defined in the "Phase 2" block near the end of this script.
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS meetings (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    date TEXT,
    location TEXT,
    meeting_type TEXT DEFAULT 'supervision',
    created_by TEXT,
    created_by_name TEXT,
    sign_off_manager_id TEXT,
    sign_off_manager_name TEXT,
    attendees JSONB NOT NULL DEFAULT '[]',
    team_id TEXT,
    setting_id TEXT,
    schedule_id TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    recording_events JSONB NOT NULL DEFAULT '[]',
    paused_periods JSONB NOT NULL DEFAULT '[]',
    total_paused_duration_seconds INTEGER NOT NULL DEFAULT 0,
    recording_notice_shown_at TEXT,
    audio_file_id TEXT,
    transcript_id TEXT,
    analysis_id TEXT,
    sign_off_record JSONB,
    pii_redactions JSONB NOT NULL DEFAULT '[]',
    pii_review_status TEXT,
    shared_with JSONB NOT NULL DEFAULT '[]',
    audio_deletion_status TEXT NOT NULL DEFAULT 'none',
    audio_grace_period_started_at TEXT,
    audio_deleted_at TEXT,
    transcript_has_warnings BOOLEAN NOT NULL DEFAULT FALSE,
    diarize_status TEXT,
    reopen_record JSONB,
    rescan_status TEXT,
    retranscribed_at TEXT,
    created_at TEXT,
    updated_at TEXT
);
ALTER TABLE meetings ENABLE ROW LEVEL SECURITY;
ALTER TABLE meetings FORCE ROW LEVEL SECURITY;
-- Policy defined in the "Phase 2" block near the end of this script.

CREATE TABLE IF NOT EXISTS transcripts (
    id TEXT PRIMARY KEY,
    meeting_id TEXT,
    org_id TEXT,
    text TEXT NOT NULL DEFAULT '',
    speaker_text TEXT,
    safety_warnings JSONB NOT NULL DEFAULT '[]',
    retranscribed_at TEXT,
    created_at TEXT
);
ALTER TABLE transcripts ENABLE ROW LEVEL SECURITY;
ALTER TABLE transcripts FORCE ROW LEVEL SECURITY;
-- Policy defined in the "Phase 2" block near the end of this script.

CREATE TABLE IF NOT EXISTS analyses (
    id TEXT PRIMARY KEY,
    meeting_id TEXT,
    org_id TEXT,
    summary TEXT NOT NULL DEFAULT '',
    edited_summary TEXT,
    achievements JSONB NOT NULL DEFAULT '[]',
    actions JSONB NOT NULL DEFAULT '[]',
    learning_needs JSONB NOT NULL DEFAULT '[]',
    risks JSONB NOT NULL DEFAULT '[]',
    cqc_mappings JSONB NOT NULL DEFAULT '[]',
    care_cert_mappings JSONB NOT NULL DEFAULT '[]',
    custom_mappings JSONB NOT NULL DEFAULT '[]',
    created_at TEXT,
    last_edited_at TEXT
);
ALTER TABLE analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE analyses FORCE ROW LEVEL SECURITY;
-- Policy defined in the "Phase 2" block near the end of this script.

CREATE TABLE IF NOT EXISTS audio_files (
    id TEXT PRIMARY KEY,
    meeting_id TEXT,
    org_id TEXT,
    storage_path TEXT,
    original_filename TEXT,
    content_type TEXT,
    size_bytes INTEGER,
    upload_status TEXT DEFAULT 'uploaded',
    processing_status TEXT DEFAULT 'pending',
    deletion_status TEXT DEFAULT 'active',
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at TEXT,
    created_at TEXT
);
ALTER TABLE audio_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE audio_files FORCE ROW LEVEL SECURITY;
-- Policy defined in the "Phase 2" block near the end of this script.

CREATE TABLE IF NOT EXISTS review_edits (
    id TEXT PRIMARY KEY,
    meeting_id TEXT,
    org_id TEXT,
    action TEXT,
    detail TEXT,
    user_id TEXT,
    user_name TEXT,
    timestamp TEXT
);
ALTER TABLE review_edits ENABLE ROW LEVEL SECURITY;
ALTER TABLE review_edits FORCE ROW LEVEL SECURITY;
-- Policy defined in the "Phase 2" block near the end of this script.

CREATE TABLE IF NOT EXISTS reviewer_comments (
    id TEXT PRIMARY KEY,
    meeting_id TEXT,
    org_id TEXT,
    text TEXT,
    user_id TEXT,
    user_name TEXT,
    role TEXT,
    created_at TEXT
);
ALTER TABLE reviewer_comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE reviewer_comments FORCE ROW LEVEL SECURITY;
-- Policy defined in the "Phase 2" block near the end of this script.

-- Standards entries: system CQC/CareCert (org_id IS NULL) are visible to all orgs.
-- Custom org standards are scoped to the owning org.
-- System records are only written by seed/admin (with_admin bypasses RLS).
CREATE TABLE IF NOT EXISTS standards_entries (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    type TEXT,
    reference TEXT,
    name TEXT,
    description TEXT,
    keywords JSONB NOT NULL DEFAULT '[]',
    sub_outcomes JSONB NOT NULL DEFAULT '[]',
    key_questions JSONB NOT NULL DEFAULT '[]',
    source TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_system BOOLEAN NOT NULL DEFAULT FALSE,
    quality_statement BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TEXT,
    created_by TEXT
);
ALTER TABLE standards_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE standards_entries FORCE ROW LEVEL SECURITY;
-- Policy (with its "system-wide rows visible to all orgs" clause) defined in
-- the "Phase 2" block near the end of this script.

-- Standards documents (org-uploaded custom docs)
CREATE TABLE IF NOT EXISTS standards_documents (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    filename TEXT,
    label TEXT,
    storage_path TEXT,
    content_type TEXT,
    size_bytes INTEGER,
    parse_status TEXT DEFAULT 'parsing',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    extracted_text TEXT,
    document_summary TEXT,
    extracted_criteria JSONB NOT NULL DEFAULT '[]',
    criteria_count INTEGER DEFAULT 0,
    parse_error TEXT,
    parsed_at TEXT,
    uploaded_by TEXT,
    uploaded_by_name TEXT,
    created_at TEXT
);
ALTER TABLE standards_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE standards_documents FORCE ROW LEVEL SECURITY;
-- Policy defined in the "Phase 2" block near the end of this script.

-- Brute-force protection — no RLS
CREATE TABLE IF NOT EXISTS login_attempts (
    identifier TEXT PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    updated_at TEXT
);

-- Password reset — no RLS
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    token TEXT UNIQUE,
    email TEXT,
    expires_at TEXT,
    used BOOLEAN NOT NULL DEFAULT FALSE
);

-- Invitations — RLS: org can only see its own invitations
CREATE TABLE IF NOT EXISTS invitations (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    user_id TEXT,
    token TEXT UNIQUE,
    expires_at TEXT,
    used_at TEXT,
    created_at TEXT
);
ALTER TABLE invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE invitations FORCE ROW LEVEL SECURITY;
-- Policy defined in the "Phase 2" block near the end of this script.

-- Settings key-value — RLS: org can only see its own settings
CREATE TABLE IF NOT EXISTS settings (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    data JSONB NOT NULL DEFAULT '{}'
);
ALTER TABLE settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE settings FORCE ROW LEVEL SECURITY;
-- NOTE: unlike every other table, settings.id/org_id are deliberately NEVER
-- migrated to UUID in Phase 2 below — this table uses composite string keys
-- (e.g. "supervision_template:{org_id}") as its primary key, not real UUIDs
-- (admin.py get_template/save_template, review.py, transcription_pipeline.py).
-- So this policy is static (plain TEXT comparison), not part of the dynamic
-- rebuild the other 20 policies get.
DROP POLICY IF EXISTS settings_rls ON settings;
CREATE POLICY settings_rls ON settings FOR ALL
    USING      (org_id = (SELECT current_setting('app.current_org_id', TRUE)))
    WITH CHECK (org_id = (SELECT current_setting('app.current_org_id', TRUE)));

-- Background job queue — no RLS (worker processes all orgs)
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    meeting_id TEXT,
    audio_path TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT,
    updated_at TEXT
);

-- Audit logs
CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    meeting_id TEXT,
    org_id TEXT,
    action TEXT,
    detail TEXT,
    user_id TEXT,
    user_name TEXT,
    timestamp TEXT
);
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;
-- Policy defined in the "Phase 2" block near the end of this script.

-- Org settings (teams hierarchy)
CREATE TABLE IF NOT EXISTS org_settings (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    name TEXT,
    settings JSONB NOT NULL DEFAULT '[]',
    created_at TEXT,
    updated_at TEXT
);
ALTER TABLE org_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_settings FORCE ROW LEVEL SECURITY;
-- Policy defined in the "Phase 2" block near the end of this script.

CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    setting_id TEXT,
    name TEXT,
    description TEXT,
    supervisor_user_id TEXT,
    members JSONB NOT NULL DEFAULT '[]',
    created_at TEXT
);
ALTER TABLE teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE teams FORCE ROW LEVEL SECURITY;
-- Policy defined in the "Phase 2" block near the end of this script.

CREATE TABLE IF NOT EXISTS schedules (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    staff_user_id TEXT,
    meeting_type_id TEXT,
    frequency TEXT,
    start_date TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by TEXT,
    created_at TEXT
);
ALTER TABLE schedules ENABLE ROW LEVEL SECURITY;
ALTER TABLE schedules FORCE ROW LEVEL SECURITY;
-- Policy defined in the "Phase 2" block near the end of this script.

CREATE TABLE IF NOT EXISTS meeting_types (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    name TEXT,
    default_frequency TEXT,
    color TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TEXT
);
ALTER TABLE meeting_types ENABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_types FORCE ROW LEVEL SECURITY;
-- Policy defined in the "Phase 2" block near the end of this script.

CREATE TABLE IF NOT EXISTS meeting_prep (
    id TEXT PRIMARY KEY,
    meeting_id TEXT UNIQUE,
    org_id TEXT,
    sections JSONB NOT NULL DEFAULT '[]',
    focus_topic TEXT,
    shared_with_attendees BOOLEAN NOT NULL DEFAULT FALSE,
    generated_at TEXT,
    coverage_results JSONB NOT NULL DEFAULT '{}',
    coverage_checked_at TEXT,
    created_at TEXT,
    updated_at TEXT
);
ALTER TABLE meeting_prep ENABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_prep FORCE ROW LEVEL SECURITY;
-- Policy defined in the "Phase 2" block near the end of this script.

CREATE TABLE IF NOT EXISTS focus_topics (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    text TEXT,
    is_current BOOLEAN NOT NULL DEFAULT FALSE,
    active_month TEXT,
    created_by TEXT,
    created_at TEXT
);
ALTER TABLE focus_topics ENABLE ROW LEVEL SECURITY;
ALTER TABLE focus_topics FORCE ROW LEVEL SECURITY;
-- Policy defined in the "Phase 2" block near the end of this script.

CREATE TABLE IF NOT EXISTS supervision_uploads (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    uploader_id TEXT,
    uploader_name TEXT,
    staff_id TEXT,
    staff_name TEXT,
    filename TEXT,
    label TEXT,
    doc_type TEXT,
    meeting_date TEXT,
    file_ext TEXT,
    size_bytes INTEGER,
    status TEXT NOT NULL DEFAULT 'processing',
    full_text TEXT,
    cqc_mappings JSONB NOT NULL DEFAULT '[]',
    care_cert_mappings JSONB NOT NULL DEFAULT '[]',
    custom_mappings JSONB NOT NULL DEFAULT '[]',
    error TEXT,
    processed_at TEXT,
    created_at TEXT
);
ALTER TABLE supervision_uploads ENABLE ROW LEVEL SECURITY;
ALTER TABLE supervision_uploads FORCE ROW LEVEL SECURITY;
-- Policy defined in the "Phase 2" block near the end of this script.

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_meetings_created_at ON meetings(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_users_org_id ON users(org_id);
CREATE INDEX IF NOT EXISTS idx_transcripts_meeting_id ON transcripts(meeting_id);
CREATE INDEX IF NOT EXISTS idx_analyses_meeting_id ON analyses(meeting_id);
CREATE INDEX IF NOT EXISTS idx_audio_files_meeting_id ON audio_files(meeting_id);
CREATE INDEX IF NOT EXISTS idx_review_edits_meeting_id ON review_edits(meeting_id);
CREATE INDEX IF NOT EXISTS idx_reviewer_comments_meeting_id ON reviewer_comments(meeting_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_meeting_id ON audit_logs(meeting_id);
CREATE INDEX IF NOT EXISTS idx_standards_type ON standards_entries(type, reference);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, attempts, created_at);
CREATE INDEX IF NOT EXISTS idx_schedules_org_id ON schedules(org_id);
CREATE INDEX IF NOT EXISTS idx_meeting_types_org_id ON meeting_types(org_id);
CREATE INDEX IF NOT EXISTS idx_supervision_uploads_org_id ON supervision_uploads(org_id);
CREATE INDEX IF NOT EXISTS idx_supervision_uploads_staff_id ON supervision_uploads(staff_id);
CREATE INDEX IF NOT EXISTS idx_teams_org_id ON teams(org_id);
CREATE INDEX IF NOT EXISTS idx_teams_setting_id ON teams(setting_id);
CREATE INDEX IF NOT EXISTS idx_org_settings_org_id ON org_settings(org_id);
CREATE INDEX IF NOT EXISTS idx_focus_topics_org_id ON focus_topics(org_id);
CREATE INDEX IF NOT EXISTS idx_standards_documents_org_id ON standards_documents(org_id);
CREATE INDEX IF NOT EXISTS idx_users_team_id ON users(team_id);
CREATE INDEX IF NOT EXISTS idx_users_setting_id ON users(setting_id);

-- ── Schema patches (idempotent — safe to run on existing database) ─────────────

-- Jurisdiction support: single deployment serves England / Wales / Scotland / Northern Ireland
ALTER TABLE organisations ADD COLUMN IF NOT EXISTS jurisdiction TEXT NOT NULL DEFAULT 'england';
ALTER TABLE standards_entries ADD COLUMN IF NOT EXISTS jurisdiction TEXT NOT NULL DEFAULT 'england';

-- Northern Ireland service type: 'residential' | 'domiciliary' (NULL = not applicable / NI shared)
ALTER TABLE organisations ADD COLUMN IF NOT EXISTS service_type TEXT;
ALTER TABLE standards_entries ADD COLUMN IF NOT EXISTS service_type TEXT;

ALTER TABLE meeting_prep ADD COLUMN IF NOT EXISTS gen_status TEXT DEFAULT 'idle';
ALTER TABLE meeting_prep ADD COLUMN IF NOT EXISTS included_source_ids JSONB NOT NULL DEFAULT '[]';
ALTER TABLE meeting_prep ADD COLUMN IF NOT EXISTS created_by TEXT;
ALTER TABLE meeting_prep ADD COLUMN IF NOT EXISTS shared_at TEXT;
ALTER TABLE meeting_prep ADD COLUMN IF NOT EXISTS coverage_results JSONB NOT NULL DEFAULT '{}';
ALTER TABLE meeting_prep ADD COLUMN IF NOT EXISTS coverage_checked_at TEXT;
ALTER TABLE meeting_prep ADD COLUMN IF NOT EXISTS shared_with_attendees BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE supervision_uploads ADD COLUMN IF NOT EXISTS full_text TEXT;
ALTER TABLE supervision_uploads ADD COLUMN IF NOT EXISTS doc_type TEXT DEFAULT 'other';
ALTER TABLE supervision_uploads ADD COLUMN IF NOT EXISTS meeting_date TEXT;
ALTER TABLE supervision_uploads ADD COLUMN IF NOT EXISTS label TEXT;

ALTER TABLE standards_documents ADD COLUMN IF NOT EXISTS extracted_text TEXT;
ALTER TABLE standards_documents ADD COLUMN IF NOT EXISTS parse_status TEXT DEFAULT 'parsing';
ALTER TABLE standards_documents ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;

ALTER TABLE focus_topics ADD COLUMN IF NOT EXISTS active_month TEXT;
ALTER TABLE focus_topics ADD COLUMN IF NOT EXISTS created_by TEXT;

ALTER TABLE org_settings ADD COLUMN IF NOT EXISTS manager_user_id TEXT;

-- Duplicate of the auto-created UNIQUE constraint index (users_email_key) — drop it.
-- users_email_key alone already serves every email lookup/uniqueness check.
DROP INDEX IF EXISTS public.idx_users_email;

ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS speaker_text_backup TEXT;
ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS speaker_text_backup_at TEXT;
ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS speaker_text_backup_by TEXT;
ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS speaker_text_edited_by_name TEXT;
ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS speaker_text_edited_at TEXT;
ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS speaker_colors JSONB NOT NULL DEFAULT '{}';
ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS updated_at TEXT;

ALTER TABLE meetings ADD COLUMN IF NOT EXISTS recording_events JSONB NOT NULL DEFAULT '[]';
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS paused_periods JSONB NOT NULL DEFAULT '[]';
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS total_paused_duration_seconds INTEGER NOT NULL DEFAULT 0;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS recording_notice_shown_at TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS sign_off_record JSONB;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS pii_redactions JSONB NOT NULL DEFAULT '[]';
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS pii_review_status TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS shared_with JSONB NOT NULL DEFAULT '[]';
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS audio_deletion_status TEXT NOT NULL DEFAULT 'none';
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS audio_grace_period_started_at TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS audio_deleted_at TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS transcript_has_warnings BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS diarize_status TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS reopen_record JSONB;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS rescan_status TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS retranscribed_at TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS team_id TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS setting_id TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS schedule_id TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS meeting_type TEXT DEFAULT 'supervision';
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS meeting_type_id TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS transcript_id TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS analysis_id TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS created_by_name TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS audio_file_id TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending';
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS date TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS location TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS updated_at TEXT;


ALTER TABLE analyses ADD COLUMN IF NOT EXISTS last_edited_by TEXT;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS rescanned_at TEXT;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS rescanned_by_name TEXT;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS edited_summary TEXT;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS last_edited_at TEXT;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS custom_mappings JSONB NOT NULL DEFAULT '[]';
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS pii_redactions JSONB NOT NULL DEFAULT '[]';
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS achievements JSONB NOT NULL DEFAULT '[]';
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS learning_needs JSONB NOT NULL DEFAULT '[]';

-- Evidence feedback — training data log; RLS scopes writes/reads to the owning org.
-- Super-admin access is still available via with_admin() which sets row_security=off.
CREATE TABLE IF NOT EXISTS evidence_feedback (
    id TEXT PRIMARY KEY,
    meeting_id TEXT,
    org_id TEXT,
    user_id TEXT,
    user_name TEXT,
    evidence_item_id TEXT,
    evidence_type TEXT,
    standard_ref TEXT,
    standard_name TEXT,
    ai_confidence TEXT,
    manager_action TEXT,
    evidence_summary TEXT,
    edited_summary TEXT,
    transcript_excerpt TEXT,
    meeting_jurisdiction TEXT,
    timestamp TEXT
);
ALTER TABLE evidence_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_feedback FORCE ROW LEVEL SECURITY;
-- Policy defined in the "Phase 2" block near the end of this script.

ALTER TABLE meetings ADD COLUMN IF NOT EXISTS pii_reviewed_at TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS pii_reviewed_by TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS pii_reviewed_by_name TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS pii_skipped BOOLEAN DEFAULT FALSE;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS reopen_requested BOOLEAN DEFAULT FALSE;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS reopen_requested_by TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS reopen_requested_by_name TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS reopen_requested_at TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS reopen_reason TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS reopen_approved_by TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS reopen_approved_by_name TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS reopen_approved_at TEXT;

-- ── Grants for app_rls_user ────────────────────────────────────────────────────
-- app_rls_user is the limited role with_org() switches to, making RLS policies
-- actually fire even though the connection pool uses the postgres superuser.

GRANT USAGE ON SCHEMA public TO app_rls_user;

GRANT SELECT, INSERT, UPDATE, DELETE ON
    meetings, transcripts, analyses, audio_files, review_edits,
    reviewer_comments, standards_entries, standards_documents,
    audit_logs, org_settings, teams, schedules, meeting_types,
    meeting_prep, focus_topics, supervision_uploads,
    users, organisations, invitations, settings, jobs,
    login_attempts, password_reset_tokens, evidence_feedback
TO app_rls_user;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_rls_user;

-- The connection pool user must be a MEMBER of app_rls_user to be allowed
-- to SET LOCAL ROLE app_rls_user. On Supabase (and other managed Postgres),
-- the application user is not a true superuser so this grant is required.
GRANT app_rls_user TO CURRENT_USER;

-- Automatically grant privileges on tables created in the future
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rls_user;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO app_rls_user;

-- Composite covering index for the dashboard meeting list
-- (org_id filter + status filter + created_at sort in one index scan)
CREATE INDEX IF NOT EXISTS idx_meetings_org_status_date
    ON meetings(org_id, status, created_at DESC);

-- Drop single-column indexes now covered by the composite above.
-- idx_meetings_org_id  → leftmost column of idx_meetings_org_status_date
-- idx_meetings_status  → with RLS, every query has org_id; standalone status index unused
DROP INDEX IF EXISTS idx_meetings_org_id;
DROP INDEX IF EXISTS idx_meetings_status;

-- Staff-scoped schedule queries
-- idx_schedules_staff_user_id was previously dropped here because SELECT
-- queries always filter by org_id first (via RLS), so a standalone index
-- was never chosen by the planner for that access pattern. It's since been
-- re-added below in the "FK-supporting indexes" section for a different
-- reason: without it, deleting a user forces a full table scan of schedules
-- to find rows to SET NULL via the fk_schedules_staff_user_id FK constraint.

-- Audit trail queries filter and sort by org + time
-- NOTE: idx_audit_logs_org_date dropped — the only SELECT on audit_logs filters
-- by meeting_id (covered by idx_audit_logs_meeting_id). The composite
-- (org_id, timestamp) can be re-added if an org-level audit page is built.
DROP INDEX IF EXISTS idx_audit_logs_org_date;

-- refresh_tokens table was never populated (refresh is purely JWT-based);
-- drop it on all environments so the dead table no longer appears in audits.
DROP TABLE IF EXISTS refresh_tokens;

-- ── Foreign key constraints ─────────────────────────────────────────────────────
-- The schema previously had zero formal relationships — every "belongs to" link
-- (transcript->meeting, team->org, user->team, etc.) was only ever enforced by
-- application code. That's the root cause of orphaned rows appearing over time
-- (e.g. audit_logs entries outliving their meeting). These constraints make
-- Postgres enforce the same relationships the app already assumes, matching the
-- app's existing manual-cascade/unassign behavior exactly:
--   • CASCADE on org_id / meeting_id chains — app already bulk-deletes these
--     children when the meeting/org is deleted (meetings.py delete_meeting()).
--   • SET NULL on soft/ownership references (team_id, setting_id, supervisor,
--     manager) — app already manually nulls these out when the parent is
--     deleted (org.py delete_team()/delete_setting()).
-- Postgres doesn't support "ADD CONSTRAINT IF NOT EXISTS", so each is wrapped in
-- a DO block that swallows the "already exists" error, matching the idempotent
-- pattern used for app_rls_user above.
--
-- Deliberately NOT added (documented, not oversights):
--   • jobs.meeting_id — app intentionally keeps job history after a meeting is
--     deleted (not in delete_meeting()'s cascade list); adding a FK here would
--     change that behavior. Also has 1 pre-existing orphan row.
--   • invitations.user_id — has 1 pre-existing orphan row; needs a product
--     decision on cleanup before it can be constrained.
--   • meetings.transcript_id / analysis_id / audio_file_id — these are the
--     reverse/denormalized pointers of transcripts.meeting_id etc. (already
--     covered in the correct "child belongs to parent" direction below);
--     constraining both directions risks a circular-FK insert-order issue.
--   • meetings.created_by / sign_off_manager_id — intentional historical
--     snapshots (created_by_name / sign_off_manager_name persist even after the
--     referenced user account is deleted); sign_off_manager_id already has 4
--     such orphans today, confirming this is by design, not a bug.

-- One-time cleanup: 3 audit_logs rows already outlived their meeting (the exact
-- symptom described above) — finish the cascade delete that should have already
-- happened, so the new CASCADE constraint below can be added.
DELETE FROM audit_logs WHERE meeting_id IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM meetings m WHERE m.id = audit_logs.meeting_id);

DO $$ BEGIN ALTER TABLE users ADD CONSTRAINT fk_users_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE users ADD CONSTRAINT fk_users_team_id FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE users ADD CONSTRAINT fk_users_setting_id FOREIGN KEY (setting_id) REFERENCES org_settings(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE meetings ADD CONSTRAINT fk_meetings_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE meetings ADD CONSTRAINT fk_meetings_team_id FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE meetings ADD CONSTRAINT fk_meetings_setting_id FOREIGN KEY (setting_id) REFERENCES org_settings(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE meetings ADD CONSTRAINT fk_meetings_schedule_id FOREIGN KEY (schedule_id) REFERENCES schedules(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE transcripts ADD CONSTRAINT fk_transcripts_meeting_id FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE transcripts ADD CONSTRAINT fk_transcripts_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE analyses ADD CONSTRAINT fk_analyses_meeting_id FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE analyses ADD CONSTRAINT fk_analyses_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE audio_files ADD CONSTRAINT fk_audio_files_meeting_id FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE audio_files ADD CONSTRAINT fk_audio_files_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE review_edits ADD CONSTRAINT fk_review_edits_meeting_id FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE review_edits ADD CONSTRAINT fk_review_edits_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE reviewer_comments ADD CONSTRAINT fk_reviewer_comments_meeting_id FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE reviewer_comments ADD CONSTRAINT fk_reviewer_comments_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE audit_logs ADD CONSTRAINT fk_audit_logs_meeting_id FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE audit_logs ADD CONSTRAINT fk_audit_logs_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE org_settings ADD CONSTRAINT fk_org_settings_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE org_settings ADD CONSTRAINT fk_org_settings_manager_user_id FOREIGN KEY (manager_user_id) REFERENCES users(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE teams ADD CONSTRAINT fk_teams_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE teams ADD CONSTRAINT fk_teams_setting_id FOREIGN KEY (setting_id) REFERENCES org_settings(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE teams ADD CONSTRAINT fk_teams_supervisor_user_id FOREIGN KEY (supervisor_user_id) REFERENCES users(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE standards_entries ADD CONSTRAINT fk_standards_entries_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE standards_documents ADD CONSTRAINT fk_standards_documents_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE invitations ADD CONSTRAINT fk_invitations_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
-- NOTE: no FK from settings.org_id -> organisations(id): settings.org_id is
-- deliberately kept TEXT forever (see Phase 2 comments below — settings.id
-- is a composite string key, not a real relational row), so it can never
-- have a type-matching FK to organisations(id), which is UUID.
DO $$ BEGIN ALTER TABLE meeting_types ADD CONSTRAINT fk_meeting_types_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE focus_topics ADD CONSTRAINT fk_focus_topics_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE meeting_prep ADD CONSTRAINT fk_meeting_prep_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE meeting_prep ADD CONSTRAINT fk_meeting_prep_meeting_id FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE schedules ADD CONSTRAINT fk_schedules_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE schedules ADD CONSTRAINT fk_schedules_staff_user_id FOREIGN KEY (staff_user_id) REFERENCES users(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE schedules ADD CONSTRAINT fk_schedules_meeting_type_id FOREIGN KEY (meeting_type_id) REFERENCES meeting_types(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE supervision_uploads ADD CONSTRAINT fk_supervision_uploads_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE supervision_uploads ADD CONSTRAINT fk_supervision_uploads_staff_id FOREIGN KEY (staff_id) REFERENCES users(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE evidence_feedback ADD CONSTRAINT fk_evidence_feedback_meeting_id FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE evidence_feedback ADD CONSTRAINT fk_evidence_feedback_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

-- ── FK-supporting indexes ────────────────────────────────────────────────────
-- Every FK column above needs a supporting index so that deleting/updating the
-- REFERENCED row (e.g. deleting an org, a user, a meeting) doesn't force a full
-- table scan of the referencing table to find rows to CASCADE/SET NULL. This is
-- a distinct concern from the composite query-pattern indexes elsewhere in this
-- file (e.g. idx_meetings_org_status_date already covers meetings.org_id for
-- SELECT filtering) — some FK columns had no index at all for either purpose.
CREATE INDEX IF NOT EXISTS idx_analyses_org_id ON analyses(org_id);
CREATE INDEX IF NOT EXISTS idx_audio_files_org_id ON audio_files(org_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_org_id ON audit_logs(org_id);
CREATE INDEX IF NOT EXISTS idx_evidence_feedback_org_id ON evidence_feedback(org_id);
CREATE INDEX IF NOT EXISTS idx_evidence_feedback_meeting_id ON evidence_feedback(meeting_id);
CREATE INDEX IF NOT EXISTS idx_invitations_org_id ON invitations(org_id);
CREATE INDEX IF NOT EXISTS idx_meeting_prep_org_id ON meeting_prep(org_id);
CREATE INDEX IF NOT EXISTS idx_meetings_setting_id ON meetings(setting_id);
CREATE INDEX IF NOT EXISTS idx_meetings_team_id ON meetings(team_id);
CREATE INDEX IF NOT EXISTS idx_meetings_schedule_id ON meetings(schedule_id);
CREATE INDEX IF NOT EXISTS idx_org_settings_manager_user_id ON org_settings(manager_user_id);
CREATE INDEX IF NOT EXISTS idx_review_edits_org_id ON review_edits(org_id);
CREATE INDEX IF NOT EXISTS idx_reviewer_comments_org_id ON reviewer_comments(org_id);
CREATE INDEX IF NOT EXISTS idx_schedules_meeting_type_id ON schedules(meeting_type_id);
CREATE INDEX IF NOT EXISTS idx_schedules_staff_user_id ON schedules(staff_user_id);
CREATE INDEX IF NOT EXISTS idx_standards_entries_org_id ON standards_entries(org_id);
CREATE INDEX IF NOT EXISTS idx_teams_supervisor_user_id ON teams(supervisor_user_id);
CREATE INDEX IF NOT EXISTS idx_transcripts_org_id ON transcripts(org_id);

-- ── Phase 1 data-type migration: TEXT -> TIMESTAMPTZ for true date/time columns ──
-- Scoped to the columns that always hold a full ISO-8601 UTC timestamp written via
-- datetime.now(timezone.utc).isoformat() (database.py registers a text-format
-- TIMESTAMPTZ/TIMESTAMP codec so those call sites keep working unchanged — see
-- _encode_timestamp/_decode_timestamp). Deliberately EXCLUDED, left as TEXT
-- (different semantics, not full timestamps): meetings.date (plain user-supplied
-- date), schedules.start_date (code comment already says "keep as str — DB column
-- is text"), supervision_uploads.meeting_date (date-only), focus_topics.
-- active_month ("YYYY-MM" only).
-- Idempotent: skips columns that are already TIMESTAMPTZ or don't exist (safe on
-- a fresh DB or one already migrated). Malformed values (don't look like
-- YYYY-MM-DD[ T]HH:MI:SS) are nulled out first — logged via RAISE WARNING — so the
-- ALTER can succeed; if a column still can't be cast for any other reason it's
-- left as TEXT with a loud warning for manual inspection rather than aborting the
-- whole migration.
DO $$
DECLARE
    migrations TEXT[][] := ARRAY[
        ARRAY['organisations','created_at'], ARRAY['organisations','updated_at'],
        ARRAY['users','password_changed_at'], ARRAY['users','created_at'], ARRAY['users','updated_at'], ARRAY['users','mfa_code_expires_at'],
        ARRAY['meetings','recording_notice_shown_at'], ARRAY['meetings','audio_grace_period_started_at'], ARRAY['meetings','audio_deleted_at'],
        ARRAY['meetings','retranscribed_at'], ARRAY['meetings','created_at'], ARRAY['meetings','updated_at'],
        ARRAY['meetings','pii_reviewed_at'], ARRAY['meetings','reopen_requested_at'], ARRAY['meetings','reopen_approved_at'],
        ARRAY['transcripts','retranscribed_at'], ARRAY['transcripts','created_at'], ARRAY['transcripts','updated_at'],
        ARRAY['transcripts','speaker_text_backup_at'], ARRAY['transcripts','speaker_text_edited_at'],
        ARRAY['analyses','created_at'], ARRAY['analyses','last_edited_at'], ARRAY['analyses','rescanned_at'],
        ARRAY['audio_files','deleted_at'], ARRAY['audio_files','created_at'],
        ARRAY['review_edits','timestamp'], ARRAY['reviewer_comments','created_at'],
        ARRAY['standards_entries','created_at'], ARRAY['standards_documents','parsed_at'], ARRAY['standards_documents','created_at'],
        ARRAY['login_attempts','locked_until'], ARRAY['login_attempts','updated_at'],
        ARRAY['password_reset_tokens','expires_at'],
        ARRAY['invitations','expires_at'], ARRAY['invitations','used_at'], ARRAY['invitations','created_at'],
        ARRAY['jobs','created_at'], ARRAY['jobs','updated_at'],
        ARRAY['audit_logs','timestamp'],
        ARRAY['org_settings','created_at'], ARRAY['org_settings','updated_at'],
        ARRAY['teams','created_at'], ARRAY['schedules','created_at'], ARRAY['meeting_types','created_at'],
        ARRAY['meeting_prep','generated_at'], ARRAY['meeting_prep','coverage_checked_at'], ARRAY['meeting_prep','shared_at'],
        ARRAY['meeting_prep','created_at'], ARRAY['meeting_prep','updated_at'],
        ARRAY['supervision_uploads','processed_at'], ARRAY['supervision_uploads','created_at'],
        ARRAY['evidence_feedback','timestamp']
    ];
    m TEXT[];
    tbl TEXT;
    col TEXT;
    col_type TEXT;
    bad_count INT;
BEGIN
    FOREACH m SLICE 1 IN ARRAY migrations LOOP
        tbl := m[1];
        col := m[2];
        SELECT data_type INTO col_type FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = tbl AND column_name = col;
        IF col_type IS NULL OR col_type = 'timestamp with time zone' THEN
            CONTINUE;
        END IF;
        EXECUTE format(
            'UPDATE %I SET %I = NULL WHERE %I IS NOT NULL AND %I !~ %L',
            tbl, col, col, col, '^[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}'
        );
        GET DIAGNOSTICS bad_count = ROW_COUNT;
        IF bad_count > 0 THEN
            RAISE WARNING 'Phase-1 migration: nulled % malformed value(s) in %.% before TIMESTAMPTZ conversion', bad_count, tbl, col;
        END IF;
        BEGIN
            EXECUTE format('ALTER TABLE %I ALTER COLUMN %I TYPE TIMESTAMPTZ USING %I::timestamptz', tbl, col, col);
        EXCEPTION WHEN OTHERS THEN
            RAISE WARNING 'Phase-1 migration: could not convert %.% to TIMESTAMPTZ (%) - left as TEXT for manual inspection', tbl, col, SQLERRM;
        END;
    END LOOP;
END $$;

-- ── Phase 2 data-type migration: TEXT -> UUID for id / foreign-key columns ──────
-- Every id/foreign-key column that always holds an app-generated UUID
-- (str(uuid.uuid4()) or gen_random_uuid()) is converted from TEXT to native
-- UUID. database.py registers a text-format UUID codec (_encode_uuid/_decode_uuid)
-- so every existing string-based id comparison / f-string / JSON payload is
-- completely unaffected — this is the same technique used for the Phase 1
-- TIMESTAMPTZ migration above.
-- Deliberately EXCLUDED (kept TEXT — confirmed NOT uuid-shaped by inspecting
-- both the generating code and the live data before writing this migration):
--   • login_attempts.identifier — composite string ("login_ip:1.2.3.4", "create_meeting:<uid>", email, etc.)
--   • password_reset_tokens.token / invitations.token — secrets.token_urlsafe(32)
--   • evidence_feedback.evidence_item_id — str(uuid.uuid4())[:8], truncated to 8 chars, not a full UUID
--   • settings.id / settings.org_id — settings.id is a COMPOSITE STRING key
--     ("supervision_template:{org_id}", or the bare literal "supervision_template")
--     used by admin.py get_template/save_template, review.py and
--     transcription_pipeline.py — not a UUID at all, and org_id on that same
--     table can be '' (falsy org_id fallback), not just NULL/uuid.
--   • meetings.date / schedules.start_date / supervision_uploads.meeting_date / focus_topics.active_month
--     — unrelated date-only fields already excluded from Phase 1 above, not id columns anyway.
-- This is ONE all-or-nothing block: RLS policies (which Postgres refuses to let
-- you change a column's type underneath) and every FK constraint are dropped
-- first, columns are converted, then both are rebuilt from what was captured/
-- known before the drop. If ANYTHING fails partway, the whole block rolls back
-- automatically (a DO block is an implicit subtransaction) — the schema, its
-- FKs and its RLS policies all revert to exactly what they were, safe to retry
-- on the next restart once whatever caused the failure is fixed.
DO $$
DECLARE
    id_columns TEXT[][] := ARRAY[
        ARRAY['organisations','id'],
        ARRAY['users','id'], ARRAY['users','org_id'], ARRAY['users','team_id'], ARRAY['users','setting_id'],
        ARRAY['meetings','id'], ARRAY['meetings','org_id'], ARRAY['meetings','team_id'], ARRAY['meetings','setting_id'],
        ARRAY['meetings','schedule_id'], ARRAY['meetings','created_by'], ARRAY['meetings','sign_off_manager_id'],
        ARRAY['meetings','audio_file_id'], ARRAY['meetings','transcript_id'], ARRAY['meetings','analysis_id'],
        ARRAY['transcripts','id'], ARRAY['transcripts','meeting_id'], ARRAY['transcripts','org_id'],
        ARRAY['analyses','id'], ARRAY['analyses','meeting_id'], ARRAY['analyses','org_id'],
        ARRAY['audio_files','id'], ARRAY['audio_files','meeting_id'], ARRAY['audio_files','org_id'],
        ARRAY['review_edits','id'], ARRAY['review_edits','meeting_id'], ARRAY['review_edits','org_id'], ARRAY['review_edits','user_id'],
        ARRAY['reviewer_comments','id'], ARRAY['reviewer_comments','meeting_id'], ARRAY['reviewer_comments','org_id'], ARRAY['reviewer_comments','user_id'],
        ARRAY['standards_entries','id'], ARRAY['standards_entries','org_id'], ARRAY['standards_entries','created_by'],
        ARRAY['standards_documents','id'], ARRAY['standards_documents','org_id'], ARRAY['standards_documents','uploaded_by'],
        ARRAY['invitations','id'], ARRAY['invitations','org_id'], ARRAY['invitations','user_id'],
        ARRAY['audit_logs','id'], ARRAY['audit_logs','meeting_id'], ARRAY['audit_logs','org_id'], ARRAY['audit_logs','user_id'],
        ARRAY['org_settings','id'], ARRAY['org_settings','org_id'], ARRAY['org_settings','manager_user_id'],
        ARRAY['teams','id'], ARRAY['teams','org_id'], ARRAY['teams','setting_id'], ARRAY['teams','supervisor_user_id'],
        ARRAY['schedules','id'], ARRAY['schedules','org_id'], ARRAY['schedules','staff_user_id'], ARRAY['schedules','meeting_type_id'], ARRAY['schedules','created_by'],
        ARRAY['meeting_types','id'], ARRAY['meeting_types','org_id'],
        ARRAY['meeting_prep','id'], ARRAY['meeting_prep','meeting_id'], ARRAY['meeting_prep','org_id'], ARRAY['meeting_prep','created_by'],
        ARRAY['focus_topics','id'], ARRAY['focus_topics','org_id'], ARRAY['focus_topics','created_by'],
        ARRAY['supervision_uploads','id'], ARRAY['supervision_uploads','org_id'], ARRAY['supervision_uploads','staff_id'], ARRAY['supervision_uploads','uploader_id'],
        ARRAY['evidence_feedback','id'], ARRAY['evidence_feedback','meeting_id'], ARRAY['evidence_feedback','org_id'], ARRAY['evidence_feedback','user_id'],
        ARRAY['password_reset_tokens','id'],
        ARRAY['jobs','id'], ARRAY['jobs','meeting_id']
    ];
    org_policies TEXT[][] := ARRAY[
        ARRAY['organisations','organisations_rls','id'],
        ARRAY['users','users_rls','org_id'], ARRAY['meetings','meetings_rls','org_id'],
        ARRAY['transcripts','transcripts_rls','org_id'], ARRAY['analyses','analyses_rls','org_id'],
        ARRAY['audio_files','audio_files_rls','org_id'], ARRAY['review_edits','review_edits_rls','org_id'],
        ARRAY['reviewer_comments','reviewer_comments_rls','org_id'], ARRAY['standards_documents','standards_documents_rls','org_id'],
        ARRAY['invitations','invitations_rls','org_id'],
        ARRAY['audit_logs','audit_logs_rls','org_id'], ARRAY['org_settings','org_settings_rls','org_id'],
        ARRAY['teams','teams_rls','org_id'], ARRAY['schedules','schedules_rls','org_id'],
        ARRAY['meeting_types','meeting_types_rls','org_id'], ARRAY['meeting_prep','meeting_prep_rls','org_id'],
        ARRAY['focus_topics','focus_topics_rls','org_id'], ARRAY['supervision_uploads','supervision_uploads_rls','org_id'],
        ARRAY['evidence_feedback','evidence_feedback_rls','org_id']
    ];
    m TEXT[];
    tbl TEXT;
    col TEXT;
    pol TEXT;
    col_type TEXT;
    not_null BOOLEAN;
    bad_count INT;
    fk RECORD;
    already_uuid BOOLEAN;
    cast_expr TEXT := 'NULLIF((SELECT current_setting(''app.current_org_id'', TRUE)), '''')::uuid';
BEGIN
    -- Idempotent short-circuit: if organisations.id is already uuid, a prior
    -- run already fully committed this migration (all-or-nothing, so every
    -- other column/FK/policy is guaranteed to be uuid-aware too) — skip.
    SELECT (data_type = 'uuid') INTO already_uuid FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'organisations' AND column_name = 'id';
    IF already_uuid THEN
        RETURN;
    END IF;

    -- 1. Capture every existing FK constraint's exact definition, then drop
    --    them all (Postgres refuses to change a column's type while a FK
    --    with a different type still references/uses it).
    CREATE TEMP TABLE IF NOT EXISTS _phase2_fk_backup (conname text, tbl text, def text);
    DELETE FROM _phase2_fk_backup;
    INSERT INTO _phase2_fk_backup
        SELECT conname, conrelid::regclass::text, pg_get_constraintdef(oid)
        FROM pg_constraint WHERE contype = 'f' AND connamespace = 'public'::regnamespace;
    FOR fk IN SELECT * FROM _phase2_fk_backup LOOP
        EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', fk.tbl, fk.conname);
    END LOOP;

    -- 2. Drop the 21 RLS policies (must happen before ALTER COLUMN TYPE —
    --    Postgres refuses to change the type of a column a policy depends on).
    FOREACH m SLICE 1 IN ARRAY org_policies LOOP
        EXECUTE format('DROP POLICY IF EXISTS %I ON %I', m[2], m[1]);
    END LOOP;
    EXECUTE 'DROP POLICY IF EXISTS standards_entries_rls ON standards_entries';

    -- 3. password_reset_tokens.id has a TEXT-cast default that can't be
    --    auto-cast to uuid; drop it before the type conversion, then set the
    --    native equivalent back afterwards (step 6).
    ALTER TABLE password_reset_tokens ALTER COLUMN id DROP DEFAULT;

    -- 4. Convert every id/FK column. Non-UUID values (only ever seen on
    --    nullable historical-snapshot columns — e.g. 4 pre-existing ''
    --    rows in meetings.sign_off_manager_id) are nulled first, logged via
    --    RAISE WARNING, so the ALTER can succeed. If the column is NOT NULL
    --    (i.e. a primary/composite key — e.g. settings.id, which is why that
    --    table is excluded above), silently nulling it would just hit a
    --    confusing NOT NULL violation a moment later — instead we RAISE
    --    EXCEPTION with a clear message so it's obvious the column was
    --    wrongly added to id_columns, caught by the outer EXCEPTION below.
    FOREACH m SLICE 1 IN ARRAY id_columns LOOP
        tbl := m[1];
        col := m[2];
        SELECT data_type, (is_nullable = 'NO') INTO col_type, not_null FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = tbl AND column_name = col;
        IF col_type IS NULL OR col_type = 'uuid' THEN
            CONTINUE;
        END IF;
        EXECUTE format(
            'SELECT count(*) FROM %I WHERE %I IS NOT NULL AND %I !~ %L',
            tbl, col, col, '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
        ) INTO bad_count;
        IF bad_count > 0 AND not_null THEN
            RAISE EXCEPTION 'Phase-2 migration: %.% is NOT NULL and has % non-UUID value(s) — this column is not uuid-shaped and must not be in id_columns', tbl, col, bad_count;
        ELSIF bad_count > 0 THEN
            EXECUTE format(
                'UPDATE %I SET %I = NULL WHERE %I IS NOT NULL AND %I !~ %L',
                tbl, col, col, col, '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
            );
            RAISE WARNING 'Phase-2 migration: nulled % non-UUID value(s) in %.% before UUID conversion', bad_count, tbl, col;
        END IF;
        EXECUTE format('ALTER TABLE %I ALTER COLUMN %I TYPE UUID USING %I::uuid', tbl, col, col);
    END LOOP;

    -- 5. Re-add every FK exactly as captured (types now match on both sides).
    FOR fk IN SELECT * FROM _phase2_fk_backup LOOP
        EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I %s', fk.tbl, fk.conname, fk.def);
    END LOOP;

    -- 6. Recreate the 21 RLS policies, now uuid-aware. NULLIF(...,'') guards
    --    the empty-string default app.current_org_id gets when unset —
    --    casting NULL to uuid is always NULL (never errors), so it just
    --    fails closed (matches TEXT-era behavior of comparing against '').
    FOREACH m SLICE 1 IN ARRAY org_policies LOOP
        tbl := m[1]; pol := m[2]; col := m[3];
        EXECUTE format('CREATE POLICY %I ON %I FOR ALL USING (%I = %s) WITH CHECK (%I = %s)',
            pol, tbl, col, cast_expr, col, cast_expr);
    END LOOP;
    EXECUTE format(
        'CREATE POLICY standards_entries_rls ON standards_entries FOR ALL USING (org_id IS NULL OR org_id = %s) WITH CHECK (org_id = %s)',
        cast_expr, cast_expr
    );

    -- 7. Native uuid default (previously cast through TEXT because the
    --    column itself was TEXT).
    ALTER TABLE password_reset_tokens ALTER COLUMN id SET DEFAULT gen_random_uuid();

    RAISE NOTICE 'Phase-2 migration: all id/FK columns converted TEXT -> UUID successfully';
EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'Phase-2 UUID migration failed and was fully rolled back (schema unchanged): %', SQLERRM;
END $$;
"""


async def _init_conn(conn):
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    await conn.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def create_schema():
    dsn = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(dsn, ssl="require")
    try:
        await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
        await conn.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
        await conn.execute(SCHEMA_SQL)
        # ── Data migrations ───────────────────────────────────────────────────────
        await conn.execute(
            "UPDATE meeting_types SET name = 'Supervision' WHERE name = 'Monthly Supervision'"
        )
        # Fix meetings where attendees/shared_with were stored as a JSON object
        # instead of an array (legacy data bug). Also un-stringify double-encoded
        # JSON strings (jsonb_typeof = 'string').
        await conn.execute("""
            UPDATE meetings
            SET attendees = CASE
                WHEN jsonb_typeof(attendees) = 'string' THEN (attendees #>> '{}')::jsonb
                WHEN attendees = '{}'::jsonb THEN '[]'::jsonb
                ELSE jsonb_build_array(attendees)
            END
            WHERE jsonb_typeof(attendees) IN ('object', 'string')
        """)
        await conn.execute("""
            UPDATE meetings
            SET shared_with = CASE
                WHEN jsonb_typeof(shared_with) = 'string' THEN (shared_with #>> '{}')::jsonb
                WHEN shared_with = '{}'::jsonb THEN '[]'::jsonb
                ELSE jsonb_build_array(shared_with)
            END
            WHERE shared_with IS NOT NULL
              AND jsonb_typeof(shared_with) IN ('object', 'string')
        """)
        # Fix other JSONB array columns that may also be double-encoded
        for col in ("pii_redactions", "recording_events", "paused_periods"):
            await conn.execute(f"""
                UPDATE meetings
                SET {col} = (({col}) #>> '{{}}')::jsonb
                WHERE jsonb_typeof({col}) = 'string'
            """)
        await conn.execute("""
            UPDATE meetings
            SET sign_off_record = (sign_off_record #>> '{}')::jsonb
            WHERE sign_off_record IS NOT NULL AND jsonb_typeof(sign_off_record) = 'string'
        """)
        await conn.execute("""
            UPDATE transcripts
            SET speaker_colors = (speaker_colors #>> '{}')::jsonb
            WHERE jsonb_typeof(speaker_colors) = 'string'
        """)
        await conn.execute("""
            UPDATE standards_entries
            SET
                keywords      = CASE WHEN jsonb_typeof(keywords)      = 'string' THEN (keywords      #>> '{}')::jsonb ELSE keywords      END,
                sub_outcomes  = CASE WHEN jsonb_typeof(sub_outcomes)  = 'string' THEN (sub_outcomes  #>> '{}')::jsonb ELSE sub_outcomes  END,
                key_questions = CASE WHEN jsonb_typeof(key_questions) = 'string' THEN (key_questions #>> '{}')::jsonb ELSE key_questions END
            WHERE jsonb_typeof(keywords)='string' OR jsonb_typeof(sub_outcomes)='string' OR jsonb_typeof(key_questions)='string'
        """)
        # Fix analyses JSONB columns (all may be double-encoded strings)
        await conn.execute("""
            UPDATE analyses
            SET
                cqc_mappings       = CASE WHEN jsonb_typeof(cqc_mappings)       = 'string' THEN (cqc_mappings       #>> '{}')::jsonb ELSE cqc_mappings       END,
                care_cert_mappings = CASE WHEN jsonb_typeof(care_cert_mappings) = 'string' THEN (care_cert_mappings #>> '{}')::jsonb ELSE care_cert_mappings END,
                custom_mappings    = CASE WHEN jsonb_typeof(custom_mappings)    = 'string' THEN (custom_mappings    #>> '{}')::jsonb ELSE custom_mappings    END,
                actions            = CASE WHEN jsonb_typeof(actions)            = 'string' THEN (actions            #>> '{}')::jsonb ELSE actions            END,
                risks              = CASE WHEN jsonb_typeof(risks)              = 'string' THEN (risks              #>> '{}')::jsonb ELSE risks              END,
                learning_needs     = CASE WHEN jsonb_typeof(learning_needs)     = 'string' THEN (learning_needs     #>> '{}')::jsonb ELSE learning_needs     END,
                achievements       = CASE WHEN jsonb_typeof(achievements)       = 'string' THEN (achievements       #>> '{}')::jsonb ELSE achievements       END
            WHERE
                jsonb_typeof(cqc_mappings)       = 'string'
             OR jsonb_typeof(care_cert_mappings) = 'string'
             OR jsonb_typeof(custom_mappings)    = 'string'
             OR jsonb_typeof(actions)            = 'string'
             OR jsonb_typeof(risks)              = 'string'
             OR jsonb_typeof(learning_needs)     = 'string'
             OR jsonb_typeof(achievements)       = 'string'
        """)
        logger.info("Schema created/verified successfully")
    finally:
        await conn.close()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    load_dotenv()
    asyncio.run(create_schema())
    print("Schema created successfully.")
