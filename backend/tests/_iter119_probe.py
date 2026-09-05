"""Probe: find signed_off meeting, doc upload, prep record for iter119 tests."""
import asyncio, asyncpg
from dotenv import dotenv_values
_be = dotenv_values("/app/backend/.env")

async def main():
    conn = await asyncpg.connect(_be["DATABASE_URL"], ssl="require")
    print("== signed_off meetings ==")
    rows = await conn.fetch(
        "SELECT id, title, status, transcript_id, analysis_id, org_id FROM meetings "
        "WHERE status IN ('signed_off','shared') AND transcript_id IS NOT NULL AND analysis_id IS NOT NULL "
        "ORDER BY created_at DESC LIMIT 5"
    )
    for r in rows:
        print(dict(r))
    print("== any in_review with mappings ==")
    rows = await conn.fetch(
        "SELECT id, title, status FROM meetings WHERE status='in_review' AND analysis_id IS NOT NULL LIMIT 3"
    )
    for r in rows:
        print(dict(r))
    print("== doc uploads ==")
    rows = await conn.fetch(
        "SELECT id, filename, status, org_id FROM supervision_uploads ORDER BY created_at DESC LIMIT 5"
    )
    for r in rows:
        print(dict(r))
    print("== meeting_prep ==")
    rows = await conn.fetch(
        "SELECT id, meeting_id, gen_status, org_id FROM meeting_prep ORDER BY created_at DESC LIMIT 5"
    )
    for r in rows:
        print(dict(r))
    print("== super admin org id ==")
    rows = await conn.fetch("SELECT id, name FROM organisations LIMIT 5")
    for r in rows:
        print(dict(r))
    await conn.close()

asyncio.run(main())
