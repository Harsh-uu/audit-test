"""Set a meeting title (for header truncation UI testing). Usage: python set_title.py <id> "<title>" """
import asyncio, os, sys
import asyncpg
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")


async def main():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"], ssl="require")
    await conn.execute("UPDATE meetings SET title=$1 WHERE id=$2", sys.argv[2], sys.argv[1])
    print("title set")
    await conn.close()


asyncio.run(main())
