import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

async def main():
    client = AsyncIOMotorClient('mongodb://localhost:27017')
    db = client['supervision_db']
    
    # Check prep meetings' orgs
    for mid in ["6a429c7ae8536bbda6a923ce", "6a6a33f3b671958551291c00"]:
        m = await db.meetings.find_one({"_id": ObjectId(mid)})
        if m:
            print(f"Meeting {mid}: org_id={m.get('org_id')}, title={m.get('title')}, status={m.get('status')}, analysis_id={m.get('analysis_id')}")
    
    # Find jane@sunrisecare.com org meetings with analysis
    user = await db.users.find_one({"email": "jane@sunrisecare.com"})
    if user:
        org_id = user.get('org_id')
        print(f"\nJane's org_id: {org_id}")
        meetings = []
        async for m in db.meetings.find({"org_id": org_id, "analysis_id": {"$exists": True, "$ne": None}}):
            meetings.append(m)
        print(f"Meetings with analysis ({len(meetings)}):")
        for m in meetings[:5]:
            print(str(m['_id']), m.get('title','?'), m.get('status'), m.get('analysis_id'))

asyncio.run(main())
