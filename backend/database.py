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
    Acquire a connection, start a transaction, set the RLS context, and
    switch to the limited `app_rls_user` role so PostgreSQL RLS policies
    are actually enforced (superusers bypass RLS; limited roles do not).
    Raises RuntimeError (→ HTTP 500) if the role switch fails — silent
    degradation to superuser would bypass RLS entirely.

    !! JSONB WARNING !!
    The SET LOCAL ROLE switch causes asyncpg's prepared-statement cache to
    reset. After the reset the driver returns JSONB columns as raw JSON
    *strings* instead of decoded dicts/lists. Every JSONB column read from
    this context MUST be passed through _ensure_list / _ensure_dict / _jlist
    / _jdict (or an equivalent inline json.loads guard) before use.
    See /app/CONTRIBUTING.md for the full rule.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Set org context that USING policies check
            await conn.execute(
                "SELECT set_config('app.current_org_id', $1, TRUE)", org_id or ""
            )
            # Hard fail if the role doesn't exist — silently running as
            # superuser would bypass all RLS policies.
            try:
                await conn.execute("SET LOCAL ROLE app_rls_user")
            except Exception as exc:
                raise RuntimeError(
                    f"RLS role switch failed for org_id={org_id!r}: {exc}. "
                    "Ensure the app_rls_user role exists in the database."
                ) from exc
            yield conn


@asynccontextmanager
async def with_admin():
    """
    Acquire a connection as postgres (superuser) with RLS explicitly off.
    Use for: seeding, super-admin operations, auth, job worker.

    Note: JSONB columns can still be returned as strings in some connection-
    pooler configurations. Apply the same _ensure_list/_jdict guards as
    with_org() when reading JSONB fields. See /app/CONTRIBUTING.md.
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
