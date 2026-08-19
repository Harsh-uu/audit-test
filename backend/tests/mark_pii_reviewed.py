"""Mark pii_review_status reviewed for a meeting (skip the confidentiality gate in UI tests)."""
import asyncio, os, sys
import asyncpg
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")


async def main():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"], ssl="require")
    for mid in sys.argv[1:]:
        await conn.execute("UPDATE meetings SET pii_review_status='reviewed' WHERE id=$1", mid)
        print("pii reviewed:", mid)
    await conn.close()


asyncio.run(main())
