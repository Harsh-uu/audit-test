from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime
import jwt
import os
import database

security = HTTPBearer(auto_error=False)


def _pwd_ts_of(user: dict) -> float:
    """Convert a user's password_changed_at field to a Unix float for pwd_ts comparison."""
    pc = user.get("password_changed_at")
    if not pc:
        return 0.0
    if isinstance(pc, str):
        try:
            return datetime.fromisoformat(pc.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0
    if hasattr(pc, "timestamp"):
        return pc.timestamp()
    return 0.0


def get_db(request: Request):
    """Return the asyncpg pool stored on app state."""
    return request.app.state.pool


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    # P3b: HttpOnly cookie takes priority; fall back to Authorization header
    # for backward-compat with any sessions that pre-date the cookie migration.
    token = request.cookies.get("supervision_access")
    if not token:
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

    # SEC-001: Reject non-access tokens (mfa_pending, refresh) on guarded endpoints
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")

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

    # SEC-001: reject access tokens issued before the user's last password
    # change — closes the window where a stolen token kept working for up to
    # 30 min after a reset/change (mirrors the same check on refresh tokens).
    # Tokens without the pwd_ts claim predate this fix; the frontend's axios
    # interceptor auto-refreshes on 401, so this is a silent, seamless upgrade.
    token_pwd_ts = payload.get("pwd_ts")
    if token_pwd_ts is None or token_pwd_ts < _pwd_ts_of(user):
        raise HTTPException(status_code=401, detail="Session expired — please sign in again.")

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
