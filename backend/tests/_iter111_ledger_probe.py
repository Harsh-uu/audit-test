"""Probe: schema_migrations ledger contents + key RLS policies/indexes/FKs after the migration split."""
import asyncio
import os
import asyncpg
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

EXPECTED = [
    "001_core_tables", "002_schema_patches", "003_grants_indexes",
    "004_fk_constraints", "005_phase1_timestamptz", "006_phase2_uuid",
    "007_data_cleanup",
]


async def main():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"], ssl="require")
    try:
        rows = await conn.fetch("SELECT version, applied_at FROM schema_migrations ORDER BY version")
        versions = [r["version"] for r in rows]
        print("LEDGER ROWS:", len(versions))
        for r in rows:
            print("  ", r["version"], r["applied_at"])
        print("LEDGER_MATCH:", versions == EXPECTED)

        pol = await conn.fetch(
            "SELECT tablename, policyname, qual FROM pg_policies WHERE schemaname='public' ORDER BY tablename, policyname"
        )
        print("\nRLS POLICIES:", len(pol))
        for p in pol:
            print(f"  {p['tablename']}.{p['policyname']}")
        se = [p for p in pol if p["tablename"] == "standards_entries"]
        print("standards_entries policy qual:", se[0]["qual"] if se else "MISSING")

        idx = await conn.fetchval(
            "SELECT indexdef FROM pg_indexes WHERE tablename='meetings' AND indexname LIKE '%org_id_status%'"
        )
        print("\nmeetings composite index:", idx)

        fks = await conn.fetchval(
            "SELECT count(*) FROM information_schema.table_constraints WHERE constraint_type='FOREIGN KEY' AND table_schema='public'"
        )
        print("FK constraint count:", fks)

        tabs = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
        print("TABLES:", len(tabs), [t["tablename"] for t in tabs])

        # UUID codec sanity: are the id columns really uuid type?
        types = await conn.fetch("""
            SELECT table_name, column_name, data_type FROM information_schema.columns
            WHERE table_schema='public' AND column_name='id' AND table_name IN
            ('meetings','users','organisations','teams','org_settings','transcripts','analyses','standards_entries')
            ORDER BY table_name
        """)
        for t in types:
            print(f"  {t['table_name']}.id -> {t['data_type']}")
    finally:
        await conn.close()


asyncio.run(main())
