import asyncio
import asyncpg
from dotenv import dotenv_values

DSN = dotenv_values("/app/backend/.env")["DATABASE_URL"]
ORG = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"


async def main():
    c = await asyncpg.connect(DSN)
    print(await c.fetch(
        "SELECT status, count(*) , count(analysis_id) an, count(transcript_id) tr "
        "FROM meetings WHERE org_id=$1 GROUP BY status", ORG))
    print("residue meetings:", await c.fetchval("SELECT count(*) FROM meetings WHERE title LIKE 'TEST_iter104%'"))
    print("residue users:", await c.fetchval("SELECT count(*) FROM users WHERE email LIKE 'TEST_iter104%'"))
    print("residue teams:", await c.fetchval("SELECT count(*) FROM teams WHERE name LIKE 'TEST_iter104%'"))
    print("residue settings:", await c.fetchval("SELECT count(*) FROM org_settings WHERE name LIKE 'TEST_iter104%'"))
    print("residue mt:", await c.fetchval("SELECT count(*) FROM meeting_types WHERE name LIKE 'TEST_iter104%'"))
    print("residue docs:", await c.fetchval("SELECT count(*) FROM standards_documents WHERE label LIKE 'TEST_iter104%'"))
    print("residue topics:", await c.fetchval("SELECT count(*) FROM focus_topics WHERE text LIKE 'TEST_iter104%'"))
    print("residue schedules:", await c.fetchval("SELECT count(*) FROM schedules WHERE staff_user_id IS NULL"))
    await c.close()


asyncio.run(main())
