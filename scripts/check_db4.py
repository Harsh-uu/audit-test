import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

async def main():
    client = AsyncIOMotorClient('mongodb://localhost:27017')
    db = client['supervision_db']
    
    # Find manager@supervision.com user and their org
    user = await db.users.find_one({"email": "manager@supervision.com"})
    if user:
        org_id = user.get('org_id')
        print(f"Manager org_id: {org_id}")
        
        # Meetings in this org with analysis
        meetings = []
        async for m in db.meetings.find({"org_id": org_id, "analysis_id": {"$exists": True, "$ne": None}}):
            meetings.append(m)
        print(f"\nMeetings with analysis in manager's org ({org_id}):")
        for m in meetings[:5]:
            print(str(m['_id']), m.get('title','?'), m.get('status'), m.get('analysis_id'))
        
        # All meetings in this org
        all_meetings = []
        async for m in db.meetings.find({"org_id": org_id}):
            all_meetings.append(m)
        print(f"\nAll meetings in org ({len(all_meetings)} total):")
        for m in all_meetings[:10]:
            print(str(m['_id']), m.get('title','?'), m.get('status'))
    
asyncio.run(main())
