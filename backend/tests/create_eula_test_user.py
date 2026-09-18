"""Create a fresh throwaway user in Test Company org via super-admin API for EULA testing.

Usage: python create_eula_test_user.py [create|delete <user_id>|reset_eula <user_id>|show <user_id>]
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
ORG_ID = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"
SUPERADMIN = ("superadmin@1two.one", "TestPass123!")


async def _mfa_override(mail):
    conn = await asyncpg.connect(DSN, ssl="require")
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = datetime.now(timezone.utc) + timedelta(minutes=10)
    await conn.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, exp, mail)
    await conn.close()


def _sa_session():
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": SUPERADMIN[0], "password": SUPERADMIN[1]}, timeout=60)
    r.raise_for_status()
    d = r.json()
    if d.get("requires_mfa"):
        asyncio.run(_mfa_override(SUPERADMIN[0]))
        r2 = s.post(f"{BASE}/auth/verify-mfa", json={"mfa_session": d["mfa_session"], "code": "123456"}, timeout=60)
        r2.raise_for_status()
    return s


def create_user():
    s = _sa_session()
    stamp = int(datetime.now().timestamp())
    email = f"eula-test-{stamp}@example.com"
    pw = "EulaTest123!"
    payload = {
        "email": email,
        "password": pw,
        "name": "EULA Test User",
        "role": "attendee",
    }
    r = s.post(f"{BASE}/super-admin/orgs/{ORG_ID}/users", json=payload, timeout=60)
    print("status:", r.status_code, r.text[:400])
    if r.status_code >= 300:
        sys.exit(1)
    u = r.json()
    print(json.dumps({"email": email, "password": pw, "user_id": u.get("id") or u.get("user_id") or u}, indent=2))


def delete_user(uid):
    s = _sa_session()
    r = s.delete(f"{BASE}/super-admin/orgs/{ORG_ID}/users/{uid}", timeout=60)
    print("status:", r.status_code, r.text[:400])


async def _show(uid):
    conn = await asyncpg.connect(DSN, ssl="require")
    row = await conn.fetchrow(
        "SELECT id, email, role, must_change_password, eula_accepted_version, eula_decline_count, eula_accepted_at FROM users WHERE id=$1",
        uid)
    await conn.close()
    print(json.dumps({k: str(v) for k, v in dict(row).items()} if row else None, indent=2))


async def _reset_eula(uid):
    conn = await asyncpg.connect(DSN, ssl="require")
    await conn.execute(
        "UPDATE users SET eula_accepted_version=NULL, eula_decline_count=0, eula_accepted_at=NULL WHERE id=$1",
        uid)
    await conn.close()
    print("reset eula for", uid)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "create"
    if cmd == "create":
        create_user()
    elif cmd == "delete":
        delete_user(sys.argv[2])
    elif cmd == "show":
        asyncio.run(_show(sys.argv[2]))
    elif cmd == "reset_eula":
        asyncio.run(_reset_eula(sys.argv[2]))
    else:
        print("unknown cmd")
