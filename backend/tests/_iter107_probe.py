"""Probe: does the new timestamptz text codec survive with_org (SET LOCAL ROLE) and with_admin?"""
import asyncio, os, sys
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
import database


async def main():
    await database.create_pool()
    ORG = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"
    async with database.with_admin() as conn:
        r = await conn.fetchrow("SELECT id, created_at, updated_at FROM meetings ORDER BY created_at DESC LIMIT 1")
        print("with_admin:", type(r["created_at"]).__name__, repr(r["created_at"]))
        r2 = await conn.fetchrow("SELECT now() as n")
        print("with_admin now():", type(r2["n"]).__name__, repr(r2["n"]))
    async with database.with_org(ORG) as conn:
        r = await conn.fetchrow("SELECT id, created_at, attendees FROM meetings ORDER BY created_at DESC LIMIT 1")
        print("with_org created_at:", type(r["created_at"]).__name__, repr(r["created_at"]))
        print("with_org attendees type:", type(r["attendees"]).__name__)
    # schema check of the 52 columns + intentionally-excluded ones
    async with database.with_admin() as conn:
        rows = await conn.fetch(
            """SELECT table_name, column_name, data_type FROM information_schema.columns
               WHERE table_schema='public' AND (column_name LIKE '%%_at' OR column_name IN
               ('timestamp','start_date','active_month','date','parsed_at'))
               ORDER BY table_name, column_name"""
        )
        text_left = [(r["table_name"], r["column_name"], r["data_type"]) for r in rows if r["data_type"] == "text"]
        tstz = [r for r in rows if "timestamp" in r["data_type"]]
        print("TIMESTAMPTZ count:", len(tstz))
        print("still TEXT:", text_left)
        # unexpected nulls
        n = await conn.fetchval("SELECT count(*) FROM meetings WHERE created_at IS NULL")
        print("meetings null created_at:", n)
    await database.close_pool()

asyncio.run(main())
