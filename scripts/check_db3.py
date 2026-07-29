import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

async def main():
    client = AsyncIOMotorClient('mongodb://localhost:27017')
    db = client['supervision_db']
    
    # Meeting with prep 6a6a33f3b671958551291c00
    m = await db.meetings.find_one({"_id": ObjectId("6a6a33f3b671958551291c00")})
    if m:
        print('Meeting 6a6a33f3b671958551291c00:', m.get('title'), m.get('status'), 'analysis_id:', m.get('analysis_id'))
    
    # Prep for this meeting
    prep = await db.meeting_prep.find_one({"meeting_id": "6a6a33f3b671958551291c00"})
    if prep:
        qs = []
        for s in prep.get('sections',[]):
            for q in s.get('questions',[]):
                qs.append({'id': q.get('id'), 'text': q.get('text','')[:60], 'included': q.get('included', True)})
        print('Questions:', qs[:4])

asyncio.run(main())
