import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    client = AsyncIOMotorClient('mongodb://localhost:27017')
    db = client['supervision_db']
    
    preps = await db.meeting_prep.find({}).to_list(10)
    print('=== PREP RECORDS ===')
    for p in preps:
        mid = p.get('meeting_id')
        has_cov = bool(p.get('coverage_results'))
        sections = len(p.get('sections', []))
        print(f"meeting_id={mid} | gen_status={p.get('gen_status')} | sections={sections} | has_coverage={has_cov}")
    
    meetings = []
    async for m in db.meetings.find({"analysis_id": {"$exists": True}}):
        meetings.append(m)
        if len(meetings) >= 5:
            break
    print('\n=== MEETINGS WITH ANALYSIS ===')
    for m in meetings:
        print(str(m['_id']), m.get('title','?'), m.get('status'), m.get('org_id'))

asyncio.run(main())
