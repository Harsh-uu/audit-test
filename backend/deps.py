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
