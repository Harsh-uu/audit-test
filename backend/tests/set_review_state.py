"""Set attendee reviewed flags / meeting status for UI lifecycle testing.

Usage: python set_review_state.py <meeting_id> <status> <email:true|false> [...]
"""
import asyncio, json, os, sys
import asyncpg
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
DSN = os.environ["DATABASE_URL"]


async def main():
    mid, status = sys.argv[1], sys.argv[2]
    flags = dict(a.split(":") for a in sys.argv[3:])
    conn = await asyncpg.connect(DSN, ssl="require")
    raw = await conn.fetchval("SELECT attendees FROM meetings WHERE id=$1", mid)
    att = json.loads(raw) if isinstance(raw, str) else raw
    if isinstance(att, str):  # tolerate double-JSON-encoded attendees column
        att = json.loads(att)
    for a in att:
        if a.get("email") in flags:
            a["reviewed"] = flags[a["email"]] == "true"
    await conn.execute("UPDATE meetings SET status=$1, attendees=$2 WHERE id=$3", status, json.dumps(att), mid)
    print("updated", mid, status, [(a["email"], a["reviewed"]) for a in att])
    await conn.close()


asyncio.run(main())
