"""iter93: verify /api/review/{id}/find-replace keeps transcript.text and speaker_text in sync.

Uses manager cookies from get_tokens.py output.
"""
import json
import os

import asyncio
import asyncpg
import requests
from dotenv import dotenv_values, load_dotenv

load_dotenv("/app/backend/.env")
BASE = dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"].rstrip("/")
MID = "2f1cc088-0687-48b9-9f40-1dabb5285640"
TID = "b3fa0ea3-b05a-413c-b0f6-767f1557e92c"
cookies = json.load(open("/app/test_reports/.iter93_tokens.json"))["cookies"]


async def counts(word):
    conn = await asyncpg.connect(os.environ["DATABASE_URL"], ssl="require")
    r = await conn.fetchrow("SELECT text, speaker_text FROM transcripts WHERE id=$1", TID)
    await conn.close()
    return r["text"].count(word), (r["speaker_text"] or "").count(word)


def call(find, replace, replace_one=False, occurrence_index=0):
    resp = requests.post(
        f"{BASE}/api/review/{MID}/find-replace",
        json={"find": find, "replace": replace, "replace_one": replace_one, "occurrence_index": occurrence_index},
        cookies=cookies, timeout=60,
    )
    print("  ->", resp.status_code, resp.text[:200])
    return resp


async def main():
    print("before:", await counts("Tracy"), await counts("QAWORDX"))
    print("replace_all Tracy -> QAWORDX")
    call("Tracy", "QAWORDX")
    t, s = await counts("QAWORDX")
    print(f"  text QAWORDX={t}  speaker_text QAWORDX={s}  (both should be >0 and equal-ish)")
    print("replace_one QAWORDX -> Tracy")
    call("QAWORDX", "Tracy", replace_one=True, occurrence_index=0)
    t2, s2 = await counts("QAWORDX")
    print(f"  after replace_one: text QAWORDX={t2} speaker_text QAWORDX={s2}")
    print("cleanup: replace_all QAWORDX -> Tracy")
    call("QAWORDX", "Tracy")
    t3, s3 = await counts("QAWORDX")
    tr = await counts("Tracy")
    print(f"  final QAWORDX text={t3} sp={s3} | Tracy counts (text, sp) = {tr}")
    assert t3 == 0, "residual QAWORDX in transcript.text"
    if s3 != 0:
        print("BUG: speaker_text still contains QAWORDX after replace_all -> find-replace does not sync speaker_text")


asyncio.run(main())
