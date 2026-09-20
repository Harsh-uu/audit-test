"""Adds storage_path/content_type to resources — lets a 'course' row point at a
file we host ourselves (Supabase Storage) instead of only an external URL.
"""

VERSION = "028_resources_storage"

SQL = """
ALTER TABLE resources ADD COLUMN IF NOT EXISTS storage_path TEXT;
ALTER TABLE resources ADD COLUMN IF NOT EXISTS content_type TEXT;
"""


async def up(conn):
    await conn.execute(SQL)
