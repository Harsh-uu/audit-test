"""EULA acceptance gate — GET current version + accept/decline for the logged-in user.

Global platform content (no org_id), same pattern as routers/resources.py.
Versioning: a user "needs acceptance" when their eula_accepted_version is
NULL or below the currently active eula_versions.version — this naturally
re-gates everyone (including previously-accepted accounts) whenever a new
version is published.
"""

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone
from deps import get_current_user
import database

router = APIRouter()


@router.get("/current")
async def get_current_eula(current_user=Depends(get_current_user)):
    async with database.with_admin() as conn:
        active = await conn.fetchrow(
            "SELECT version, content FROM eula_versions WHERE is_active=TRUE ORDER BY version DESC LIMIT 1"
        )
        if not active:
            raise HTTPException(status_code=500, detail="No active EULA version configured")
        row = await conn.fetchrow(
            "SELECT eula_accepted_version, eula_decline_count FROM users WHERE id=$1",
            current_user["id"],
        )
    accepted_version = row["eula_accepted_version"] if row else None
    needs_acceptance = accepted_version is None or accepted_version < active["version"]
    return {
        "version": active["version"],
        "content": active["content"],
        "needs_acceptance": needs_acceptance,
        "decline_count": (row["eula_decline_count"] if row else 0) or 0,
    }


@router.post("/accept")
async def accept_eula(current_user=Depends(get_current_user)):
    async with database.with_admin() as conn:
        active = await conn.fetchrow("SELECT version FROM eula_versions WHERE is_active=TRUE ORDER BY version DESC LIMIT 1")
        if not active:
            raise HTTPException(status_code=500, detail="No active EULA version configured")
        await conn.execute(
            """UPDATE users SET eula_accepted_version=$1, eula_accepted_at=$2, eula_decline_count=0
               WHERE id=$3""",
            active["version"], datetime.now(timezone.utc), current_user["id"],
        )
    return {"message": "EULA accepted", "version": active["version"]}


@router.post("/decline")
async def decline_eula(current_user=Depends(get_current_user)):
    """Called when the user dismisses the prompt without agreeing ("remind me later")."""
    async with database.with_admin() as conn:
        row = await conn.fetchrow(
            "UPDATE users SET eula_decline_count = eula_decline_count + 1 WHERE id=$1 RETURNING eula_decline_count",
            current_user["id"],
        )
    return {"decline_count": row["eula_decline_count"]}
