"""
Reusable DB-backed rate limiter.

Reuses the existing `login_attempts` table (identifier, count, locked_until, updated_at).
Survives server restarts. No extra dependencies.

Three functions:
  - check_rate_limit(): counts EVERY call (regardless of outcome) against the
    budget, raising 429 once `max_attempts` is exceeded within `window_minutes`.
    Use this for pure resource-usage throttling where there's no notion of
    "success/failure" (e.g. "max 10 meetings created per hour", "max 3 prep
    regenerations per hour") — every call is a real use of the resource.

  - check_lockout(): READ-ONLY. Raises 429 if `identifier` is currently locked
    out. Does NOT record an attempt. Call this at the START of a request.
  - record_failed_attempt(): increments the failure count and locks the
    identifier if `max_attempts` is exceeded within `window_minutes`.
    Call this ONLY when the actual operation failed (e.g. wrong password,
    wrong OTP) — NOT on every request.

  Use check_lockout() + record_failed_attempt() together for anything where
  a legitimate SUCCESS must never count against the budget (login, OTP
  verification) — otherwise heavy-but-legitimate traffic from a shared IP/
  account gets locked out for no reason, which is exactly as bad as no rate
  limit at all.

Usage (pure throttling):
    from utils.rate_limit import check_rate_limit
    async with database.with_admin() as conn:
        await check_rate_limit(
            conn, identifier="fp_ip:192.168.1.1",
            max_attempts=5, window_minutes=15,
            error_detail="Too many password reset requests. Try again in 15 minutes.",
        )

Usage (failure-only, e.g. login):
    from utils.rate_limit import check_lockout, record_failed_attempt
    async with database.with_admin() as conn:
        await check_lockout(conn, identifier="login_ip:1.2.3.4", error_detail="...")
    # ... do the actual credential check ...
    if not password_ok:
        async with database.with_admin() as conn:
            await record_failed_attempt(
                conn, identifier="login_ip:1.2.3.4",
                max_attempts=20, window_minutes=15,
                error_detail="Too many failed login attempts. Try again in 15 minutes.",
            )
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException


def _as_aware_dt(value):
    if value is None:
        return None
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        dt = value
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def check_rate_limit(
    conn,
    identifier: str,
    max_attempts: int,
    window_minutes: int,
    error_detail: str | None = None,
) -> None:
    """
    Raise HTTP 429 if `identifier` has exceeded `max_attempts`
    within the last `window_minutes` minutes. Counts EVERY call.
    Automatically clears expired windows — including a count that never
    crossed the threshold but has simply gone stale (no activity for
    window_minutes), which previously persisted indefinitely and could
    tip into a lock on the next attempt no matter how much time had
    passed since the count was last incremented.
    """
    now = datetime.now(timezone.utc)
    row = await conn.fetchrow(
        "SELECT count, locked_until, updated_at FROM login_attempts WHERE identifier = $1",
        identifier,
    )

    if row:
        locked_dt = _as_aware_dt(row["locked_until"])
        if locked_dt and locked_dt > now:
            mins_left = max(1, int((locked_dt - now).total_seconds() / 60))
            raise HTTPException(
                status_code=429,
                detail=error_detail or f"Rate limit exceeded. Try again in {mins_left} minute(s).",
            )
        # Either a prior lock has expired, or the count never crossed the
        # threshold but the window has elapsed since the last call — reset
        # either way, mirroring record_failed_attempt's staleness check below.
        updated_dt = _as_aware_dt(row.get("updated_at"))
        if (locked_dt and locked_dt <= now) or (updated_dt and (now - updated_dt) > timedelta(minutes=window_minutes)):
            await conn.execute("DELETE FROM login_attempts WHERE identifier = $1", identifier)

    locked_until_new = (now + timedelta(minutes=window_minutes)).isoformat()
    result = await conn.fetchrow(
        """INSERT INTO login_attempts (identifier, count, locked_until, updated_at)
           VALUES ($1, 1, NULL, $2)
           ON CONFLICT (identifier) DO UPDATE
               SET count       = login_attempts.count + 1,
                   locked_until = CASE
                       WHEN login_attempts.count + 1 > $3
                       THEN $4::timestamptz
                       ELSE NULL::timestamptz
                   END,
                   updated_at  = $2
           RETURNING count, locked_until
        """,
        identifier, now.isoformat(), max_attempts, locked_until_new,
    )
    if result and result.get("locked_until"):
        raise HTTPException(
            status_code=429,
            detail=error_detail or f"Rate limit exceeded. Try again in {window_minutes} minute(s).",
        )


async def check_lockout(conn, identifier: str, error_detail: str | None = None) -> None:
    """Read-only: raise HTTP 429 if `identifier` is currently locked out. Does NOT record an attempt."""
    row = await conn.fetchrow(
        "SELECT locked_until FROM login_attempts WHERE identifier = $1", identifier,
    )
    if not row or not row.get("locked_until"):
        return
    locked_dt = _as_aware_dt(row["locked_until"])
    now = datetime.now(timezone.utc)
    if locked_dt and locked_dt > now:
        mins_left = max(1, int((locked_dt - now).total_seconds() / 60))
        raise HTTPException(
            status_code=429,
            detail=error_detail or f"Rate limit exceeded. Try again in {mins_left} minute(s).",
        )


async def record_failed_attempt(
    conn,
    identifier: str,
    max_attempts: int,
    window_minutes: int,
    error_detail: str | None = None,
) -> None:
    """
    Record one FAILED attempt for `identifier`. Raises HTTP 429 if this failure
    pushes the count over `max_attempts` within `window_minutes`. Resets the
    window automatically once it has expired. Successful attempts must never
    call this — only call it once you know the operation actually failed.
    """
    now = datetime.now(timezone.utc)
    row = await conn.fetchrow(
        "SELECT updated_at FROM login_attempts WHERE identifier = $1", identifier,
    )
    if row:
        updated_dt = _as_aware_dt(row.get("updated_at"))
        if updated_dt and (now - updated_dt) > timedelta(minutes=window_minutes):
            await conn.execute("DELETE FROM login_attempts WHERE identifier = $1", identifier)

    locked_until_new = (now + timedelta(minutes=window_minutes)).isoformat()
    result = await conn.fetchrow(
        """INSERT INTO login_attempts (identifier, count, locked_until, updated_at)
           VALUES ($1, 1, NULL, $2)
           ON CONFLICT (identifier) DO UPDATE
               SET count       = login_attempts.count + 1,
                   locked_until = CASE
                       WHEN login_attempts.count + 1 > $3
                       THEN $4::timestamptz
                       ELSE NULL::timestamptz
                   END,
                   updated_at  = $2
           RETURNING count, locked_until
        """,
        identifier, now.isoformat(), max_attempts, locked_until_new,
    )
    if result and result.get("locked_until"):
        raise HTTPException(
            status_code=429,
            detail=error_detail or f"Rate limit exceeded. Try again in {window_minutes} minute(s).",
        )
