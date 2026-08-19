"""Shared login helper for iteration 79 tests (password + MFA DB bypass)."""
import asyncio
from datetime import datetime, timezone, timedelta

import asyncpg
import bcrypt
import requests
from dotenv import dotenv_values

be = dotenv_values("/app/backend/.env")
fe = dotenv_values("/app/frontend/.env")
BASE = fe["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = be["DATABASE_URL"]


async def _override(mail):
    conn = await asyncpg.connect(DSN, ssl="require")
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    await conn.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 "
        "WHERE email=$3", h, exp, mail)
    await conn.close()


def login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=60)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text[:200]}"
    data = r.json()
    if data.get("requires_mfa"):
        asyncio.run(_override(email))
        r2 = s.post(f"{BASE}/auth/verify-mfa",
                    json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=60)
        assert r2.status_code == 200, f"mfa failed {r2.status_code} {r2.text[:200]}"
    return s
