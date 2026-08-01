"""
PostgreSQL connection pool management via asyncpg.
Provides helpers for org-scoped (RLS) and admin (RLS bypass) operations.
"""
import asyncpg
import json
import os
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Register JSONB/JSON codecs so asyncpg returns Python objects, not strings."""
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )
    await conn.set_type_codec(
        "json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def create_pool() -> asyncpg.Pool:
    global pool
    dsn = os.environ["DATABASE_URL"]
    pool = await asyncpg.create_pool(
        dsn,
        ssl="require",
        min_size=2,
        max_size=15,
        init=_init_connection,
    )
    logger.info("PostgreSQL pool created")
    return pool


async def close_pool() -> None:
    global pool
    if pool:
        await pool.close()
        logger.info("PostgreSQL pool closed")


def get_pool() -> asyncpg.Pool:
    return pool


@asynccontextmanager
async def with_org(org_id: str):
    """
    Acquire a connection, start a transaction, and set the RLS context.
    All queries within the block are scoped to org_id via PostgreSQL RLS.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.current_org_id', $1, TRUE)", org_id or ""
            )
            yield conn


@asynccontextmanager
async def with_admin():
    """
    Acquire a connection with RLS bypassed.
    Use for: seeding, super-admin operations, job worker.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SET LOCAL row_security = off")
            yield conn


def row(r) -> dict | None:
    """Convert an asyncpg Record to a plain dict (returns None if r is None)."""
    return dict(r) if r is not None else None


def rows(rs) -> list[dict]:
    """Convert a list of asyncpg Records to a list of dicts."""
    return [dict(r) for r in rs]
