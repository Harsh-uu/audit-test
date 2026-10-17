"""Seed/cleanup a meeting fixture for the Evidence-tab UI test (iter175).
Usage: python seed_iter175_evidence_fixture.py seed   -> prints meeting_id
       python seed_iter175_evidence_fixture.py cleanup <meeting_id>
"""
import sys, asyncio, uuid, json
from datetime import datetime, timezone
import asyncpg
from dotenv import dotenv_values

DSN = dotenv_values("/app/backend/.env")["DATABASE_URL"]

ADMIN_EMAIL = "admin@supervision.com"
STAFF_EMAIL = "user@supervision.com"
MANAGER_EMAIL = "manager@supervision.com"


async def seed():
    conn = await asyncpg.connect(DSN, ssl="require")
    try:
        admin = await conn.fetchrow("SELECT id, org_id FROM users WHERE email=$1", ADMIN_EMAIL)
        mgr = await conn.fetchrow("SELECT id, name FROM users WHERE email=$1", MANAGER_EMAIL)
        staff_id = await conn.fetchval("SELECT id FROM users WHERE email=$1", STAFF_EMAIL)
        org_id = admin["org_id"]

        action_id = str(uuid.uuid4())
        ln_id = str(uuid.uuid4())
        actions = [{
            "id": action_id, "text": "ITER175 UI test action — assigned to staff",
            "action": "ITER175 UI test action — assigned to staff",
            "assigned_to_user_id": str(staff_id), "assigned_to": STAFF_EMAIL,
            "completed": False,
        }]
        lns = [{
            "id": ln_id, "text": "ITER175 UI test learning need — assigned to staff",
            "assigned_to_user_id": str(staff_id), "assigned_to": STAFF_EMAIL,
            "completed": False,
        }]

        meeting_id = str(uuid.uuid4())
        analysis_id = str(uuid.uuid4())
        now_dt = datetime.now(timezone.utc)
        attendees = json.dumps([
            {"user_id": str(mgr["id"]), "name": mgr["name"], "role": "manager", "reviewed": True},
            {"user_id": str(staff_id), "name": "Staff User", "role": "attendee", "reviewed": True},
        ])
        await conn.execute(
            """INSERT INTO meetings (id, org_id, title, date, status, attendees, analysis_id,
                created_by, created_by_name, sign_off_manager_id, sign_off_manager_name,
                created_at, updated_at)
               VALUES ($1,$2,'ITER175 UI Evidence Tab Test',$3::timestamptz,'reviewed',$4::jsonb,NULL,
                       $5,$6,$7,$8,$3::timestamptz,$3::timestamptz)""",
            meeting_id, org_id, now_dt, attendees,
            str(mgr["id"]), mgr["name"], mgr["id"], mgr["name"],
        )
        await conn.execute(
            """INSERT INTO analyses (id, meeting_id, org_id, actions, learning_needs, achievements, created_at)
               VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,'[]'::jsonb,$6::timestamptz)""",
            analysis_id, meeting_id, org_id, json.dumps(actions), json.dumps(lns), now_dt,
        )
        await conn.execute("UPDATE meetings SET analysis_id=$1 WHERE id=$2", analysis_id, meeting_id)
        print(meeting_id)
    finally:
        await conn.close()


async def cleanup(meeting_id):
    conn = await asyncpg.connect(DSN, ssl="require")
    try:
        await conn.execute("DELETE FROM meetings WHERE id=$1", meeting_id)
        await conn.execute("DELETE FROM analyses WHERE meeting_id=$1", meeting_id)
    finally:
        await conn.close()


if __name__ == "__main__":
    if sys.argv[1] == "seed":
        asyncio.run(seed())
    elif sys.argv[1] == "cleanup":
        asyncio.run(cleanup(sys.argv[2]))
