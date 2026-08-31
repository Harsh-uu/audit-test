"""Probe: list all FK constraints in the DB with their delete actions + orphan checks."""
import asyncio
import asyncpg
from dotenv import dotenv_values

DSN = dotenv_values("/app/backend/.env")["DATABASE_URL"]

Q = """
SELECT con.conname, src.relname AS child, tgt.relname AS parent,
       con.confdeltype,
       (SELECT string_agg(a.attname, ',') FROM unnest(con.conkey) k
          JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k) AS cols
FROM pg_constraint con
JOIN pg_class src ON src.oid = con.conrelid
JOIN pg_class tgt ON tgt.oid = con.confrelid
JOIN pg_namespace n ON n.oid = src.relnamespace
WHERE con.contype = 'f' AND n.nspname = 'public'
ORDER BY src.relname, con.conname;
"""

ACT = {"a": "NO ACTION", "r": "RESTRICT", "c": "CASCADE", "n": "SET NULL", "d": "SET DEFAULT"}


async def main():
    conn = await asyncpg.connect(DSN, ssl="require")
    rows = await conn.fetch(Q)
    print(f"TOTAL FKs: {len(rows)}")
    for r in rows:
        print(f"  {r['child']}.{r['cols']} -> {r['parent']}  ON DELETE {ACT[(r['confdeltype'].decode() if isinstance(r['confdeltype'], bytes) else r['confdeltype'])]}  ({r['conname']})")

    # orphan checks
    print("\nORPHAN CHECKS")
    checks = [
        ("audit_logs", "meeting_id", "meetings"),
        ("jobs", "meeting_id", "meetings"),
        ("invitations", "user_id", "users"),
        ("meetings", "sign_off_manager_id", "users"),
        ("meetings", "created_by", "users"),
    ]
    for tbl, col, parent in checks:
        n = await conn.fetchval(
            f"SELECT count(*) FROM {tbl} t WHERE t.{col} IS NOT NULL "
            f"AND NOT EXISTS (SELECT 1 FROM {parent} p WHERE p.id = t.{col})")
        print(f"  {tbl}.{col} orphans: {n}")
    await conn.close()


asyncio.run(main())
