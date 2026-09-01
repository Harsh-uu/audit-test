"""app_rls_user grants and composite/dead index cleanup."""

VERSION = "003_grants_indexes"

SQL = """
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
"""


async def up(conn):
    await conn.execute(SQL)
