"""
One-time (idempotent, safe to re-run) backfill: create a Supabase Auth
identity for every existing user who doesn't have one yet.

No password is set here — existing users activate their Supabase identity via
the forced password-reset email sent in a later, separate step. This script
only provisions identities; it does not change how anyone logs in.

Usage: python3 scripts/backfill_supabase_auth.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from utils import supabase_auth  # noqa: E402


async def main():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"], ssl="require")
    try:
        rows = await conn.fetch("SELECT id, email FROM users WHERE supabase_migrated = FALSE")
        print(f"{len(rows)} user(s) to migrate")
        migrated, failed = 0, 0
        for row in rows:
            user_id, email = str(row["id"]), row["email"]
            try:
                await supabase_auth.create_user(user_id, email)
                await conn.execute("UPDATE users SET supabase_migrated=TRUE WHERE id=$1", user_id)
                migrated += 1
                print(f"  OK  {email}")
            except Exception as exc:
                failed += 1
                print(f"  FAIL {email}: {exc}")
        print(f"Done: {migrated} migrated, {failed} failed")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
