"""
Create all PostgreSQL tables and RLS policies.
Delegates to the versioned migration runner in migrations/ — each numbered
chunk only runs once, tracked via the schema_migrations ledger table, instead
of re-evaluating the entire schema history on every startup.
"""
import asyncpg
import asyncio
import json
import os
import logging
from dotenv import load_dotenv

from migrations import run_migrations

load_dotenv()
logger = logging.getLogger(__name__)


async def _init_conn(conn):
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    await conn.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def create_schema():
    dsn = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(dsn, ssl="require")
    try:
        await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
        await conn.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
        await run_migrations(conn)
        logger.info("Schema created/verified successfully")
    finally:
        await conn.close()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    load_dotenv()
    asyncio.run(create_schema())
    print("Schema created successfully.")
