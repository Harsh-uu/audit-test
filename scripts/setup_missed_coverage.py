import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timezone

async def main():
    db = AsyncIOMotorClient('mongodb://localhost:27017')['supervision_db']
    
    q_missed = "missed_test_q_001"
    now = datetime.now(timezone.utc).isoformat()
    
    await db.meeting_prep.update_one(
        {"meeting_id": "6a46da6d1936c45e856ce791"},
        {"$set": {
            "sections": [{
                "section_id": "wellbeing",
                "label": "Wellbeing",
                "questions": [
                    {"id": "covered_q", "text": "Covered question about wellbeing", "included": True},
                    {"id": q_missed, "text": "MISSED: Walk me through a recent safeguarding situation", "included": True}
                ]
            }],
            "coverage_results": {
                "covered_q": {"status": "covered", "evidence": "discussed fully"},
                q_missed: {"status": "missed", "evidence": ""},
            },
            "coverage_checked_at": now,
        }},
    )
    print(f"Updated prep for Jane's meeting with 1 covered + 1 missed question")

asyncio.run(main())
