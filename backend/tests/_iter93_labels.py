"""Show speaker labels + fix Tracey residue in speaker_text (iter93 cleanup)."""
import asyncio, os, re, sys
import asyncpg
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
DSN = os.environ["DATABASE_URL"]
TID = "b3fa0ea3-b05a-413c-b0f6-767f1557e92c"


async def main():
    conn = await asyncpg.connect(DSN, ssl="require")
    sp = await conn.fetchval("SELECT speaker_text FROM transcripts WHERE id=$1", TID)
    labels = sorted(set(re.findall(r"^(?:\[[\d:]+\]\s*)?([A-Za-z][^:\n]{0,40}):", sp, re.M)))
    print("labels:", labels)
    if len(sys.argv) > 1 and sys.argv[1] == "fix":
        new = sp.replace("Tracey", "Tracy")
        await conn.execute("UPDATE transcripts SET speaker_text=$1 WHERE id=$2", new, TID)
        print("fixed Tracey residue ->", new.count("Tracey"))
    await conn.close()


asyncio.run(main())
