"""Phase A of Supabase Auth migration: tracking column for identity migration status."""

VERSION = "008_supabase_auth"

SQL = """
ALTER TABLE users ADD COLUMN IF NOT EXISTS supabase_migrated BOOLEAN NOT NULL DEFAULT FALSE;
"""


async def up(conn):
    await conn.execute(SQL)
