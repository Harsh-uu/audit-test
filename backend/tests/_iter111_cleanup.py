"""Cleanup of iteration-111 test residue."""
import asyncio
import os
import asyncpg
from dotenv import dotenv_values

BE = dotenv_values("/app/backend/.env")
MEETING_IDS = ["41ef4495-194b-4925-84ef-5ee2282f74a8"]


async def main():
    conn = await asyncpg.connect(BE["DATABASE_URL"], ssl="require")
    try:
        for mid in MEETING_IDS:
            for tbl in ("analyses", "transcripts", "audio_files", "meeting_prep",
                        "review_edits", "reviewer_comments", "audit_logs", "focus_topics"):
                try:
                    await conn.execute(f"DELETE FROM {tbl} WHERE meeting_id = $1::uuid", mid)
                except Exception as e:
                    print(f"  skip {tbl}: {str(e)[:70]}")
            r = await conn.execute("DELETE FROM meetings WHERE id = $1::uuid", mid)
            print("meeting", mid, r)

        print("meetings TEST_iter111:", await conn.execute(
            "DELETE FROM meetings WHERE title LIKE 'TEST_iter111%'"))
        print("teams TEST_iter111:", await conn.execute(
            "DELETE FROM teams WHERE name LIKE 'TEST_iter111%'"))
        print("org_settings TEST_iter111:", await conn.execute(
            "DELETE FROM org_settings WHERE name LIKE 'TEST_iter111%'"))

        for q, label in [
            ("SELECT count(*) FROM meetings WHERE title LIKE 'TEST_iter111%'", "meetings"),
            ("SELECT count(*) FROM teams WHERE name LIKE 'TEST_iter111%'", "teams"),
            ("SELECT count(*) FROM org_settings WHERE name LIKE 'TEST_iter111%'", "settings"),
        ]:
            print(f"remaining {label}:", await conn.fetchval(q))
        print("ledger rows:", await conn.fetchval("SELECT count(*) FROM schema_migrations"))
    finally:
        await conn.close()


asyncio.run(main())
