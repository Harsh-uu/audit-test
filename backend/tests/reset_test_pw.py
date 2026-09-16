"""Reset a test user's password hash and clear login attempt lockouts (test-data maintenance).

Usage: python reset_test_pw.py <email> <password>
"""
import asyncio, os, sys
from datetime import datetime, timezone
import asyncpg, bcrypt
from dotenv import dotenv_values

be = dotenv_values("/app/backend/.env")


async def main():
    email, pw = sys.argv[1], sys.argv[2]
    conn = await asyncpg.connect(be["DATABASE_URL"], ssl="require")
    h = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    now = datetime.now(timezone.utc)
    res = await conn.execute(
        "UPDATE users SET password_hash=$1, must_change_password=FALSE, password_changed_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, now, email)
    try:
        await conn.execute("DELETE FROM login_attempts WHERE identifier LIKE $1", f"%{email}%")
    except Exception as e:
        print("attempts cleanup:", e)
    row = await conn.fetchrow("SELECT id, role, org_id, is_active FROM users WHERE email=$1", email)
    print(res, dict(row) if row else "no user")
    await conn.close()

asyncio.run(main())
