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


_SENTINEL = object()

_USER_SELECT_COLS = (
    "id, org_id, email, name, role, team_id, setting_id, password_changed_at, "
    "must_change_password, mfa_enabled, eula_accepted_version"
)


def _decode_access_token(request: Request, credentials: HTTPAuthorizationCredentials):
    """Shared token-decoding + payload-validation logic used by both
    get_current_user() and get_current_user_conn() below — kept identical
    between the two so the connection-reusing variant can never diverge in
    its auth checks from the original."""
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

    # A token minted before the org_id claim existed has no "org_id" key at
    # all (distinct from a super_admin's legitimate org_id=None) — treat
    # that the same as the pwd_ts upgrade path below: a clean 401 that the
    # frontend's axios interceptor silently turns into a refresh, which
    # mints a new token carrying the claim.
    org_id = payload.get("org_id", _SENTINEL)
    if org_id is _SENTINEL:
        raise HTTPException(status_code=401, detail="Session expired — please sign in again.")

    return user_id, org_id, payload


def _finalize_user_row(row: dict | None, payload: dict) -> dict:
    """Shared row-validation logic (not found / stale-password-token check)
    used by both get_current_user() and get_current_user_conn() below."""
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


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id, org_id, payload = _decode_access_token(request, credentials)

    # SEC-DB-001: use the least-privilege, org-scoped connection for this
    # self-lookup instead of the RLS-bypass admin connection — this dependency
    # runs on nearly every request, so it was previously the single biggest
    # consumer of the admin/bypass pool.
    if org_id is None:
        # super_admin has no single org to scope to — this is the exact
        # "handful of operations that genuinely need it" exception.
        async with database.with_admin() as conn:
            row = await conn.fetchrow(
                f"SELECT {_USER_SELECT_COLS} FROM users WHERE id = $1 AND is_active = TRUE", user_id
            )
    else:
        async with database.with_org(org_id) as conn:
            row = await conn.fetchrow(
                f"SELECT {_USER_SELECT_COLS} FROM users WHERE id = $1 AND org_id = $2 AND is_active = TRUE",
                user_id, org_id,
            )

    return _finalize_user_row(row, payload)


async def get_current_user_conn(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """PERF: opt-in variant of get_current_user() for a small allowlist of
    read-only endpoints that can reuse THIS dependency's own connection/
    transaction for their own query, instead of opening a second, separate
    with_org() block immediately afterward for the exact same org_id — each
    with_org()/with_admin() block costs ~5-6 DB round trips (BEGIN, set
    context, role switch, query, COMMIT), so removing one redundant block
    per request is a real, measured win (~636ms in this environment).

    Stashes the still-open connection on request.state.db_conn /
    request.state.db_conn_org_id so the route handler can check "is this
    the same org_id I need, on a connection that's still open?" before
    deciding to reuse it — falling back to opening its own fresh block
    otherwise. Yield-based (FastAPI's standard "acquire once, release after
    the response" pattern) so the transaction commits/releases automatically
    once the handler (and response) is done.

    NOT a replacement for get_current_user() app-wide — only safe for plain
    GET handlers with:
      - no background_tasks.add_task() calls (the connection is released the
        moment the response is generated, before any background task runs)
      - no writes (holding a transaction open for the whole handler is fine
        for reads; on a write it extends how long row locks are held)
    Every other route keeps using get_current_user() above, unchanged.
    """
    user_id, org_id, payload = _decode_access_token(request, credentials)

    if org_id is None:
        async with database.with_admin() as conn:
            row = await conn.fetchrow(
                f"SELECT {_USER_SELECT_COLS} FROM users WHERE id = $1 AND is_active = TRUE", user_id
            )
            user = _finalize_user_row(row, payload)
            request.state.db_conn = conn
            request.state.db_conn_org_id = None
            yield user
    else:
        async with database.with_org(org_id) as conn:
            row = await conn.fetchrow(
                f"SELECT {_USER_SELECT_COLS} FROM users WHERE id = $1 AND org_id = $2 AND is_active = TRUE",
                user_id, org_id,
            )
            user = _finalize_user_row(row, payload)
            request.state.db_conn = conn
            request.state.db_conn_org_id = org_id
            yield user





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
