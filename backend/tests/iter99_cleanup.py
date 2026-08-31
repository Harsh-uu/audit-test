"""iter99 cleanup: remove TEST99 focus topics / org settings left by UI tests."""
import json
import subprocess
import sys

import requests
from dotenv import dotenv_values

BASE = dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"].rstrip("/")
out = subprocess.run([sys.executable, "/app/backend/tests/get_tokens.py", "admin@supervision.com", "Admin123!"],
                     capture_output=True, text=True, cwd="/app/backend")
s = requests.Session()
for k, v in json.loads(out.stdout.strip().splitlines()[-1])["cookies"].items():
    s.cookies.set(k, v)

topics = s.get(f"{BASE}/api/prep/focus-topics", timeout=60).json()
print("topics:", topics)
for t in topics:
    if "TEST99" in t.get("topic", "") or "TEST99" in str(t):
        print("delete topic", t["id"], s.delete(f"{BASE}/api/prep/focus-topics/{t['id']}", timeout=60).status_code)

struct = s.get(f"{BASE}/api/org/structure", timeout=60).json()
for st in struct["settings"]:
    if "TEST99" in st["name"]:
        print("delete setting", st["name"], s.delete(f"{BASE}/api/org/settings/{st['id']}", timeout=60).status_code)

print("final topics:", s.get(f"{BASE}/api/prep/focus-topics", timeout=60).json())
print("final settings:", [x["name"] for x in s.get(f"{BASE}/api/org/structure", timeout=60).json()["settings"]])
