"""Fix Supabase "Auth RLS Initialization Plan" advisory on need_review_signals.

m022's policy called current_setting('app.current_org_id', true) directly in
USING/WITH CHECK instead of wrapping it as (SELECT current_setting(...)) —
every other org-scoped table's policy (see m001_core_tables.py) uses the
wrapped form. Without the wrapper, Postgres re-evaluates the function once
PER ROW scanned instead of once per query (as a cached InitPlan), which is
what the Supabase linter flags — a performance issue, not a data-isolation
bug (the policy's logic itself was always correct).
"""

VERSION = "024_fix_need_review_signals_initplan"

SQL = """
DROP POLICY IF EXISTS need_review_signals_rls ON need_review_signals;

CREATE POLICY need_review_signals_rls ON need_review_signals
    USING      (org_id::text = (SELECT current_setting('app.current_org_id', true)))
    WITH CHECK (org_id::text = (SELECT current_setting('app.current_org_id', true)));
"""


async def up(conn):
    await conn.execute(SQL)
