"""Create/reset a test user with must_change_password=TRUE for frontend testing."""
import asyncio, sys, uuid
from datetime import datetime, timezone
import asyncpg, bcrypt
from dotenv import dotenv_values

be = dotenv_values("/app/backend/.env")

EMAIL = "mustchange-test@supervision.com"
TEMP_PW = "TempPass123!"

async def main():
    conn = await asyncpg.connect(be["DATABASE_URL"], ssl="require")
    h = bcrypt.hashpw(TEMP_PW.encode(), bcrypt.gensalt()).decode()
    now = datetime.now(timezone.utc)
    row = await conn.fetchrow("SELECT id, org_id FROM users WHERE email=$1", EMAIL)
    if row:
        await conn.execute(
            """UPDATE users SET password_hash=$1, must_change_password=TRUE,
               password_changed_at=$2, mfa_code_attempts=0, is_active=TRUE,
               supabase_password_set=FALSE WHERE email=$3""",
            h, now, EMAIL,
        )
        print("updated", dict(row))
    else:
        # pick any org
        org = await conn.fetchrow("SELECT id FROM organisations LIMIT 1")
        uid = str(uuid.uuid4())
        await conn.execute(
            """INSERT INTO users (id, email, name, role, org_id, password_hash,
               must_change_password, password_changed_at, is_active, created_at,
               supabase_password_set, supabase_migrated)
               VALUES ($1,$2,'MustChange Test','attendee',$3,$4,TRUE,$5,TRUE,$5,FALSE,FALSE)""",
            uid, EMAIL, org["id"], h, now,
        )
        print("created", uid, "in org", org["id"])
    try:
        await conn.execute("DELETE FROM login_attempts WHERE identifier LIKE $1", f"%{EMAIL}%")
    except Exception as e:
        print("attempts cleanup:", e)
    r = await conn.fetchrow("SELECT id, role, must_change_password, supabase_password_set FROM users WHERE email=$1", EMAIL)
    print("state:", dict(r))
    await conn.close()

asyncio.run(main())
