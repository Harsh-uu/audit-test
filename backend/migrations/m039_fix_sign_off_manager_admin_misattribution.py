"""Correction to m037/m038: those backfilled sign_off_manager_id using
sign_off_record->>'signed_by' (literally "whoever clicked the sign-off
button") as a proxy for "the supervising manager". That's wrong whenever an
ADMIN performs a bulk/administrative sign-off on behalf of someone else —
which is common (e.g. historical/imported data) and is explicitly allowed
by sign_off()'s role check. In that case the real conducting manager is
whichever single attendee has role='manager' in the meeting's attendee
list — ground-truth meeting composition, not "who happened to click the
button". Only touches rows where sign_off_manager_id currently points at
an admin-role user AND there's exactly one unambiguous manager-role
attendee who differs from that admin; leaves everything else untouched
(including legitimate cases where an admin really was the conducting
manager and is also the only manager-role attendee).
"""

VERSION = "039_fix_sign_off_manager_admin_misattribution"

SQL = """
WITH candidate AS (
    SELECT m.id,
           (array_agg(elem->>'user_id') FILTER (WHERE elem->>'role' = 'manager'))[1] AS mgr_id,
           (array_agg(elem->>'name') FILTER (WHERE elem->>'role' = 'manager'))[1] AS mgr_name,
           count(*) FILTER (WHERE elem->>'role' = 'manager') AS mgr_count
    FROM meetings m,
         jsonb_array_elements(
             CASE WHEN jsonb_typeof(COALESCE(m.attendees,'[]'::jsonb)) = 'array'
                  THEN COALESCE(m.attendees,'[]'::jsonb) ELSE '[]'::jsonb END
         ) elem
    WHERE m.status IN ('signed_off', 'shared')
      AND m.sign_off_manager_id IS NOT NULL
    GROUP BY m.id
)
UPDATE meetings m
SET sign_off_manager_id = c.mgr_id::uuid,
    sign_off_manager_name = c.mgr_name
FROM candidate c, users u
WHERE m.id = c.id
  AND u.id = m.sign_off_manager_id
  AND u.org_id = m.org_id
  AND u.role = 'admin'
  AND c.mgr_count = 1
  AND c.mgr_id IS NOT NULL
  AND c.mgr_id != m.sign_off_manager_id::text
  AND c.mgr_id ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$';
"""


async def up(conn):
    await conn.execute(SQL)
