"""Login helper: performs password login, bypasses MFA via DB override, prints cookies as JSON.

Usage: python get_tokens.py <email> <password>
"""
import asyncio, json, os, sys
from datetime import datetime, timezone, timedelta

import asyncpg
import bcrypt
import requests
from dotenv import dotenv_values

be = dotenv_values("/app/backend/.env")
fe = dotenv_values("/app/frontend/.env")
BASE = fe["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = be["DATABASE_URL"]

email, password = sys.argv[1], sys.argv[2]


async def override(mail):
    conn = await asyncpg.connect(DSN, ssl="require")
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    await conn.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, exp, mail)
    await conn.close()


s = requests.Session()
r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=60)
if r.status_code != 200:
    print(json.dumps({"error": r.status_code, "body": r.text[:300]}))
    sys.exit(1)
data = r.json()
if data.get("requires_mfa"):
    asyncio.run(override(email))
    r2 = s.post(f"{BASE}/auth/verify-mfa", json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=60)
    if r2.status_code != 200:
        print(json.dumps({"error": r2.status_code, "body": r2.text[:300]}))
        sys.exit(1)
cookies = {c.name: c.value for c in s.cookies}
me = s.get(f"{BASE}/auth/me", timeout=60)
print(json.dumps({"cookies": cookies, "me_status": me.status_code, "me": me.json() if me.status_code == 200 else me.text[:200]}))
