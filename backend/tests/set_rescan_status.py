"""Set meetings.rescan_status for UI badge testing. Usage: python set_rescan_status.py <id> <status|none>"""
import asyncio, os, sys
import asyncpg
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")


async def main():
    mid, st = sys.argv[1], sys.argv[2]
    conn = await asyncpg.connect(os.environ["DATABASE_URL"], ssl="require")
    await conn.execute("UPDATE meetings SET rescan_status=$1 WHERE id=$2", None if st == "none" else st, mid)
    print("rescan_status:", st, mid)
    await conn.close()


asyncio.run(main())
