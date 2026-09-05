import asyncio, asyncpg
from dotenv import dotenv_values
BE = dotenv_values("/app/backend/.env")

async def main():
    c = await asyncpg.connect(BE["DATABASE_URL"], ssl="require")
    rows = await c.fetch("SELECT status, count(*) FROM meetings GROUP BY status ORDER BY 2 DESC")
    print("meeting statuses:", [dict(r) for r in rows])
    so = await c.fetch("SELECT id, title, org_id, status, analysis_id IS NOT NULL a, transcript_id IS NOT NULL t FROM meetings WHERE status='signed_off' LIMIT 5")
    print("signed_off:", [dict(r) for r in so])
    jobs = await c.fetch("SELECT status, count(*) FROM jobs GROUP BY status")
    print("jobs:", [dict(r) for r in jobs])
    recent = await c.fetch("SELECT id, meeting_id, status, attempts, error, created_at, updated_at FROM jobs ORDER BY created_at DESC LIMIT 5")
    for r in recent:
        print("job:", dict(r))
    await c.close()

asyncio.run(main())
