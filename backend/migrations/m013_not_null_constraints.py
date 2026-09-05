"""Add NOT NULL to child-record FK columns that were verified (live data +
pg_constraint FK cascade rules) to be safe: zero NULLs in production data
today, and no `ON DELETE SET NULL` FK on the column (which would need to
write NULL into it later when the referenced row is deleted).

Explicitly EXCLUDED, on purpose — do not add these in a future pass without
re-reading this comment:
  - standards_entries.org_id (239/240 rows NULL by design — system-wide
    standards sentinel; m006's RLS policy is
    `USING (org_id IS NULL OR org_id = current_org_id)`)
  - users.org_id (2/15 rows NULL — legacy/invited-account edge case with
    explicit application-level handling in routers/meetings.py and
    routers/portfolio.py)
  - meetings.audio_file_id / analysis_id / transcript_id /
    sign_off_manager_id / schedule_id / team_id / setting_id — lifecycle-
    optional, populated after creation as a meeting progresses through
    recording -> transcription -> analysis -> sign-off
  - schedules.staff_user_id / meeting_type_id, org_settings.manager_user_id,
    teams.supervisor_user_id / setting_id, users.team_id / setting_id — all
    have an `ON DELETE SET NULL` FK; NOT NULL would turn that graceful
    cascade into a hard delete failure the next time the referenced row
    (a user, team, or setting) is removed.

Each column is re-checked for NULLs at migration time (not just trusted from
the pre-migration audit) — if any are found, that one column is skipped and
logged rather than failing the whole migration (and therefore backend boot).
"""
import logging

logger = logging.getLogger(__name__)

VERSION = "013_not_null_constraints"

COLUMNS = [
    ("analyses", "meeting_id"), ("analyses", "org_id"),
    ("audio_files", "meeting_id"), ("audio_files", "org_id"),
    ("audit_logs", "meeting_id"), ("audit_logs", "org_id"), ("audit_logs", "user_id"),
    ("evidence_feedback", "meeting_id"), ("evidence_feedback", "org_id"), ("evidence_feedback", "user_id"),
    ("review_edits", "meeting_id"), ("review_edits", "org_id"), ("review_edits", "user_id"),
    ("reviewer_comments", "meeting_id"), ("reviewer_comments", "org_id"),
    ("reviewer_comments", "user_id"), ("reviewer_comments", "role"),
    ("transcripts", "meeting_id"), ("transcripts", "org_id"),
    ("teams", "org_id"),
    ("schedules", "org_id"),
    ("meeting_types", "org_id"),
    ("org_settings", "org_id"),
    ("invitations", "org_id"), ("invitations", "user_id"),
    ("meetings", "created_by"),
]


async def up(conn):
    for tbl, col in COLUMNS:
        bad = await conn.fetchval(f'SELECT count(*) FROM {tbl} WHERE {col} IS NULL')
        if bad > 0:
            logger.warning(
                "m013: skipping NOT NULL on %s.%s — found %d unexpected NULL row(s) "
                "at migration time; investigate before re-attempting", tbl, col, bad,
            )
            continue
        await conn.execute(f'ALTER TABLE {tbl} ALTER COLUMN {col} SET NOT NULL')
