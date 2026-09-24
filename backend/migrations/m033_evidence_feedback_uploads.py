"""Extend evidence_feedback tracking to uploaded-document evidence (not just
meetings). Previously meeting_id was NOT NULL because all feedback came from
live meeting evidence. Document uploads (supervision_uploads) now also need
accept/reject/flag tracking so the AI Accuracy report is complete — a row
now has EITHER meeting_id OR upload_id set, not both.
"""

VERSION = "033_evidence_feedback_uploads"

SQL = """
ALTER TABLE evidence_feedback ALTER COLUMN meeting_id DROP NOT NULL;
ALTER TABLE evidence_feedback ADD COLUMN IF NOT EXISTS upload_id UUID;

DO $$ BEGIN
    ALTER TABLE evidence_feedback ADD CONSTRAINT fk_evidence_feedback_upload_id
        FOREIGN KEY (upload_id) REFERENCES supervision_uploads(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_evidence_feedback_upload_id ON evidence_feedback(upload_id);
"""


async def up(conn):
    await conn.execute(SQL)
