"""iter87: inspect / seed evidence statuses for bulk-accept testing.

Usage:
  python3 tests/_iter87_seed.py show <meeting_id>
  python3 tests/_iter87_seed.py reset <meeting_id>     # all -> pending
  python3 tests/_iter87_seed.py mix <meeting_id>       # set a few to accepted/rejected/needs_followup, rest pending
"""
import asyncio, json, os, sys
import asyncpg
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
DSN = os.environ["DATABASE_URL"]
FIELDS = ["cqc_mappings", "care_cert_mappings", "custom_mappings"]


def _lst(v):
    if v is None:
        return []
    if isinstance(v, str):
        return json.loads(v)
    return v


async def main():
    cmd, mid = sys.argv[1], sys.argv[2]
    conn = await asyncpg.connect(DSN, ssl="require")
    m = await conn.fetchrow("SELECT analysis_id, status, org_id FROM meetings WHERE id=$1", mid)
    a = await conn.fetchrow("SELECT * FROM analyses WHERE id=$1", m["analysis_id"])
    if cmd == "show":
        print("meeting status:", m["status"], "org:", m["org_id"])
        for f in FIELDS:
            items = _lst(a[f])
            counts = {}
            for it in items:
                key = (it.get("confidence"), it.get("status") or "pending")
                counts[key] = counts.get(key, 0) + 1
            print(f, len(items), counts)
    elif cmd in ("reset", "mix"):
        for f in FIELDS:
            items = _lst(a[f])
            for i, it in enumerate(items):
                items[i]["status"] = "pending"
            if cmd == "mix" and items:
                # mark first likely as accepted, first possible as rejected -> must not be touched
                done = {"likely_evidence": 0, "possible_evidence": 0}
                for i, it in enumerate(items):
                    c = it.get("confidence")
                    if c == "likely_evidence" and done["likely_evidence"] == 0:
                        items[i]["status"] = "accepted"; done["likely_evidence"] = 1
                    elif c in ("possible_evidence", "needs_review", "not_enough_evidence") and done["possible_evidence"] == 0:
                        items[i]["status"] = "rejected"; done["possible_evidence"] = 1
            await conn.execute(f"UPDATE analyses SET {f}=$1::jsonb WHERE id=$2", json.dumps(items), m["analysis_id"])
        print("done", cmd)
    await conn.close()


asyncio.run(main())
