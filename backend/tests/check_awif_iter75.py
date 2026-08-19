"""Iteration 75 — AWIF Wales seed repair path check (run before/after a backend restart)."""
import asyncio
import json

import asyncpg
from dotenv import dotenv_values

DSN = dotenv_values("/app/backend/.env")["DATABASE_URL"]


async def main():
    c = await asyncpg.connect(DSN, ssl="require")
    for typ in ("awif", "scw", "ciw"):
        rows = await c.fetch(
            "SELECT jsonb_typeof(keywords) kw, jsonb_typeof(sub_outcomes) so, "
            "jsonb_typeof(key_questions) kq, COUNT(*) n FROM standards_entries "
            "WHERE type=$1 AND jurisdiction='wales' AND is_system=TRUE "
            "GROUP BY 1,2,3", typ)
        print(typ, [dict(r) for r in rows])
    tot = await c.fetch(
        "SELECT type, jsonb_typeof(keywords) kw, COUNT(*) n FROM standards_entries "
        "GROUP BY 1,2 ORDER BY 1,2")
    print("all types keywords:", [(r["type"], r["kw"], r["n"]) for r in tot])
    await c.close()


asyncio.run(main())
