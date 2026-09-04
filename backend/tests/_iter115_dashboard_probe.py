"""Probe: /api/dashboard/ payload for jane vs user (UI dashboard source)."""
import os

import requests
from dotenv import dotenv_values

FE = dotenv_values("/app/frontend/.env")
API = (os.environ.get("REACT_APP_BACKEND_URL") or FE["REACT_APP_BACKEND_URL"]).rstrip("/") + "/api"


def login(email, pw):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=60)
    assert r.status_code == 200, (email, r.status_code, r.text[:200])
    return s


for email, pw in [("user@supervision.com", "AnotherNew789!"), ("jane@supervision.com", "JaneNew456!")]:
    s = login(email, pw)
    r = s.get(f"{API}/dashboard/", timeout=60)
    print("=" * 20, email, r.status_code)
    d = r.json()
    print("keys:", list(d.keys()))
    for k, v in d.items():
        if isinstance(v, list):
            print(f"  {k}: {len(v)} items")
            if k in ("meetings", "recent_meetings", "historical_meetings"):
                print("   ", [(m.get("id", "")[:8], m.get("title")) for m in v])
        else:
            print(f"  {k}: {v if not isinstance(v, dict) else list(v.keys())}")
