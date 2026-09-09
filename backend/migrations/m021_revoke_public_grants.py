"""SEC-DB-003: revoke PostgREST-facing anon/authenticated grants on 4 tables
that were never meant to be reachable over the public Supabase REST API.

Supabase's automated security advisor flagged this live (06 Sep 2026):
"Table publicly accessible" (rls_disabled_in_public) and "Sensitive data
publicly accessible" (sensitive_columns_exposed) on password_reset_tokens
(columns: token, email) — and the same rls_disabled_in_public signature
applies to jobs, login_attempts, schema_migrations, since m020 disabled RLS
on all four.

m020's reasoning for disabling RLS on these tables is still correct — they
are pre-auth/system tables this app's own with_org()/with_admin() code paths
were never meant to filter by organisation. But every table in the `public`
schema gets default SELECT/INSERT/UPDATE/DELETE grants to Supabase's `anon`
and `authenticated` roles unless explicitly revoked, and those two roles are
what Supabase's auto-generated PostgREST API (the `/rest/v1/...` endpoints
reachable with nothing but the public, non-secret anon API key) authenticates
as. RLS-off + those grants + PostgREST together means anyone holding the
project's anon key could read/write/delete these tables directly over HTTP,
completely bypassing this backend.

Confirmed live before writing this: neither the frontend nor this backend
ever uses the anon or authenticated Postgres roles for anything — the app
connects via APP_DATABASE_URL (app_default, which inherits its real table
access from app_rls_user's m003 grants) and DATABASE_URL (postgres, which
owns these tables outright and needs no explicit grant at all). Revoking
anon/authenticated here removes public HTTP exposure only — it changes
nothing about how this application itself reaches these tables.
"""

VERSION = "021_revoke_public_grants"


async def up(conn):
    for table in ("jobs", "login_attempts", "password_reset_tokens", "schema_migrations"):
        await conn.execute(f"REVOKE ALL ON TABLE {table} FROM anon, authenticated")
