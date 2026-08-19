"""Temporarily inject a timestamped speaker_text into meeting 0383953a, export both
PDFs, verify speaker labels, then restore the original speaker_text."""
import asyncio, io, sys
import asyncpg
from dotenv import dotenv_values
from pypdf import PdfReader

sys.path.insert(0, "/app/backend/tests")
from _iter79_login import login, BASE

DSN = dotenv_values("/app/backend/.env")["DATABASE_URL"]
MID = "0383953a-9a17-4f7f-9924-ed5ec30b42b6"
TS_TEXT = """[00:02] Sarah Thompson: Hi Jane, thanks for making time today.
[00:07] Jane Doe: No problem at all. Shall we start with the medication issue?
this is a continuation line of Jane's turn without a speaker label.
[00:15] Sarah Thompson: Yes please, and then training needs."""


async def swap(new_text):
    conn = await asyncpg.connect(DSN, ssl="require")
    row = await conn.fetchrow(
        "SELECT t.id, t.speaker_text FROM transcripts t JOIN meetings m ON m.transcript_id=t.id WHERE m.id=$1", MID)
    old = row["speaker_text"]
    if new_text is not None:
        await conn.execute("UPDATE transcripts SET speaker_text=$1 WHERE id=$2", new_text, row["id"])
    await conn.close()
    return old


def text_of(resp):
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(resp.content)).pages)


old = asyncio.run(swap(TS_TEXT))
try:
    s = login("admin@supervision.com", "Admin123!")
    for ep in ("export-pdf", "export-transcript"):
        r = s.get(f"{BASE}/review/{MID}/{ep}", timeout=180)
        t = text_of(r)
        idx = t.find("Hi Jane")
        print("=" * 20, ep, r.status_code)
        print(t[max(0, idx - 400):idx + 900])
finally:
    asyncio.run(swap(old))
    print("restored original speaker_text (len=%s)" % (len(old or "")))
