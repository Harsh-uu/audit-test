"""Bug fix: POST /{meeting_id}/signoff never wrote sign_off_manager_id — it
was only auto-assigned at meeting creation when exactly one manager/admin
was among the attendees (0 or 2+ left it NULL "for manual selection", which
in practice often never happened via PUT /{id}/manager). Every downstream
consumer of this field — Team Insights' per-manager registers, the Download
Audio permission check, and critically My Portfolio's "meetings I conducted
for my own staff" exclusion filter — relied on it being correctly populated
on any signed-off/shared meeting. With it NULL, a manager's own conducted
supervision (and its Achievements/Actions/Learning Needs) leaked into their
OWN personal portfolio instead of being excluded, because the exclusion
filter's `sign_off_manager_id IS NULL OR sign_off_manager_id != caller_id`
treats NULL as "not excluded".

review.py's sign_off() is fixed going forward (COALESCE at sign-off time);
this is the one-time repair for meetings that were already signed off
before that fix shipped, using sign_off_record->>'signed_by' (always
populated at sign-off, regardless of this bug) as the source of truth for
who actually signed it off.
"""

VERSION = "037_backfill_sign_off_manager_id"

SQL = """
UPDATE meetings
SET sign_off_manager_id = (sign_off_record->>'signed_by')::uuid,
    sign_off_manager_name = sign_off_record->>'signed_by_name'
WHERE status IN ('signed_off', 'shared')
  AND sign_off_manager_id IS NULL
  AND sign_off_record IS NOT NULL
  AND sign_off_record ? 'signed_by'
  AND (sign_off_record->>'signed_by') ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$';
"""


async def up(conn):
    await conn.execute(SQL)
