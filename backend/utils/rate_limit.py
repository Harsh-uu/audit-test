"""
Reusable DB-backed rate limiter.

Reuses the existing `login_attempts` table (identifier, count, locked_until, updated_at).
Survives server restarts. No extra dependencies.

Usage:
    from utils.rate_limit import check_rate_limit

    async with database.with_admin() as conn:
        await check_rate_limit(
            conn,
            identifier="fp_ip:192.168.1.1",
            max_attempts=5,
            window_minutes=15,
            error_detail="Too many password reset requests. Try again in 15 minutes.",
        )
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException


async def check_rate_limit(
    conn,
    identifier: str,
    max_attempts: int,
    window_minutes: int,
    error_detail: str | None = None,
) -> None:
    """
    Raise HTTP 429 if `identifier` has exceeded `max_attempts`
    within the last `window_minutes` minutes.
    Automatically clears expired windows.
    """
    now = datetime.now(timezone.utc)
    row = await conn.fetchrow(
        "SELECT count, locked_until FROM login_attempts WHERE identifier = $1",
        identifier,
    )

    if row:
        locked_until = row.get("locked_until")
        if locked_until:
            # Parse stored ISO string to aware datetime for comparison
            if isinstance(locked_until, str):
                from datetime import datetime as _dt
                try:
                    locked_dt = _dt.fromisoformat(locked_until)
                    if locked_dt.tzinfo is None:
                        locked_dt = locked_dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    locked_dt = now
            else:
                locked_dt = locked_until if locked_until.tzinfo else locked_until.replace(tzinfo=timezone.utc)

            if locked_dt > now:
                mins_left = max(1, int((locked_dt - now).total_seconds() / 60))
                raise HTTPException(
                    status_code=429,
                    detail=error_detail or f"Rate limit exceeded. Try again in {mins_left} minute(s).",
                )
            else:
                # Window expired — reset counter
                await conn.execute(
                    "DELETE FROM login_attempts WHERE identifier = $1", identifier
                )
                row = None

    locked_until_new = (now + timedelta(minutes=window_minutes)).isoformat()
    await conn.execute(
        """INSERT INTO login_attempts (identifier, count, locked_until, updated_at)
           VALUES ($1, 1, NULL, $2)
           ON CONFLICT (identifier) DO UPDATE
               SET count       = login_attempts.count + 1,
                   locked_until = CASE
                       WHEN login_attempts.count + 1 >= $3
                       THEN $4
                       ELSE NULL
                   END,
                   updated_at  = $2
        """,
        identifier, now.isoformat(), max_attempts, locked_until_new,
    )

    # Re-read to check if we just hit the limit
    updated = await conn.fetchrow(
        "SELECT count, locked_until FROM login_attempts WHERE identifier = $1",
        identifier,
    )
    if updated and updated.get("locked_until"):
        raise HTTPException(
            status_code=429,
            detail=error_detail or f"Rate limit exceeded. Try again in {window_minutes} minute(s).",
        )
