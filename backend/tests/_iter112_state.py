"""Iter112 probe: dump Supabase-auth migration flags + clear rate limits."""
import asyncio
import os
import sys

import asyncpg
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
DSN = os.environ["DATABASE_URL"]


async def main():
    conn = await asyncpg.connect(DSN)
    rows = await conn.fetch(
        "SELECT email, role, mfa_enabled, supabase_migrated, supabase_password_set, must_change_password"
        " FROM users ORDER BY email"
    )
    for r in rows:
        print(dict(r))
    print("--- login_attempts ---")
    for r in await conn.fetch("SELECT identifier, count, locked_until FROM login_attempts"):
        print(dict(r))
    if "clear" in sys.argv:
        await conn.execute("DELETE FROM login_attempts")
        print("cleared login_attempts")
    print("--- reset tokens (recent) ---")
    try:
        for r in await conn.fetch(
            "SELECT user_id, token, expires_at, used FROM password_reset_tokens ORDER BY expires_at DESC LIMIT 5"
        ):
            print(dict(r))
    except Exception as e:
        print("token table probe failed:", e)
    await conn.close()


asyncio.run(main())
