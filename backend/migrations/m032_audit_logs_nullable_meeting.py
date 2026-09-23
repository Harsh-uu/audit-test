"""m013 added NOT NULL to audit_logs.meeting_id because at that time every
audit_logs row was meeting-scoped. This session introduces org-level staff
lifecycle events (Deactivate / Hard Delete / invite revoked) that are NOT
tied to any single meeting, so meeting_id must be nullable again for those
rows (org_id is still always set, and the new GET /admin/activity-log
endpoint filters on `meeting_id IS NULL` to show just these events,
distinct from the per-meeting Audit Trail tab).
"""

VERSION = "032_audit_logs_nullable_meeting"

SQL = """
ALTER TABLE audit_logs ALTER COLUMN meeting_id DROP NOT NULL;
"""


async def up(conn):
    await conn.execute(SQL)
