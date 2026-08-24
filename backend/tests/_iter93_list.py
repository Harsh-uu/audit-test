"""List meetings with transcript+analysis for UI regression testing (read-only)."""
import asyncio, os
import asyncpg
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
DSN = os.environ["DATABASE_URL"]
ORG = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"


async def main():
    conn = await asyncpg.connect(DSN, ssl="require")
    rows = await conn.fetch(
        """SELECT m.id, m.title, m.status, m.pii_review_status, m.transcript_id, m.analysis_id,
                  length(t.text) AS tlen, (t.speaker_text IS NOT NULL) AS has_sp
           FROM meetings m LEFT JOIN transcripts t ON t.id = m.transcript_id
           WHERE m.org_id=$1 AND m.analysis_id IS NOT NULL AND m.transcript_id IS NOT NULL
           ORDER BY m.created_at DESC LIMIT 25""", ORG
    )
    for r in rows:
        print(dict(r))
    await conn.close()


asyncio.run(main())
