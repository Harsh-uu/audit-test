"""Add storage_path to supervision_uploads so the original uploaded file
(previously discarded after text extraction — only full_text survived) can be
persisted and read back, matching the standards_documents pattern.
"""

VERSION = "015_supervision_uploads_storage_path"

SQL = """
ALTER TABLE supervision_uploads ADD COLUMN IF NOT EXISTS storage_path TEXT;
"""


async def up(conn):
    await conn.execute(SQL)
