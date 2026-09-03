"""Iter113 helper: exercise admin MFA toggle (enable/disable) end-to-end via API.

Usage: python3 tests/_iter113_mfa_toggle.py enable|disable|state
"""
import asyncio
import sys
from datetime import datetime, timedelta, timezone

import asyncpg
import bcrypt
import requests
from dotenv import dotenv_values

BE = dotenv_values("/app/backend/.env")
BASE = dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"].rstrip("/")
EMAIL, PW = "admin@supervision.com", "Admin123!"


async def _set_code():
    c = await asyncpg.connect(BE["DATABASE_URL"])
    await c.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2 WHERE email=$3",
        bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode(),
        datetime.now(timezone.utc) + timedelta(minutes=10), EMAIL)
    await c.close()


async def _state():
    c = await asyncpg.connect(BE["DATABASE_URL"])
    r = await c.fetchrow("SELECT mfa_enabled FROM users WHERE email=$1", EMAIL)
    await c.close()
    return r["mfa_enabled"]


async def _clear():
    c = await asyncpg.connect(BE["DATABASE_URL"])
    await c.execute("DELETE FROM login_attempts")
    await c.close()


def session():
    asyncio.run(_clear())
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": EMAIL, "password": PW}, timeout=60)
    body = r.json()
    if body.get("requires_mfa"):
        asyncio.run(_set_code())
        vr = s.post(f"{BASE}/api/auth/verify-mfa",
                    json={"mfa_session": body["mfa_session"], "code": "123456"}, timeout=60)
        print("verify-mfa:", vr.status_code)
    else:
        print("login (no mfa):", r.status_code)
    return s


def main():
    cmd = sys.argv[1]
    if cmd == "state":
        print("db mfa_enabled:", asyncio.run(_state()))
        return
    s = session()
    rc = s.post(f"{BASE}/api/auth/request-mfa-code", json={}, timeout=60)
    print("request-mfa-code:", rc.status_code, rc.text[:150])
    asyncio.run(_set_code())
    enable = cmd == "enable"
    tr = s.post(f"{BASE}/api/auth/toggle-mfa", json={"code": "123456", "enable": enable}, timeout=60)
    print("toggle-mfa:", tr.status_code, tr.text[:200])
    print("db mfa_enabled:", asyncio.run(_state()))
    me = s.get(f"{BASE}/api/auth/me", timeout=60)
    print("me mfa_enabled:", me.json().get("mfa_enabled"))
    print("cookies:", {k: v for k, v in s.cookies.items() if k.startswith("supervision")})


main()
