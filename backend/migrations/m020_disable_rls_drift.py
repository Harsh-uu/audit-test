"""SEC-DB-002: undo manually-toggled RLS on 4 tables the code never intended
to protect this way.

Audit found `jobs`, `login_attempts`, `password_reset_tokens`, `schema_migrations`
live with relrowsecurity=true but relforcerowsecurity=false and ZERO policies —
the exact signature of someone clicking Supabase Dashboard's "Enable RLS" toggle
by hand (which never sets FORCE), not this codebase's own migration pattern
(every table m001/m002 actually manage always pairs ENABLE + FORCE in one
statement — see m001_core_tables.py).

These 4 tables are deliberately NOT RLS candidates:
- login_attempts / password_reset_tokens: looked up by raw email/token during
  login/reset BEFORE any org context exists — org-scoped RLS makes no sense here.
- jobs: background-worker/system table, always accessed via with_admin().
- schema_migrations: internal ledger, only ever touched by the bootstrap
  connection in init_db.py::create_schema() (always the postgres/BYPASSRLS role).

With RLS enabled and no policies, ANY non-bypass role (app_rls_user, used by
with_org()) sees zero rows / deletes zero rows for these tables, even though
app_rls_user already holds full table-level grants (m003) — confirmed live:
meetings.py::delete_meeting()'s defense-in-depth `DELETE FROM jobs WHERE
meeting_id=...` (run via with_org()) was silently a no-op (masked by m014's
FK ON DELETE CASCADE, which bypasses RLS, doing the real cleanup). Disabling
RLS here restores that manual cleanup's intended behavior and removes the
same silent-zero-rows trap for any future with_org() code path — it does NOT
grant any new access, since app_rls_user's grants already exist regardless.
"""

VERSION = "020_disable_rls_drift"


async def up(conn):
    for table in ("jobs", "login_attempts", "password_reset_tokens", "schema_migrations"):
        await conn.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
