"""Probe: rescan-evidence / regenerate-summary 400 reasons, on meetings that DO have a transcript."""
import asyncio, json
import asyncpg, requests
from dotenv import dotenv_values
FE = dotenv_values("/app/frontend/.env"); BE = dotenv_values("/app/backend/.env")
API = FE["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
T = 240

async def candidates():
    c = await asyncpg.connect(BE["DATABASE_URL"], ssl="require")
    rows = await c.fetch("""SELECT m.id, m.title, m.status, length(t.text) tlen
                            FROM meetings m JOIN transcripts t ON t.id=m.transcript_id
                            WHERE m.status IN ('in_review','reviewed') ORDER BY tlen DESC NULLS LAST LIMIT 5""")
    await c.close()
    return [dict(r) for r in rows]

s = requests.Session()
r = s.post(f"{API}/auth/login", json={"email": "admin@supervision.com", "password": "Admin123!"}, timeout=60)
print("login", r.status_code)
cands = asyncio.run(candidates())
print("candidates:", cands)
for cand in cands[:2]:
    mid = str(cand["id"])
    for path in ("rescan-evidence", "regenerate-summary", "scan-pii"):
        resp = s.post(f"{API}/review/{mid}/{path}", json={}, timeout=T)
        print(f"{cand['title'][:35]} tlen={cand['tlen']} {path}: {resp.status_code} {resp.text[:250]}")
