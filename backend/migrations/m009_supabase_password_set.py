"""Phase B of Supabase Auth migration: track whether a USABLE Supabase
password has actually been set (distinct from supabase_migrated, which only
means the identity was provisioned — Phase 1's backfill creates identities
with no password yet, so login must not treat those as Supabase-ready)."""

VERSION = "009_supabase_password_set"

SQL = """
ALTER TABLE users ADD COLUMN IF NOT EXISTS supabase_password_set BOOLEAN NOT NULL DEFAULT FALSE;
"""


async def up(conn):
    await conn.execute(SQL)
