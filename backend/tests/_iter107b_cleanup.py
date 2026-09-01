"""Cleanup of iteration 107/107b test residue (users/invitations/meetings)."""
import asyncio
import asyncpg
from dotenv import dotenv_values

DSN = dotenv_values("/app/backend/.env")["DATABASE_URL"]


async def main():
    c = await asyncpg.connect(DSN)
    try:
        rows = await c.fetch(
            "SELECT id, email, name, org_id FROM users WHERE name LIKE 'TEST_iter107%' OR email LIKE 'test_iter107%'")
        print("residual users:", [(r["email"], r["name"]) for r in rows])
        ids = [r["id"] for r in rows]
        if ids:
            await c.execute("DELETE FROM invitations WHERE user_id = ANY($1::text[])", ids)
            await c.execute("DELETE FROM schedules WHERE staff_user_id = ANY($1::text[])", ids)
            await c.execute("DELETE FROM users WHERE id = ANY($1::text[])", ids)
        # UI-created meeting from this test round
        mid = "741289b6-a6bb-496c-a77a-5c850ef8d19f"
        await c.execute("DELETE FROM meeting_prep WHERE meeting_id=$1", mid)
        await c.execute("DELETE FROM meetings WHERE id=$1", mid)
        # org settings / teams residue
        await c.execute("DELETE FROM teams WHERE name LIKE 'TEST_iter107%'")
        await c.execute("DELETE FROM org_settings WHERE name LIKE 'TEST_iter107%'")
        left = await c.fetchrow(
            """SELECT (SELECT count(*) FROM users WHERE name LIKE 'TEST_iter107%') u,
                      (SELECT count(*) FROM meetings WHERE title LIKE 'TEST_iter107%' OR id LIKE 'TEST_iter107%') m,
                      (SELECT count(*) FROM organisations WHERE name LIKE 'TEST_iter107%') o,
                      (SELECT count(*) FROM teams WHERE name LIKE 'TEST_iter107%') t,
                      (SELECT count(*) FROM org_settings WHERE name LIKE 'TEST_iter107%') s""")
        print("remaining residue:", dict(left))
        # provenance of the 'Test N' meetings seen in the UI
        pre = await c.fetch(
            "SELECT id, title, date, created_at, created_by_name FROM meetings WHERE title LIKE 'Test %' ORDER BY created_at")
        for r in pre:
            print("pre-existing:", dict(r))
    finally:
        await c.close()


asyncio.run(main())
