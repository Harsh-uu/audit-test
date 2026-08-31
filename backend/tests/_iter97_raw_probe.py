"""Probe: read-after-write consistency for POST /org/settings -> GET /org/structure."""
import asyncio, sys, time, uuid
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
r = s.post(f"{API}/auth/login", json={"email": "admin@supervision.com", "password": "Admin123!"}, timeout=60)
d = r.json()
if d.get("requires_mfa"):
    asyncio.run(mfa("admin@supervision.com"))
    s.post(f"{API}/auth/verify-mfa", json={"mfa_session": d["mfa_session"], "code": "123456"}, timeout=60)

name = f"TEST_PROBE_{uuid.uuid4().hex[:6]}"
t0 = time.time()
cr = s.post(f"{API}/org/settings", json={"name": name}, timeout=60)
print("create", cr.status_code, cr.json(), f"{time.time()-t0:.2f}s")
for i in range(5):
    g = s.get(f"{API}/org/structure", timeout=60)
    names = [x["name"] for x in g.json().get("settings", [])]
    print(f"structure attempt {i}: present={name in names} count={len(names)} t={time.time()-t0:.2f}s")
    if name in names:
        break
    time.sleep(1.5)

# cleanup
sid = cr.json().get("id")
if sid:
    print("cleanup delete:", s.delete(f"{API}/org/settings/{sid}", timeout=60).status_code)
for extra in sys.argv[1:]:
    print("cleanup extra:", extra, s.delete(f"{API}/org/settings/{extra}", timeout=60).status_code)
