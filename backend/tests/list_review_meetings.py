"""List in_review meetings + attendee review state (read-only helper for UI testing)."""
import asyncio, os
import asyncpg
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
DSN = os.environ["DATABASE_URL"]


async def main():
    conn = await asyncpg.connect(DSN, ssl="require")
    rows = await conn.fetch(
        "SELECT id, title, status, attendees, analysis_id FROM meetings WHERE status IN ('in_review','reviewed') ORDER BY created_at DESC LIMIT 15"
    )
    for r in rows:
        print(dict(r))
    await conn.close()


asyncio.run(main())
