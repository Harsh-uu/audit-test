"""Seed fixtures for iteration 72 (prep cross-supervisee leak + portfolio null org_id).

Creates:
  1. TEST_ signed-off meeting with 'Connor Repro' (null-org_id user) as attendee,
     cloned from an existing signed-off meeting so the portfolio has real meetings.
  2. TEST_ Org B manager account (different org, org-level scope) for cross-org checks.
Idempotent. Run: python seed_iter72.py [cleanup]
"""
import asyncio
import sys

import asyncpg
import bcrypt
from dotenv import dotenv_values

env = dotenv_values("/app/backend/.env")
DSN = env["DATABASE_URL"]

SRC_MEETING = "d272da8e-d183-4354-a7eb-a38e5c7f586e"
CONNOR_ID = "60613cdc-52a6-4fef-8873-2becd059607a"
CONNOR_MEETING = "11111111-2222-3333-4444-555555555555"
ORGB_ID = "3628a11d-36b8-42df-9d46-0479450ee22c"
ORGB_MGR_ID = "99999999-8888-7777-6666-555555555555"
ORGB_MGR_EMAIL = "test-orgb-manager@example.com"
ORGB_MGR_PW = "OrgBManager123!"


async def seed(conn):
    await conn.execute("DELETE FROM meetings WHERE id=$1", CONNOR_MEETING)
    await conn.execute("DROP TABLE IF EXISTS tmp_seed72")
    await conn.execute("CREATE TEMP TABLE tmp_seed72 AS SELECT * FROM meetings WHERE id=$1", SRC_MEETING)
    await conn.execute(
        """UPDATE tmp_seed72 SET id=$1, title='TEST_ Supervision with Connor Repro',
           attendees=$2::jsonb, sign_off_manager_id=NULL""",
        CONNOR_MEETING,
        '[{"name": "Demo Manager", "role": "manager", "user_id": "465c5101-bbc8-4f26-adaa-c906d3324dd5"},'
        f' {{"name": "Connor Repro", "role": "attendee", "user_id": "{CONNOR_ID}"}}]',
    )
    await conn.execute("INSERT INTO meetings SELECT * FROM tmp_seed72")
    print("seeded connor meeting", CONNOR_MEETING)

    h = bcrypt.hashpw(ORGB_MGR_PW.encode(), bcrypt.gensalt()).decode()
    await conn.execute("DELETE FROM public.users WHERE id=$1 OR email=$2", ORGB_MGR_ID, ORGB_MGR_EMAIL)
    await conn.execute(
        """INSERT INTO public.users (id, org_id, email, password_hash, name, role, is_active,
                             team_id, setting_id, must_change_password, mfa_enabled, created_at, updated_at)
           VALUES ($1,$2,$3,$4,'TEST Org B Manager','manager',TRUE,NULL,NULL,FALSE,FALSE,now(),now())""",
        ORGB_MGR_ID, ORGB_ID, ORGB_MGR_EMAIL, h,
    )
    print("seeded org B manager", ORGB_MGR_EMAIL)


async def cleanup(conn):
    await conn.execute("DELETE FROM meetings WHERE id=$1", CONNOR_MEETING)
    await conn.execute("DELETE FROM public.users WHERE id=$1", ORGB_MGR_ID)
    print("cleaned up")


async def main():
    conn = await asyncpg.connect(DSN, ssl="require")
    if len(sys.argv) > 1 and sys.argv[1] == "cleanup":
        await cleanup(conn)
    else:
        await seed(conn)
    await conn.close()


asyncio.run(main())
