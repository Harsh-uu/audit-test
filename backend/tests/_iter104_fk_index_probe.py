"""Which FK child columns have no supporting index (each un-indexed FK forces a
seq scan of the child table on every parent DELETE/UPDATE of the referenced key)."""
import asyncio
import asyncpg
from dotenv import dotenv_values

DSN = dotenv_values("/app/backend/.env")["DATABASE_URL"]

Q = """
SELECT src.relname AS child, tgt.relname AS parent, con.confdeltype,
       (SELECT string_agg(a.attname, ',') FROM unnest(con.conkey) k
          JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k) AS col,
       (SELECT count(*) FROM pg_index i
          WHERE i.indrelid = con.conrelid AND (i.indkey::int2[])[0] = con.conkey[1]) AS idx_cnt,
       (SELECT n_live_tup FROM pg_stat_user_tables st WHERE st.relid = con.conrelid) AS rows
FROM pg_constraint con
JOIN pg_class src ON src.oid = con.conrelid
JOIN pg_class tgt ON tgt.oid = con.confrelid
WHERE con.contype='f'
ORDER BY idx_cnt, src.relname;
"""


async def main():
    c = await asyncpg.connect(DSN)
    for r in await c.fetch(Q):
        if r["idx_cnt"] == 0:
            print(f"NO INDEX: {r['child']}.{r['col']} -> {r['parent']} (rows={r['rows']})")
    await c.close()


asyncio.run(main())
