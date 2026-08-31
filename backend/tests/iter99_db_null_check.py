"""iter99: end-to-end check that clearing a manager via the API stores NULL (not '') in org_settings."""
import asyncio
import json
import subprocess
import sys

import requests
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
import database  # noqa: E402

BASE = dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"].rstrip("/")
ORG = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"


def api_session():
    out = subprocess.run([sys.executable, "/app/backend/tests/get_tokens.py", "admin@supervision.com", "Admin123!"],
                         capture_output=True, text=True, cwd="/app/backend")
    data = json.loads(out.stdout.strip().splitlines()[-1])
    s = requests.Session()
    for k, v in data["cookies"].items():
        s.cookies.set(k, v)
    return s


async def db_row(sid):
    async with database.with_admin() as c:
        r = await c.fetchrow(
            "SELECT name, manager_user_id, manager_user_id IS NULL AS is_null FROM org_settings WHERE id=$1", sid)
        return dict(r) if r else None


async def main():
    await database.create_pool()
    s = api_session()
    users = s.get(f"{BASE}/api/admin/users", timeout=60).json()
    mgr = [u for u in users if u["role"] == "manager"][0]

    # pre-existing hygiene check
    async with database.with_admin() as c:
        rows = await c.fetch("SELECT name, manager_user_id FROM org_settings WHERE org_id=$1", ORG)
    print("existing rows:", [dict(r) for r in rows])
    print("rows with '' manager_user_id:", [dict(r) for r in rows if r["manager_user_id"] == ""])

    # 1) create with EMPTY STRING manager (what the frontend sends when 'None' selected)
    r = s.post(f"{BASE}/api/org/settings", json={"name": "TEST99_NULLCHK", "description": "", "manager_user_id": ""}, timeout=60)
    sid = r.json()["id"]
    print("create(empty mgr) status", r.status_code, "-> DB:", await db_row(sid))

    # 2) update to assign a manager
    r = s.put(f"{BASE}/api/org/settings/{sid}", json={"name": "TEST99_NULLCHK", "description": "", "manager_user_id": mgr["id"]}, timeout=60)
    print("update(assign mgr) status", r.status_code, "-> DB:", await db_row(sid))

    # 3) update back to '' (None in dropdown)
    r = s.put(f"{BASE}/api/org/settings/{sid}", json={"name": "TEST99_NULLCHK", "description": "", "manager_user_id": ""}, timeout=60)
    print("update(clear mgr) status", r.status_code, "-> DB:", await db_row(sid))

    print("cleanup delete:", s.delete(f"{BASE}/api/org/settings/{sid}", timeout=60).status_code)
    print("row after delete:", await db_row(sid))


asyncio.run(main())
