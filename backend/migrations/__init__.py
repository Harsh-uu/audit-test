"""
Versioned schema migration runner.

Each mNNN_*.py module exposes VERSION (str) and an async up(conn) callable.
On every backend boot, run_migrations() applies only the modules whose
VERSION is not yet recorded in the schema_migrations ledger table, instead
of re-evaluating the entire schema history on every startup.
"""
import logging

from . import (
    m001_core_tables,
    m002_schema_patches,
    m003_grants_indexes,
    m004_fk_constraints,
    m005_phase1_timestamptz,
    m006_phase2_uuid,
    m007_data_cleanup,
    m008_supabase_auth,
    m009_supabase_password_set,
    m010_idle_timeout,
    m011_least_privilege_role,
    m012_idle_session_timeout,
    m013_not_null_constraints,
    m014_jobs_fk_cascade,
)

logger = logging.getLogger(__name__)

# Order matters: later chunks depend on tables/columns created by earlier ones.
MIGRATIONS = [
    m001_core_tables,
    m002_schema_patches,
    m003_grants_indexes,
    m004_fk_constraints,
    m005_phase1_timestamptz,
    m006_phase2_uuid,
    m007_data_cleanup,
    m008_supabase_auth,
    m009_supabase_password_set,
    m010_idle_timeout,
    m011_least_privilege_role,
    m012_idle_session_timeout,
    m013_not_null_constraints,
    m014_jobs_fk_cascade,
]


async def run_migrations(conn):
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    applied = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")}

    for mod in MIGRATIONS:
        if mod.VERSION in applied:
            continue
        async with conn.transaction():
            await mod.up(conn)
            await conn.execute(
                "INSERT INTO schema_migrations (version) VALUES ($1)", mod.VERSION
            )
        logger.info("Applied migration %s", mod.VERSION)
