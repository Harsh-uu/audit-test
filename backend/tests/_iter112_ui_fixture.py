"""Iter112: create a disposable user + reset token for the UI reset-password test."""
import asyncio
import os
import sys
import uuid

import asyncpg
import requests
from dotenv import dotenv_values

FE = dotenv_values("/app/frontend/.env")
BE = dotenv_values("/app/backend/.env")
BASE = FE["REACT_APP_BACKEND_URL"].rstrip("/")


async def token_for(email):
    c = await asyncpg.connect(BE["DATABASE_URL"])
    r = await c.fetchrow("SELECT token FROM password_reset_tokens WHERE email=$1", email)
    await c.close()
    return r["token"] if r else None


async def purge(email):
    c = await asyncpg.connect(BE["DATABASE_URL"])
    row = await c.fetchrow("SELECT id FROM users WHERE email=$1", email)
    if row:
        await c.execute("DELETE FROM password_reset_tokens WHERE email=$1", email)
        await c.execute("DELETE FROM login_attempts WHERE identifier=$1", email)
        await c.execute("DELETE FROM users WHERE id=$1", row["id"])
    await c.execute("DELETE FROM login_attempts")
    await c.close()
    if row:
        sys.path.insert(0, "/app/backend")
        os.environ["SUPABASE_URL"] = BE["SUPABASE_URL"]
        os.environ["SUPABASE_SERVICE_KEY"] = BE["SUPABASE_SERVICE_KEY"]
        try:
            from utils.supabase_auth import _get_admin_client
            _get_admin_client().auth.admin.delete_user(str(row["id"]))
        except Exception as e:
            print("supabase delete failed:", e)
    print("purged", email)


def main():
    cmd = sys.argv[1]
    if cmd == "create":
        email = f"test_iter112_ui_{uuid.uuid4().hex[:6]}@example.com"
        r = requests.post(f"{BASE}/api/auth/login",
                          json={"email": "admin@supervision.com", "password": "Admin123!"}, timeout=45)
        r.raise_for_status()
        cr = requests.post(f"{BASE}/api/admin/users", cookies=r.cookies, timeout=60,
                           json={"email": email, "name": "TEST Iter112 UI", "role": "attendee",
                                 "password": "InitialPass123!"})
        cr.raise_for_status()
        requests.post(f"{BASE}/api/auth/forgot-password", json={"email": email}, timeout=60)
        tok = asyncio.run(token_for(email))
        print(f"EMAIL={email}")
        print(f"TOKEN={tok}")
    elif cmd == "purge":
        asyncio.run(purge(sys.argv[2]))


main()
