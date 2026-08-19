"""One-off: inspect/repair the Test Company organisations.branding value mangled by
an iteration-75 test teardown that round-tripped it through a jsonb codec."""
import asyncio
import json
import sys

import asyncpg
from dotenv import dotenv_values

DSN = dotenv_values("/app/backend/.env")["DATABASE_URL"]
ORG = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"


async def main():
    c = await asyncpg.connect(DSN, ssl="require")
    t, raw = await c.fetchrow("SELECT jsonb_typeof(branding), branding::text FROM organisations WHERE id=$1", ORG)
    print("typeof:", t)
    print("raw:", raw[:300] if raw else raw)
    if t == "string" and "--fix" in sys.argv:
        v = json.loads(raw)
        while isinstance(v, str):
            v = json.loads(v)
        await c.execute("UPDATE organisations SET branding=$1::jsonb WHERE id=$2", json.dumps(v), ORG)
        t2 = await c.fetchval("SELECT jsonb_typeof(branding) FROM organisations WHERE id=$1", ORG)
        print("after fix typeof:", t2, await c.fetchval("SELECT branding::text FROM organisations WHERE id=$1", ORG))
    await c.close()


asyncio.run(main())
