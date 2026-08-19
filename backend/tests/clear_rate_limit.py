"""Test helper: clear DB-backed login rate-limit / lockout rows so repeated
automated logins (get_tokens.py) don't trip the 20-per-IP / 15-min limiter.

Usage: python clear_rate_limit.py
"""
import asyncio
import os

import asyncpg
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
DSN = os.environ["DATABASE_URL"]


async def main():
    conn = await asyncpg.connect(DSN)
    rows = await conn.fetch("SELECT identifier, count FROM login_attempts")
    print("before:", [dict(r) for r in rows])
    await conn.execute("DELETE FROM login_attempts")
    print("cleared login_attempts")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
