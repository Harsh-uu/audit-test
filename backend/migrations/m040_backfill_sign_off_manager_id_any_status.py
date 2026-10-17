"""Follow-up to m038: that backfill was restricted to status IN
('signed_off','shared') because the bug it targeted (sign_off_manager_id
never being written by sign_off()) could only exist on meetings that had
already been through that endpoint. But My Portfolio's Achievements/
Actions/Learning Needs registers are deliberately NOT status-restricted
(see portfolio.py's _build_portfolio_registers docstring — rollover needs
pre-signoff visibility), so a meeting that bypassed create_meeting()'s
own auto-assignment entirely (e.g. demo/seed data inserted directly into
the DB rather than created through the live recording flow) can sit with
sign_off_manager_id NULL in ANY status — including 'reviewed'/'in_review'
— and still leak its achievements into the conducting manager's own
portfolio indefinitely, since m037/038/039 would never reach it.

There is no reason to restrict this specific backfill to signed-off
meetings: the "exactly one manager/admin attendee" rule is unambiguous
regardless of status (it's the exact same rule create_meeting() applies
at creation time, just applied retroactively here for rows that evidently
never went through create_meeting()'s own logic). Genuinely ambiguous
rows (0 or 2+ manager/admin attendees) are still left NULL, same as ever.
"""

VERSION = "040_backfill_sign_off_manager_id_any_status"

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
    WHERE m.sign_off_manager_id IS NULL
      AND m.analysis_id IS NOT NULL
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
