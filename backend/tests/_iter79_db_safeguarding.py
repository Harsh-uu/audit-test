import asyncio, json, re
import asyncpg
from dotenv import dotenv_values

DSN = dotenv_values("/app/backend/.env")["DATABASE_URL"]

async def main():
    conn = await asyncpg.connect(DSN, ssl="require")
    rows = await conn.fetch("SELECT meeting_id, risks FROM analyses")
    bad = []
    total = 0
    for r in rows:
        raw = r["risks"]
        if not raw:
            continue
        s = raw if isinstance(raw, str) else json.dumps(raw)
        total += 1
        for m in re.finditer(r"[Pp]otential safeguarding (?:indicator|breach|concern)s?", s):
            bad.append((str(r["meeting_id"]), m.group(0)))
        for m in re.finditer(r"Potential safeguarding[^\"]{0,60}", s):
            pass
    print("analyses with risks:", total)
    print("old-phrasing occurrences:", len(bad))
    for b in bad[:10]:
        print("  ", b)
    hits = await conn.fetch("SELECT meeting_id, risks::text FROM analyses WHERE risks::text ILIKE '%Potential safeguarding%'")
    print("rows containing 'Potential safeguarding':", len(hits))
    for h in hits[:5]:
        txt = h[1]
        for m in re.finditer(r"Potential safeguarding[^\"]{0,80}", txt):
            print("   >", m.group(0)[:110])
    await conn.close()

asyncio.run(main())
