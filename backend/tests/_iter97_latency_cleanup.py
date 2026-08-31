"""Latency probe + cleanup of iteration-97 TEST_ data."""
import asyncio, time
from datetime import datetime, timezone, timedelta
import asyncpg, bcrypt, requests
from dotenv import dotenv_values

BE = dotenv_values("/app/backend/.env"); FE = dotenv_values("/app/frontend/.env")
API = FE["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = BE["DATABASE_URL"]


async def mfa(email):
    c = await asyncpg.connect(DSN, ssl="require")
    await c.execute("UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
                    bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode(),
                    (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(), email)
    await c.close()


s = requests.Session()
d = s.post(f"{API}/auth/login", json={"email": "admin@supervision.com", "password": "Admin123!"}, timeout=60).json()
if d.get("requires_mfa"):
    asyncio.run(mfa("admin@supervision.com"))
    s.post(f"{API}/auth/verify-mfa", json={"mfa_session": d["mfa_session"], "code": "123456"}, timeout=60)

for path in ["/org/structure", "/org/settings", "/admin/users", "/prep/focus-topics",
             "/admin/standards/documents", "/admin/team-insights", "/admin/team-insights/registers"]:
    ts = []
    for _ in range(3):
        t = time.time(); r = s.get(f"{API}{path}", timeout=120); ts.append(round(time.time() - t, 2))
    print(f"{path:35s} status={r.status_code} times={ts}")

# ── cleanup TEST_UI_* branches / teams / focus topics ─────────────────────────
settings = s.get(f"{API}/org/settings", timeout=60).json()
for st in settings:
    if st["name"].startswith("TEST_UI") or st["name"].startswith("TEST_PROBE") or st["name"].startswith("TEST_Branch"):
        print("delete setting", st["name"], s.delete(f"{API}/org/settings/{st['id']}", timeout=60).status_code)

struct = s.get(f"{API}/org/structure", timeout=60).json()
for st in struct.get("settings", []):
    for t in st.get("teams", []):
        if t["name"].startswith("TEST_"):
            print("delete team", t["name"], s.delete(f"{API}/org/teams/{t['id']}", timeout=60).status_code)

for t in s.get(f"{API}/prep/focus-topics", timeout=60).json():
    if str(t.get("topic", "")).startswith("TEST_"):
        print("delete topic", t["topic"], s.delete(f"{API}/prep/focus-topics/{t['id']}", timeout=60).status_code)


async def orphan_cleanup():
    c = await asyncpg.connect(DSN, ssl="require")
    print("orphan teams:", await c.fetch("DELETE FROM teams WHERE name LIKE 'TEST_%' RETURNING name"))
    print("remaining settings:", [r["name"] for r in await c.fetch("SELECT name FROM org_settings")])
    print("remaining teams:", [(r["name"], r["setting_id"]) for r in await c.fetch("SELECT name, setting_id FROM teams")])
    print("remaining topics:", [r["text"] for r in await c.fetch("SELECT text FROM focus_topics")])
    await c.close()

asyncio.run(orphan_cleanup())
