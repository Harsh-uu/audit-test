"""
PostgreSQL connection pool management via asyncpg.
Provides helpers for org-scoped (RLS) and admin (RLS bypass) operations.
"""
import asyncpg
import json
import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime

logger = logging.getLogger(__name__)

pool: asyncpg.Pool | None = None
# Separate pool authenticated as the RLS-exempt admin role (see m011).
# with_admin() acquires from here; every other code path (with_org(), and
# there is nothing else — see database.py module docstring) uses `pool`,
# which now authenticates as the least-privilege `app_default` role.
admin_pool: asyncpg.Pool | None = None


def _encode_timestamp(value):
    """Accept either a datetime object or an ISO-8601 string as a query param for
    TIMESTAMPTZ/TIMESTAMP columns — Postgres's own input parser accepts ISO-8601
    text natively, so a plain string passes through unchanged."""
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else value


def _decode_timestamp(value):
    """Normalize Postgres's text output ('YYYY-MM-DD HH:MI:SS+TZ') back to Python's
    isoformat ('...T...+HH:MM') so every existing string comparison / JSON payload
    built from a fetched timestamp column is completely unaffected by the
    TEXT -> TIMESTAMPTZ migration (Phase 1)."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace(" ", "T", 1)).isoformat()
    except ValueError:
        return value


def _encode_uuid(value):
    """A plain string UUID (str(uuid.uuid4())) passes straight through — Postgres's
    own input parser accepts standard UUID text natively, no wrapping needed."""
    return value


def _decode_uuid(value):
    """Postgres's text output for uuid is already lowercase-hyphenated, identical
    to Python's str(uuid.uuid4()) — return as-is so every id stays a plain str,
    exactly as before the TEXT -> UUID migration (Phase 2)."""
    return value


def _encode_date(value):
    """Accept either a date object or a plain 'YYYY-MM-DD' string as a query
    param for DATE columns — Postgres's own input parser accepts ISO-8601 date
    text natively, so a plain string passes through unchanged."""
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else value


def _decode_date(value):
    """Postgres's text output for date is already plain 'YYYY-MM-DD', identical
    to what every existing call site (date.fromisoformat(...), string slicing,
    JSON payloads) already expects — return as-is so nothing downstream needs
    to change after the TEXT -> DATE migration (Phase 2)."""
    return value


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Register JSONB/JSON codecs so asyncpg returns Python objects, not strings.
    Also register TIMESTAMPTZ/TIMESTAMP and UUID codecs in text format: this lets
    columns migrated from TEXT to TIMESTAMPTZ/UUID keep accepting/returning plain
    strings, so none of the existing `.isoformat()` / `str(uuid.uuid4())` call
    sites across routers need to change, while Postgres now stores, sorts and
    validates real timestamps/UUIDs at rest (and rejects malformed values at the
    DB level) instead of comparing opaque text."""
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )
    await conn.set_type_codec(
        "json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )
    for typename in ("timestamptz", "timestamp"):
        await conn.set_type_codec(
            typename,
            encoder=_encode_timestamp,
            decoder=_decode_timestamp,
            schema="pg_catalog",
            format="text",
        )
    await conn.set_type_codec(
        "uuid",
        encoder=_encode_uuid,
        decoder=_decode_uuid,
        schema="pg_catalog",
        format="text",
    )
    await conn.set_type_codec(
        "date",
        encoder=_encode_date,
        decoder=_decode_date,
        schema="pg_catalog",
        format="text",
    )


async def create_pool() -> asyncpg.Pool:
    """Create both pools. Must be called AFTER migrations (init_db.create_schema())
    have run at least once, since app_default (m011) doesn't exist before that."""
    global pool, admin_pool
    pool = await asyncpg.create_pool(
        os.environ["APP_DATABASE_URL"],
        ssl="require",
        min_size=2,
        max_size=15,
        init=_init_connection,
        # Required when DATABASE_URL points at a transaction-mode pooler
        # (Supavisor/PgBouncer, e.g. Supabase's transaction pooler on port
        # 6543): each query can land on a different physical backend
        # connection, so asyncpg's client-side prepared-statement cache
        # must be disabled — a cached statement may not exist on whichever
        # backend the pooler routes the next query to. Harmless no-op on a
        # direct connection (port 5432).
        statement_cache_size=0,
    )
    logger.info("PostgreSQL pool created (app_default, RLS-enforced by default)")

    admin_pool = await asyncpg.create_pool(
        os.environ["DATABASE_URL"],
        ssl="require",
        min_size=1,
        max_size=10,
        init=_init_connection,
        statement_cache_size=0,
    )
    logger.info("PostgreSQL admin pool created (postgres, RLS bypass — with_admin() only)")
    return pool


async def close_pool() -> None:
    global pool, admin_pool
    if pool:
        await pool.close()
    if admin_pool:
        await admin_pool.close()
    logger.info("PostgreSQL pools closed")


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

    !! JSONB WRITE WARNING (applies to with_admin() too — NOT RLS-specific) !!
    _init_connection registers a jsonb/json type codec with encoder=json.dumps
    on every pooled connection. NEVER call json.dumps() on a value you are
    binding to a `$N::jsonb` parameter — the codec serializes it AGAIN,
    producing a double-encoded JSON string in the column (jsonb_typeof
    returns 'string' instead of 'array'/'object'). Just pass the raw Python
    list/dict directly; the codec does the encoding. This also applies to
    jsonb `||` concat writes (e.g. recording_events || $1::jsonb) — pass a
    raw list, not json.dumps(list), or individual appended elements end up
    stringified inside an otherwise-valid array. See /app/CONTRIBUTING.md.
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
    Acquire a connection from the separate admin_pool, authenticated as
    `postgres` (BYPASSRLS) with RLS explicitly off.
    Use for: seeding, super-admin operations, auth, job worker — i.e. paths
    that are genuinely cross-org or run before an org context exists.
    This is a distinct pool/credential from `pool` (see m011): the main
    pool authenticates as the least-privilege `app_default` role, so this
    bypass is now an explicit, separately-provisioned escalation rather
    than the default identity every connection starts with.

    Note: JSONB columns can still be returned as strings in some connection-
    pooler configurations. Apply the same _ensure_list/_jdict guards as
    with_org() when reading JSONB fields. See /app/CONTRIBUTING.md.
    """
    async with admin_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SET LOCAL row_security = off")
            yield conn


def row(r) -> dict | None:
    """Convert an asyncpg Record to a plain dict (returns None if r is None)."""
    return dict(r) if r is not None else None


def rows(rs) -> list[dict]:
    """Convert a list of asyncpg Records to a list of dicts."""
    return [dict(r) for r in rs]
