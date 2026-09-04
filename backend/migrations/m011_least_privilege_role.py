"""Least-privilege default connection role.

Until now the connection pool authenticated as `postgres`, which has the
BYPASSRLS attribute — every with_admin() call (and, if one were ever added,
any stray pool.acquire() outside with_org()/with_admin()) silently skips
every RLS policy in the database with no defence-in-depth if a Python-level
org_id filter is ever missing.

This migration creates `app_default`: a LOGIN role with NOBYPASSRLS,
NOSUPERUSER, NOCREATEROLE, NOCREATEDB, granted membership in `app_rls_user`
only (nothing else). database.py's main pool now authenticates as this role
instead of `postgres`, so with_org()'s existing `SET LOCAL ROLE
app_rls_user` keeps working exactly as before, and with_admin() moves to a
*separate* pool that still authenticates as `postgres` — the BYPASSRLS
override becomes an explicit, separately-provisioned connection instead of
the default identity for every request.

The password is generated once by the operator and passed in via the
APP_DB_PASSWORD env var (never hardcoded here). Re-running this migration
(it isn't re-run once recorded in schema_migrations, but the logic is
idempotent regardless) only ever syncs the role to match that env var.
"""
import os

VERSION = "011_least_privilege_role"


async def up(conn):
    password = os.environ["APP_DB_PASSWORD"]
    # token_urlsafe() output is [A-Za-z0-9_-] only — safe to embed directly
    # in a single-quoted SQL literal, but assert it defensively anyway since
    # this value is interpolated into raw SQL rather than bound as a param
    # (CREATE/ALTER ROLE do not accept bind parameters).
    if not password or any(c in password for c in ("'", "\\", ";", " ")):
        raise RuntimeError("APP_DB_PASSWORD is missing or contains unsafe characters")

    await conn.execute(f"""
        DO $do$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_default') THEN
            CREATE ROLE app_default LOGIN PASSWORD '{password}'
              NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
          ELSE
            ALTER ROLE app_default WITH LOGIN PASSWORD '{password}'
              NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
          END IF;
        END $do$;

        GRANT app_rls_user TO app_default;
    """)
