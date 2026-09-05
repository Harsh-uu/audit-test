"""Close the last orphan gap from the FK-constraints audit (m004): jobs.meeting_id
was deliberately left without a FK so the app could "keep job history after a
meeting is deleted" — but nothing anywhere (grep-confirmed) ever reads jobs for
display, so that history is never actually surfaced. Reversing that decision:
clean the existing orphans, then add the same FK + manual-cascade
belt-and-suspenders pattern already used for every other meeting-child table
(transcripts, analyses, audio_files, reviewer_comments, review_edits,
audit_logs, evidence_feedback).
"""

VERSION = "014_jobs_fk_cascade"

SQL = """
-- One-time cleanup: delete jobs rows whose meeting was already removed by a
-- prior delete_meeting()/delete_org() call before this FK existed to enforce it.
DELETE FROM jobs WHERE meeting_id IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM meetings m WHERE m.id = jobs.meeting_id);

DO $$ BEGIN ALTER TABLE jobs ADD CONSTRAINT fk_jobs_meeting_id FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

CREATE INDEX IF NOT EXISTS idx_jobs_meeting_id ON jobs(meeting_id);
"""


async def up(conn):
    await conn.execute(SQL)
