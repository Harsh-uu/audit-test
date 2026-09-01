"""Iteration 108 cleanup — purge TEST_iter108* residue left by aborted runs."""
import asyncio
import asyncpg
from dotenv import dotenv_values

BE = dotenv_values("/app/backend/.env")


async def main():
    c = await asyncpg.connect(BE["DATABASE_URL"])
    try:
        n = await c.execute("DELETE FROM meetings WHERE title LIKE 'TEST_iter108%'")
        print("meetings:", n)
        uid = await c.fetchval("SELECT id FROM users WHERE email LIKE '%iter108%'")
        if uid:
            await c.execute("DELETE FROM invitations WHERE user_id=$1", uid)
            await c.execute("DELETE FROM users WHERE id=$1", uid)
            print("removed residue user", uid)
        print("teams:", await c.execute("DELETE FROM teams WHERE name LIKE 'TEST_iter108%'"))
        print("org_settings:", await c.execute("DELETE FROM org_settings WHERE name LIKE 'TEST_iter108%'"))
        print("schedules left:", await c.fetchval("SELECT count(*) FROM schedules"))
        print("residual iter108 rows:",
              await c.fetchval("SELECT count(*) FROM meetings WHERE title LIKE 'TEST_iter108%'"),
              await c.fetchval("SELECT count(*) FROM users WHERE email LIKE '%iter108%'"))
    finally:
        await c.close()


asyncio.run(main())
