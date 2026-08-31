"""Iter105 probe: (1) real Supabase Storage put/get/delete round-trip,
(2) evidence_feedback FK constraints present in live DB,
(3) org-scoped tables FK cascade coverage for org deletion."""
import asyncio
import os
import sys

import asyncpg
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")
DSN = os.environ["DATABASE_URL"]


async def storage_roundtrip():
    from utils.supabase_storage import put_audio, get_audio, delete_audio
    path = "TEST_iter105/probe.webm"
    print("-- storage round-trip against REAL Supabase --")
    await put_audio(path, b"iter105-fake-audio-bytes", "audio/webm")
    print("put_audio OK")
    data, ct = await get_audio(path)
    print("get_audio OK:", len(data), "bytes", ct, "match=", data == b"iter105-fake-audio-bytes")
    await delete_audio(path)
    print("delete_audio OK (no exception)")
    try:
        data2, _ = await get_audio(path)
        print("!! FAIL: file still downloadable after delete, len=", len(data2))
    except Exception as e:
        print("verified gone: download raised", type(e).__name__, str(e)[:150])
    # bad path behaviour
    try:
        await delete_audio("TEST_iter105/does-not-exist-xyz.webm")
        print("delete_audio(nonexistent) -> no exception (idempotent)")
    except Exception as e:
        print("delete_audio(nonexistent) -> raised", type(e).__name__, str(e)[:200])


async def fks():
    conn = await asyncpg.connect(DSN, ssl="require")
    rows = await conn.fetch("""
        SELECT tc.table_name, kcu.column_name, rc.delete_rule, tc.constraint_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu ON tc.constraint_name=kcu.constraint_name
        JOIN information_schema.referential_constraints rc ON tc.constraint_name=rc.constraint_name
        WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema='public'
        ORDER BY tc.table_name, kcu.column_name""")
    print("\n-- total public FKs:", len(rows))
    for r in rows:
        if r["table_name"] == "evidence_feedback":
            print("evidence_feedback FK:", dict(r))
    org_fk = {r["table_name"] for r in rows if r["column_name"] == "org_id"}
    print("\ntables with org_id FK:", sorted(org_fk))
    tabs = [t["table_name"] for t in await conn.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'")]
    has_org = []
    for t in tabs:
        c = await conn.fetchval(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name=$1 AND column_name='org_id'", t)
        if c:
            has_org.append(t)
    print("tables WITH org_id column but NO org_id FK:", sorted(set(has_org) - org_fk))
    print("\nevidence_feedback columns:", [
        (r["column_name"], r["data_type"]) for r in await conn.fetch(
            "SELECT column_name,data_type FROM information_schema.columns WHERE table_name='evidence_feedback' ORDER BY ordinal_position")])
    await conn.close()


async def main():
    await fks()
    await storage_roundtrip()


asyncio.run(main())
