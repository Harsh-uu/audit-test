"""Iteration 75 — verify no test residue left behind."""
import asyncio

import asyncpg
from dotenv import dotenv_values

DSN = dotenv_values("/app/backend/.env")["DATABASE_URL"]
ORG = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"


async def main():
    c = await asyncpg.connect(DSN, ssl="require")
    print("TEST_ITER75 meetings:", await c.fetchval("SELECT count(*) FROM meetings WHERE title LIKE 'TEST_ITER75%'"))
    print("TEST_ITER75 standards:", await c.fetchval("SELECT count(*) FROM standards_entries WHERE reference LIKE 'TEST_ITER75%'"))
    print("TEST_ITER75 docs:", await c.fetchval("SELECT count(*) FROM standards_documents WHERE label LIKE 'TEST_ITER75%'"))
    print("orphan analyses/transcripts:", await c.fetchval(
        "SELECT count(*) FROM analyses WHERE summary LIKE 'TEST_ITER75%' OR summary='TEST dedicated summary'"))
    print("branding:", await c.fetchrow("SELECT jsonb_typeof(branding) t, branding::text FROM organisations WHERE id=$1", ORG))
    print("template settings:", await c.fetchrow(
        "SELECT jsonb_typeof(data) t, data->>'name' nm FROM settings WHERE id=$1", f"supervision_template:{ORG}"))
    await c.close()


asyncio.run(main())
