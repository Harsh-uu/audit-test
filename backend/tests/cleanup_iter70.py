"""Revert all test-only DB mutations made during iteration 70 frontend testing."""
import asyncio, json, os
import asyncpg
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
DSN = os.environ["DATABASE_URL"]

PREP_MEETING = "c20802af-17e3-4210-b497-13d09c9e67ec"
ANALYSIS = "7f278c15-ad4d-46aa-b739-8271d2752429"
FAILED_MEETING = "011beb33-c879-4ac7-8bb7-ce6f81f0fd64"
REVIEWED_MEETING = "2f1cc088-0687-48b9-9f40-1dabb5285640"


def as_list(v):
    if isinstance(v, str):
        v = json.loads(v)
    return v or []


async def main():
    c = await asyncpg.connect(DSN)
    # 1. remove seeded prep agenda
    await c.execute("delete from meeting_prep where meeting_id=$1", PREP_MEETING)
    # 2. remove carried-forward actions
    raw = await c.fetchval("select actions from analyses where id=$1", ANALYSIS)
    actions = as_list(raw)
    kept = [a for a in actions if a.get("source") != "carry_forward_prep"]
    await c.execute("update analyses set actions=$1::jsonb where id=$2", json.dumps(kept), ANALYSIS)
    print(f"actions {len(actions)} -> {len(kept)}")
    # 3. restore the failed meeting
    await c.execute(
        "update meetings set status='processing_failed', audio_file_id=null, analysis_id=null where id=$1",
        FAILED_MEETING,
    )
    await c.execute("delete from transcripts where meeting_id=$1", FAILED_MEETING)
    # 4. reset attendee reviewed flags on the in_review meeting
    raw = await c.fetchval("select attendees from meetings where id=$1", REVIEWED_MEETING)
    att = as_list(raw)
    if isinstance(att, str):
        att = json.loads(att)
    for a in att:
        a["reviewed"] = False
        a["reviewed_at"] = None
    await c.execute(
        "update meetings set attendees=$1::jsonb, status='in_review' where id=$2",
        json.dumps(att), REVIEWED_MEETING,
    )
    for mid in (PREP_MEETING, FAILED_MEETING, REVIEWED_MEETING):
        print(dict(await c.fetchrow("select id,status,audio_file_id from meetings where id=$1", mid)))
    await c.close()


asyncio.run(main())
