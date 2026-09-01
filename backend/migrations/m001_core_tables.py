"""Core tables, RLS enablement and base indexes."""

VERSION = "001_core_tables"

SQL = """
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
-- defined in m006_phase2_uuid.py — it has to run AFTER the id-column type
-- migration (Postgres refuses to change a column's type while a policy
-- depends on it), so all 21 policies are dropped/recreated together in that
-- one atomic block.
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
-- Policy defined in m006_phase2_uuid.py.
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
-- Policy defined in m006_phase2_uuid.py.

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
-- Policy defined in m006_phase2_uuid.py.

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
-- Policy defined in m006_phase2_uuid.py.

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
-- Policy defined in m006_phase2_uuid.py.

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
-- Policy defined in m006_phase2_uuid.py.

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
-- Policy defined in m006_phase2_uuid.py.

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
-- m006_phase2_uuid.py.

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
-- Policy defined in m006_phase2_uuid.py.

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
-- Policy defined in m006_phase2_uuid.py.

-- Settings key-value — RLS: org can only see its own settings
CREATE TABLE IF NOT EXISTS settings (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    data JSONB NOT NULL DEFAULT '{}'
);
ALTER TABLE settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE settings FORCE ROW LEVEL SECURITY;
-- NOTE: unlike every other table, settings.id/org_id are deliberately NEVER
-- migrated to UUID in m006_phase2_uuid.py — this table uses composite string
-- keys (e.g. "supervision_template:{org_id}") as its primary key, not real
-- UUIDs (admin.py get_template/save_template, review.py, transcription_pipeline.py).
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
-- Policy defined in m006_phase2_uuid.py.

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
-- Policy defined in m006_phase2_uuid.py.

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
-- Policy defined in m006_phase2_uuid.py.

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
-- Policy defined in m006_phase2_uuid.py.

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
-- Policy defined in m006_phase2_uuid.py.

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
-- Policy defined in m006_phase2_uuid.py.

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
-- Policy defined in m006_phase2_uuid.py.

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
-- Policy defined in m006_phase2_uuid.py.

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
"""


async def up(conn):
    await conn.execute(SQL)
