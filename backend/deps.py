from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
import os
import database

security = HTTPBearer(auto_error=False)


def get_db(request: Request):
    """Return the asyncpg pool stored on app state."""
    return request.app.state.pool


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = credentials.credentials
    secret = os.environ["JWT_SECRET"]
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    pool = request.app.state.pool
    async with database.with_admin() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE id = $1 AND is_active = TRUE", user_id
        )

    if not row:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    user = dict(row)
    return user


def require_roles(*roles):
    async def checker(current_user=Depends(get_current_user)):
        if current_user.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return checker


def get_manager_scope(current_user: dict) -> dict:
    """
    Determine data scope for a manager/admin.
    Returns {'level': 'org'|'setting'|'team', 'setting_id': str|None, 'team_id': str|None}
      - 'org'     → no restriction; sees everything in the org (admin, super_admin, or
                    manager with no branch/team assignment)
      - 'setting' → restricted to a specific branch / setting
      - 'team'    → restricted to a specific team within a setting
    """
    role = current_user.get("role", "")
    if role in ["admin", "super_admin"]:
        return {"level": "org", "setting_id": None, "team_id": None}
    team_id = current_user.get("team_id") or None
    setting_id = current_user.get("setting_id") or None
    if team_id:
        return {"level": "team", "setting_id": setting_id, "team_id": team_id}
    if setting_id:
        return {"level": "setting", "setting_id": setting_id, "team_id": None}
    return {"level": "org", "setting_id": None, "team_id": None}


async def get_scoped_staff_ids(conn, org_id: str, scope: dict):
    """
    Returns a list of staff user IDs within the manager's scope.
    Returns None for org-level scope (meaning no restriction).
    Used by multiple routers to apply consistent RBAC filtering.
    """
    if scope["level"] == "org":
        return None
    if scope["level"] == "team":
        rows = await conn.fetch(
            "SELECT id FROM users WHERE org_id=$1 AND is_active=TRUE AND team_id=$2",
            org_id, scope["team_id"],
        )
    else:  # setting
        rows = await conn.fetch(
            "SELECT id FROM users WHERE org_id=$1 AND is_active=TRUE AND setting_id=$2",
            org_id, scope["setting_id"],
        )
    return [r["id"] for r in rows]
