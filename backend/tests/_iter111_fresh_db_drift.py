"""Fresh-DB drift check: are there live DB columns that no migration chunk would create?

Heuristic — for every column in every app table, check whether the column name
appears anywhere in the concatenated migrations/ source. Columns that don't
appear would be MISSING on a brand-new database bootstrapped only by the ledger.
"""
import asyncio
import os
from pathlib import Path

import asyncpg
from dotenv import dotenv_values

BE = dotenv_values("/app/backend/.env")
MIG = Path("/app/backend/migrations")

src = "".join(f.read_text() for f in sorted(MIG.glob("*.py")))
src += Path("/app/backend/init_db.py").read_text()

SKIP_TABLES = {"schema_migrations"}


async def main():
    conn = await asyncpg.connect(BE["DATABASE_URL"], ssl="require")
    try:
        tables = [r["tablename"] for r in await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
        total_missing = 0
        for t in tables:
            if t in SKIP_TABLES:
                continue
            if t not in src:
                print(f"TABLE NOT IN MIGRATIONS: {t}")
                total_missing += 1
                continue
            cols = [r["column_name"] for r in await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=$1", t)]
            missing = [c for c in cols if c not in src]
            if missing:
                print(f"{t}: MISSING FROM MIGRATIONS -> {missing}")
                total_missing += len(missing)
        print(f"\nTOTAL DRIFT ITEMS: {total_missing}")
    finally:
        await conn.close()


asyncio.run(main())
