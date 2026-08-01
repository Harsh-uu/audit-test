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
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS users_rls ON users;
CREATE POLICY users_rls ON users FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

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
DROP POLICY IF EXISTS meetings_rls ON meetings;
CREATE POLICY meetings_rls ON meetings FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

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
DROP POLICY IF EXISTS transcripts_rls ON transcripts;
CREATE POLICY transcripts_rls ON transcripts FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

CREATE TABLE IF NOT EXISTS analyses (
    id TEXT PRIMARY KEY,
    meeting_id TEXT,
    org_id TEXT,
    summary TEXT NOT NULL DEFAULT '',
    edited_summary TEXT,
    actions JSONB NOT NULL DEFAULT '[]',
    risks JSONB NOT NULL DEFAULT '[]',
    cqc_mappings JSONB NOT NULL DEFAULT '[]',
    care_cert_mappings JSONB NOT NULL DEFAULT '[]',
    custom_mappings JSONB NOT NULL DEFAULT '[]',
    created_at TEXT,
    last_edited_at TEXT
);
ALTER TABLE analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE analyses FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS analyses_rls ON analyses;
CREATE POLICY analyses_rls ON analyses FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

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
DROP POLICY IF EXISTS audio_files_rls ON audio_files;
CREATE POLICY audio_files_rls ON audio_files FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

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
DROP POLICY IF EXISTS review_edits_rls ON review_edits;
CREATE POLICY review_edits_rls ON review_edits FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

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
DROP POLICY IF EXISTS reviewer_comments_rls ON reviewer_comments;
CREATE POLICY reviewer_comments_rls ON reviewer_comments FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

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
DROP POLICY IF EXISTS standards_entries_rls ON standards_entries;
CREATE POLICY standards_entries_rls ON standards_entries FOR ALL
    USING (
        org_id IS NULL                                                  -- system-wide (CQC / Care Cert)
        OR org_id = current_setting('app.current_org_id', TRUE)        -- org-custom standards
    )
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE)); -- writes always scoped to org

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
DROP POLICY IF EXISTS standards_documents_rls ON standards_documents;
CREATE POLICY standards_documents_rls ON standards_documents FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

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

-- Invitations — no RLS (token-based access)
CREATE TABLE IF NOT EXISTS invitations (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    user_id TEXT,
    token TEXT UNIQUE,
    expires_at TEXT,
    used_at TEXT,
    created_at TEXT
);

-- Settings key-value — no RLS (uses compound org-keyed id)
CREATE TABLE IF NOT EXISTS settings (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    data JSONB NOT NULL DEFAULT '{}'
);

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
DROP POLICY IF EXISTS audit_logs_rls ON audit_logs;
CREATE POLICY audit_logs_rls ON audit_logs FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

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
DROP POLICY IF EXISTS org_settings_rls ON org_settings;
CREATE POLICY org_settings_rls ON org_settings FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

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
DROP POLICY IF EXISTS teams_rls ON teams;
CREATE POLICY teams_rls ON teams FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

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
DROP POLICY IF EXISTS schedules_rls ON schedules;
CREATE POLICY schedules_rls ON schedules FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

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
DROP POLICY IF EXISTS meeting_types_rls ON meeting_types;
CREATE POLICY meeting_types_rls ON meeting_types FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

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
DROP POLICY IF EXISTS meeting_prep_rls ON meeting_prep;
CREATE POLICY meeting_prep_rls ON meeting_prep FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

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
DROP POLICY IF EXISTS focus_topics_rls ON focus_topics;
CREATE POLICY focus_topics_rls ON focus_topics FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

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
DROP POLICY IF EXISTS supervision_uploads_rls ON supervision_uploads;
CREATE POLICY supervision_uploads_rls ON supervision_uploads FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

-- Refresh tokens — no RLS
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    org_id TEXT,
    token_hash TEXT UNIQUE,
    expires_at TEXT,
    created_at TEXT
);

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_meetings_org_id ON meetings(org_id);
CREATE INDEX IF NOT EXISTS idx_meetings_created_at ON meetings(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_meetings_status ON meetings(status);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_org_id ON users(org_id);
CREATE INDEX IF NOT EXISTS idx_transcripts_meeting_id ON transcripts(meeting_id);
CREATE INDEX IF NOT EXISTS idx_analyses_meeting_id ON analyses(meeting_id);
CREATE INDEX IF NOT EXISTS idx_review_edits_meeting_id ON review_edits(meeting_id);
CREATE INDEX IF NOT EXISTS idx_reviewer_comments_meeting_id ON reviewer_comments(meeting_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_meeting_id ON audit_logs(meeting_id);
CREATE INDEX IF NOT EXISTS idx_standards_type ON standards_entries(type, reference);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, attempts, created_at);
CREATE INDEX IF NOT EXISTS idx_schedules_org_id ON schedules(org_id);
CREATE INDEX IF NOT EXISTS idx_meeting_types_org_id ON meeting_types(org_id);
CREATE INDEX IF NOT EXISTS idx_supervision_uploads_org_id ON supervision_uploads(org_id);
CREATE INDEX IF NOT EXISTS idx_supervision_uploads_staff_id ON supervision_uploads(staff_id);

-- ── Schema patches (idempotent — safe to run on existing database) ─────────────
ALTER TABLE meeting_prep ADD COLUMN IF NOT EXISTS gen_status TEXT DEFAULT 'idle';
ALTER TABLE meeting_prep ADD COLUMN IF NOT EXISTS included_source_ids JSONB NOT NULL DEFAULT '[]';
ALTER TABLE meeting_prep ADD COLUMN IF NOT EXISTS created_by TEXT;
ALTER TABLE meeting_prep ADD COLUMN IF NOT EXISTS shared_at TEXT;

ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS speaker_text_backup TEXT;
ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS speaker_text_backup_at TEXT;
ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS speaker_text_backup_by TEXT;
ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS speaker_text_edited_by_name TEXT;
ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS speaker_text_edited_at TEXT;
ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS speaker_colors JSONB NOT NULL DEFAULT '{}';
ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS updated_at TEXT;

ALTER TABLE analyses ADD COLUMN IF NOT EXISTS last_edited_by TEXT;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS rescanned_at TEXT;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS rescanned_by_name TEXT;

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
    refresh_tokens, login_attempts, password_reset_tokens
TO app_rls_user;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_rls_user;

-- Automatically grant privileges on tables created in the future
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rls_user;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO app_rls_user;
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
        logger.info("Schema created/verified successfully")
    finally:
        await conn.close()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    load_dotenv()
    asyncio.run(create_schema())
    print("Schema created successfully.")
