import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

async def main():
    client = AsyncIOMotorClient('mongodb://localhost:27017')
    db = client['supervision_db']
    
    meetings = []
    async for m in db.meetings.find({"status": {"$in": ["signed_off","in_review","reviewed"]}}):
        meetings.append(m)
    print('=== SIGNED OFF/IN REVIEW MEETINGS ===')
    for m in meetings[:5]:
        print(str(m['_id']), m.get('title','?'), m.get('status'), m.get('analysis_id'))
    
    prep = await db.meeting_prep.find_one({"meeting_id": "6a429c7ae8536bbda6a923ce"})
    if prep:
        prep['_id'] = str(prep['_id'])
        print('\nPrep sections:', [s.get('label') for s in prep.get('sections',[])])
        qs = []
        for s in prep.get('sections',[]):
            for q in s.get('questions',[]):
                qs.append({'id': q.get('id'), 'text': q.get('text','')[:50]})
        print('Questions sample:', qs[:3])
    
    m2 = await db.meetings.find_one({"_id": ObjectId("6a429c7ae8536bbda6a923ce")})
    if m2:
        print('Meeting:', m2.get('title'), m2.get('status'), m2.get('analysis_id'))

asyncio.run(main())
