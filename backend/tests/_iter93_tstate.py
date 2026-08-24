"""Inspect transcript state for iter93 UI regression checks (read-only)."""
import asyncio, os, sys, json
import asyncpg
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
DSN = os.environ["DATABASE_URL"]
TID = "b3fa0ea3-b05a-413c-b0f6-767f1557e92c"


async def main():
    conn = await asyncpg.connect(DSN, ssl="require")
    r = await conn.fetchrow(
        "SELECT text, speaker_text, speaker_text_edited_by_name, speaker_text_edited_at FROM transcripts WHERE id=$1", TID)
    txt = r["text"]
    print("text len", len(txt), "| Tracy count:", txt.count("Tracy"), "| Tracey count:", txt.count("Tracey"))
    sp = r["speaker_text"] or ""
    print("speaker_text len", len(sp), "| edited_by:", r["speaker_text_edited_by_name"], r["speaker_text_edited_at"])
    print("speaker labels:", sorted({l.split(":")[0] for l in sp.split("\n") if ":" in l})[:10])
    print("sp Tracey count:", sp.count("Tracey"), "Tracy count:", sp.count("Tracy"))
    await conn.close()


asyncio.run(main())
