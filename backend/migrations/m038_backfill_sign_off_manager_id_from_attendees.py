"""Follow-up to m037: a handful of meetings are signed_off/shared with no
sign_off_record at all (pre-existing fixture rows inserted directly with
status='signed_off', bypassing POST /{id}/signoff entirely), so m037's
sign_off_record->>'signed_by' backfill couldn't reach them. Falls back to
the same "exactly one manager/admin attendee" inference create_meeting()
already uses when sign_off_manager_id isn't explicitly chosen — genuinely
ambiguous meetings (0 or 2+ manager attendees) are deliberately left NULL
rather than guessed, same as the original creation-time rule.
"""

VERSION = "038_backfill_sign_off_manager_id_from_attendees"

SQL = """
WITH candidate AS (
    SELECT m.id,
           (array_agg(elem->>'user_id') FILTER (WHERE elem->>'role' IN ('manager','admin')))[1] AS mgr_id,
           (array_agg(elem->>'name') FILTER (WHERE elem->>'role' IN ('manager','admin')))[1] AS mgr_name,
           count(*) FILTER (WHERE elem->>'role' IN ('manager','admin')) AS mgr_count
    FROM meetings m,
         jsonb_array_elements(
             CASE WHEN jsonb_typeof(COALESCE(m.attendees,'[]'::jsonb)) = 'array'
                  THEN COALESCE(m.attendees,'[]'::jsonb) ELSE '[]'::jsonb END
         ) elem
    WHERE m.status IN ('signed_off', 'shared') AND m.sign_off_manager_id IS NULL
    GROUP BY m.id
)
UPDATE meetings m
SET sign_off_manager_id = c.mgr_id::uuid,
    sign_off_manager_name = c.mgr_name
FROM candidate c
WHERE m.id = c.id
  AND c.mgr_count = 1
  AND c.mgr_id ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$';
"""


async def up(conn):
    await conn.execute(SQL)
