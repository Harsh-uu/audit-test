"""Probe: compare meetings visible to user@ vs jane@ via API, and DB ownership."""
import asyncio
import os
import sys

import asyncpg
import requests
from dotenv import dotenv_values

FE = dotenv_values("/app/frontend/.env")
BE = dotenv_values("/app/backend/.env")
API = (os.environ.get("REACT_APP_BACKEND_URL") or FE["REACT_APP_BACKEND_URL"]).rstrip("/") + "/api"
DSN = BE["DATABASE_URL"]


def login(email, pw):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=60)
    assert r.status_code == 200, (email, r.status_code, r.text[:200])
    return s


def meetings(s):
    r = s.get(f"{API}/meetings/?limit=500", timeout=60)
    p = r.json()
    return p if isinstance(p, list) else p.get("meetings", [])


async def main():
    u = login("user@supervision.com", "AnotherNew789!")
    j = login("jane@supervision.com", "JaneNew456!")
    um, jm = meetings(u), meetings(j)
    uid = u.get(f"{API}/auth/me", timeout=60).json()["id"]
    jid = j.get(f"{API}/auth/me", timeout=60).json()["id"]
    print("user id", uid, "count", len(um))
    print("jane id", jid, "count", len(jm))
    print("user titles", [(m["id"][:8], m.get("title")) for m in um])
    print("jane titles", [(m["id"][:8], m.get("title")) for m in jm])
    print("overlap", len({m["id"] for m in um} & {m["id"] for m in jm}))

    conn = await asyncpg.connect(DSN, ssl="require")
    try:
        for m in jm:
            row = await conn.fetchrow(
                "SELECT id, title, created_by, attendees::text, shared_with::text FROM meetings WHERE id=$1::uuid",
                m["id"])
            own = (str(row["created_by"]) == jid) or (jid in (row["attendees"] or "")) or (jid in (row["shared_with"] or ""))
            print(f"jane meeting {row['id']} '{row['title']}' created_by={row['created_by']} jane_owned={own}")
            if not own:
                print("   attendees:", row["attendees"], " shared_with:", row["shared_with"])
    finally:
        await conn.close()

asyncio.run(main())
