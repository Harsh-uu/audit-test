"""Seed/cleanup a meeting_prep row with coverage_results on an in_review meeting
so the report page Prep Agenda tab renders sections + coverage badges + carry-forward banner.

Usage:
  python seed_prep_coverage.py seed <target_meeting_id>
  python seed_prep_coverage.py clean <target_meeting_id>
"""
import asyncio, json, os, sys, uuid
from datetime import datetime, timezone
import asyncpg
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
DSN = os.environ["DATABASE_URL"]
SRC = "91357f81-8092-4791-b7d5-e9b3ef646620"


async def seed(target):
    c = await asyncpg.connect(DSN)
    row = await c.fetchrow("select org_id, sections::text as s from meeting_prep where meeting_id=$1", SRC)
    sections = json.loads(row["s"])
    org_id = await c.fetchval("select org_id from meetings where id=$1", target)
    # build coverage: first question covered, second partial, rest missed
    coverage = {}
    flat = [q["id"] for sec in sections for q in (sec.get("questions") or [])]
    for i, qid in enumerate(flat):
        if i == 0:
            coverage[qid] = {"status": "covered", "evidence": "Discussed at length early in the session."}
        elif i == 1:
            coverage[qid] = {"status": "partial", "evidence": "Touched on briefly."}
        else:
            coverage[qid] = {"status": "missed"}
    await c.execute("delete from meeting_prep where meeting_id=$1", target)
    await c.execute(
        """insert into meeting_prep (id, meeting_id, org_id, sections, focus_topic, shared_with_attendees,
             generated_at, coverage_results, coverage_checked_at, created_at, updated_at, gen_status)
           values ($1,$2,$3,$4::jsonb,$5,true,now(),$6::jsonb,now(),now(),now(),'done')""",
        str(uuid.uuid4()), target, org_id, json.dumps(sections), "TEST_Caseload pressure",
        json.dumps(coverage),
    )
    print("seeded prep for", target, "questions:", len(flat), "missed:", len(flat) - 2)
    await c.close()


async def clean(target):
    c = await asyncpg.connect(DSN)
    await c.execute("delete from meeting_prep where meeting_id=$1", target)
    print("cleaned prep for", target)
    await c.close()


if __name__ == "__main__":
    cmd, target = sys.argv[1], sys.argv[2]
    asyncio.run(seed(target) if cmd == "seed" else clean(target))
