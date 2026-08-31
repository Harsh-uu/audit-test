"""iter99: does PUT /org/settings/{id} reflect immediately in GET /org/structure? Also check manager_user_id NULL coercion."""
import json
import os
import subprocess
import sys
import time

import requests
from dotenv import dotenv_values

BASE = dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"].rstrip("/")

out = subprocess.run([sys.executable, "/app/backend/tests/get_tokens.py", "admin@supervision.com", "Admin123!"],
                     capture_output=True, text=True, cwd="/app/backend")
data = json.loads(out.stdout.strip().splitlines()[-1])
s = requests.Session()
for k, v in data["cookies"].items():
    s.cookies.set(k, v)


def structure():
    r = s.get(f"{BASE}/api/org/structure", timeout=60)
    r.raise_for_status()
    return r.json()


def find(name):
    for st in structure()["settings"]:
        if st["name"] == name:
            return st
    return None


# find a manager id
users = s.get(f"{BASE}/api/admin/users", timeout=60).json()
mgr = [u for u in users if u["role"] == "manager"][0]
print("manager:", mgr["name"], mgr["id"])

# CREATE with manager
r = s.post(f"{BASE}/api/org/settings", json={"name": "TEST99_API", "description": "", "manager_user_id": mgr["id"]}, timeout=60)
print("create status", r.status_code, r.text[:200])
sid = r.json()["id"]
st = find("TEST99_API")
print("immediately after create, present:", st is not None, "manager_name:", st and st.get("manager_name"))

# RENAME (keep manager)
t0 = time.time()
r = s.put(f"{BASE}/api/org/settings/{sid}", json={"name": "TEST99_API_R", "description": "", "manager_user_id": mgr["id"]}, timeout=60)
print("rename status", r.status_code, r.text[:120])
st = find("TEST99_API_R")
print(f"immediately after rename ({time.time()-t0:.1f}s), renamed visible:", st is not None, "| old still there:", find("TEST99_API") is not None)

# MANAGER -> "" (empty string, as frontend sends)
r = s.put(f"{BASE}/api/org/settings/{sid}", json={"name": "TEST99_API_R", "description": "", "manager_user_id": ""}, timeout=60)
print("clear-manager status", r.status_code)
st = find("TEST99_API_R")
print("immediately after clearing manager, manager_name:", st and st.get("manager_name"))

# DB check for NULL vs ''
db = subprocess.run([sys.executable, "-c", f"""
import asyncio, sys
sys.path.insert(0, '/app/backend')
from utils import database
async def main():
    await database.connect()
    async with database.pool.acquire() as c:
        row = await c.fetchrow("SELECT name, manager_user_id, manager_user_id IS NULL AS is_null FROM org_settings WHERE id=$1", "{sid}")
        print(dict(row))
asyncio.run(main())
"""], capture_output=True, text=True, cwd="/app/backend")
print("DB CHECK:", db.stdout.strip() or db.stderr.strip()[-800:])

# cleanup
print("delete status", s.delete(f"{BASE}/api/org/settings/{sid}", timeout=60).status_code)
print("after delete, present:", find("TEST99_API_R") is not None)
print("final settings:", [x["name"] for x in structure()["settings"]])
