"""Idempotent ALTER TABLE ADD COLUMN patches applied on top of the core schema."""

VERSION = "002_schema_patches"

SQL = """
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
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS processing_error TEXT;


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
-- Policy defined in m006_phase2_uuid.py.

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
"""


async def up(conn):
    await conn.execute(SQL)
