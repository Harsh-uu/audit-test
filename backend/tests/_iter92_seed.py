"""iter92: seed evidence confidence/status scenarios for the Accept-all button state tests.

Usage:
  python3 tests/_iter92_seed.py show <meeting_id>
  python3 tests/_iter92_seed.py backup <meeting_id>
  python3 tests/_iter92_seed.py restore <meeting_id>
  python3 tests/_iter92_seed.py scenario_a <meeting_id>   # 4 likely (1 accepted, 3 pending), rest possible pending
  python3 tests/_iter92_seed.py scenario_b <meeting_id>   # zero likely items at all, possible pending
  python3 tests/_iter92_seed.py scenario_c <meeting_id>   # 3 likely, ALL rejected (pending=0, accepted=0)
"""
import asyncio, json, os, sys
import asyncpg
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
DSN = os.environ["DATABASE_URL"]
FIELDS = ["cqc_mappings", "care_cert_mappings", "custom_mappings"]
BK = "/tmp/iter92_backup.json"


def _lst(v):
    if v is None:
        return []
    if isinstance(v, str):
        return json.loads(v)
    return v


async def main():
    cmd, mid = sys.argv[1], sys.argv[2]
    conn = await asyncpg.connect(DSN, ssl="require")
    m = await conn.fetchrow("SELECT analysis_id, status FROM meetings WHERE id=$1", mid)
    aid = m["analysis_id"]
    a = await conn.fetchrow("SELECT * FROM analyses WHERE id=$1", aid)
    data = {f: _lst(a[f]) for f in FIELDS}

    if cmd == "show":
        print("meeting status:", m["status"])
        for f in FIELDS:
            counts = {}
            for it in data[f]:
                k = f"{it.get('confidence')}/{it.get('status') or 'pending'}"
                counts[k] = counts.get(k, 0) + 1
            print(f, len(data[f]), counts)
        await conn.close()
        return

    if cmd == "backup":
        with open(BK, "w") as fh:
            json.dump({"meeting": mid, "analysis": aid, "data": data}, fh)
        print("backed up to", BK)
        await conn.close()
        return

    if cmd == "restore":
        with open(BK) as fh:
            b = json.load(fh)
        assert b["analysis"] == aid
        for f in FIELDS:
            await conn.execute(f"UPDATE analyses SET {f}=$1::jsonb WHERE id=$2", json.dumps(b["data"][f]), aid)
        print("restored")
        await conn.close()
        return

    if cmd == "scenario_a":
        n = 0
        for i, it in enumerate(data["cqc_mappings"]):
            if n < 4:
                it["confidence"] = "likely_evidence"
                it["status"] = "accepted" if n == 0 else "pending"
                n += 1
            else:
                it["confidence"] = "possible_evidence"
                it["status"] = "pending"
        for it in data["care_cert_mappings"]:
            it["confidence"] = "possible_evidence"
            it["status"] = "pending"
    elif cmd == "scenario_b":
        for f in FIELDS:
            for it in data[f]:
                it["confidence"] = "possible_evidence"
                it["status"] = "pending"
    elif cmd == "scenario_c":
        n = 0
        for i, it in enumerate(data["cqc_mappings"]):
            if n < 3:
                it["confidence"] = "likely_evidence"
                it["status"] = "rejected"
                n += 1
            else:
                it["confidence"] = "possible_evidence"
                it["status"] = "pending"
        for it in data["care_cert_mappings"]:
            it["confidence"] = "possible_evidence"
            it["status"] = "pending"
    else:
        raise SystemExit("unknown cmd")

    for f in FIELDS:
        await conn.execute(f"UPDATE analyses SET {f}=$1::jsonb WHERE id=$2", json.dumps(data[f]), aid)
    print("applied", cmd)
    await conn.close()


asyncio.run(main())
