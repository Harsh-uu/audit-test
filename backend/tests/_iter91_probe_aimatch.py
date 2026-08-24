"""Probe: would _match_attendee_user_id map real AI-extracted assignee names
onto real meeting attendees? Reads existing analyses + their meetings."""
import asyncio, json, os, sys
from dotenv import load_dotenv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
import asyncpg
from routers.processing import _match_attendee_user_id, _jlist


async def main():
    c = await asyncpg.connect(os.environ["DATABASE_URL"], ssl="require")
    rows = await c.fetch(
        """SELECT m.id, m.title, m.attendees, a.actions, a.learning_needs
           FROM meetings m JOIN analyses a ON a.id = m.analysis_id LIMIT 20"""
    )
    total = matched = 0
    for r in rows:
        atts = _jlist(r["attendees"])
        names = [a.get("name") for a in atts]
        items = _jlist(r["actions"]) + _jlist(r["learning_needs"])
        assignees = [i.get("assigned_to") for i in items if i.get("assigned_to")]
        if not assignees:
            continue
        res = {n: _match_attendee_user_id(n, atts) for n in set(assignees)}
        total += len(assignees)
        matched += sum(1 for n in assignees if res.get(n))
        print(f"{r['title'][:45]:45} attendees={names} -> {res}")
    print(f"\nAI assignee names that would map to a user_id: {matched}/{total}")
    await c.close()

asyncio.run(main())
