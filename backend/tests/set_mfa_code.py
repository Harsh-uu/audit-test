"""Set MFA code to 123456 for a given email (test helper)."""
import asyncio
import sys
from datetime import datetime, timedelta, timezone

import asyncpg
import bcrypt
from dotenv import dotenv_values

be = dotenv_values("/app/backend/.env")
email = sys.argv[1]


async def main():
    c = await asyncpg.connect(be["DATABASE_URL"], ssl="require")
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    await c.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, exp, email)
    await c.close()
    print("mfa code set to 123456 for", email)


asyncio.run(main())
