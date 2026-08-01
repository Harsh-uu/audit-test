from fastapi import APIRouter, HTTPException, Depends, Response, Request
from pydantic import BaseModel, EmailStr
import bcrypt
import jwt
import os
import re
import uuid
import secrets
import resend
from datetime import datetime, timezone, timedelta
from deps import get_db, get_current_user
import database

router = APIRouter()
JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def validate_password_strength(password: str):
    errors = []
    if len(password) < 10:
        errors.append("at least 10 characters")
    if not re.search(r'[A-Z]', password):
        errors.append("an uppercase letter")
    if not re.search(r'[a-z]', password):
        errors.append("a lowercase letter")
    if not re.search(r'[0-9]', password):
        errors.append("a number")
    if not re.search(r'[^A-Za-z0-9]', password):
        errors.append("a special character (!@#$%^&* etc.)")
    if errors:
        raise HTTPException(status_code=400, detail=f"Password must contain {', '.join(errors)}.")


def create_access_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=24),
        "type": "access",
    }
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "type": "refresh",
    }
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm=JWT_ALGORITHM)


def set_auth_cookies(response: Response, access_token: str, refresh_token: str):
    response.set_cookie("access_token", access_token, httponly=True, secure=True, samesite="lax", max_age=28800, path="/")
    response.set_cookie("refresh_token", refresh_token, httponly=True, secure=True, samesite="lax", max_age=604800, path="/")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: str = "attendee"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/register")
async def register(data: RegisterRequest, response: Response):
    email = data.email.lower()
    async with database.with_admin() as conn:
        existing = await conn.fetchrow("SELECT id FROM users WHERE email = $1", email)
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")
        user_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await conn.execute(
            """INSERT INTO users (id, email, password_hash, name, role, is_active, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7)""",
            user_id, email, hash_password(data.password), data.name, "attendee", True, now,
        )
    access_token = create_access_token(user_id, email)
    refresh_token = create_refresh_token(user_id)
    set_auth_cookies(response, access_token, refresh_token)
    return {"id": user_id, "email": email, "name": data.name, "role": "attendee", "token": access_token, "refresh_token": refresh_token}


@router.post("/login")
async def login(data: LoginRequest, response: Response, request: Request):
    email = data.email.lower()
    identifier = f"{request.client.host}:{email}"

    async with database.with_admin() as conn:
        attempts_row = await conn.fetchrow("SELECT count, locked_until FROM login_attempts WHERE identifier = $1", identifier)
        if attempts_row and attempts_row["count"] >= 5:
            lockout_until = attempts_row.get("locked_until")
            if lockout_until and lockout_until > datetime.now(timezone.utc).isoformat():
                raise HTTPException(status_code=429, detail="Account temporarily locked. Try again later.")

        user = await conn.fetchrow("SELECT * FROM users WHERE email = $1", email)
        if not user or not verify_password(data.password, user["password_hash"] or ""):
            now = datetime.now(timezone.utc).isoformat()
            locked_until = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
            await conn.execute(
                """INSERT INTO login_attempts (identifier, count, locked_until, updated_at)
                   VALUES ($1, 1, $2, $3)
                   ON CONFLICT (identifier) DO UPDATE
                   SET count = login_attempts.count + 1,
                       locked_until = $2,
                       updated_at = $3""",
                identifier, locked_until, now,
            )
            raise HTTPException(status_code=401, detail="Invalid credentials")

        await conn.execute("DELETE FROM login_attempts WHERE identifier = $1", identifier)

    user = dict(user)
    user_id = user["id"]
    access_token = create_access_token(user_id, email)
    refresh_token = create_refresh_token(user_id)
    set_auth_cookies(response, access_token, refresh_token)
    return {
        "id": user_id, "email": email, "name": user["name"], "role": user["role"],
        "token": access_token, "refresh_token": refresh_token,
        "must_change_password": user.get("must_change_password", False),
    }


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return {"message": "Logged out"}


@router.get("/me")
async def me(current_user=Depends(get_current_user)):
    user = dict(current_user)
    user.pop("password_hash", None)
    org_id = user.get("org_id")
    if org_id:
        async with database.with_admin() as conn:
            org = await conn.fetchrow("SELECT name, branding FROM organisations WHERE id = $1", org_id)
        if org:
            _b_raw = org["branding"] or {}
            import json as _json
            b = _json.loads(_b_raw) if isinstance(_b_raw, str) else (_b_raw or {})
            user["org_branding"] = {
                "has_logo": bool(b.get("logo_path")),
                "primary_color": b.get("primary_color"),
            }
            user["org_name"] = org["name"]
    return user


@router.post("/refresh")
async def refresh_token(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        payload = jwt.decode(token, os.environ["JWT_SECRET"], algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        async with database.with_admin() as conn:
            user = await conn.fetchrow("SELECT id, email, is_active FROM users WHERE id = $1", payload["sub"])
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        if not user["is_active"]:
            raise HTTPException(status_code=401, detail="Account is deactivated")
        user_id = user["id"]
        new_access = create_access_token(user_id, user["email"])
        new_refresh = create_refresh_token(user_id)
        response.set_cookie("access_token", new_access, httponly=True, secure=True, samesite="lax", max_age=86400, path="/")
        response.set_cookie("refresh_token", new_refresh, httponly=True, secure=True, samesite="lax", max_age=604800, path="/")
        return {"access_token": new_access, "refresh_token": new_refresh, "message": "Token refreshed"}
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordRequest):
    email = data.email.lower()
    async with database.with_admin() as conn:
        user = await conn.fetchrow("SELECT id FROM users WHERE email = $1", email)
        if not user:
            return {"message": "If that email exists, a reset link has been sent."}

        token = secrets.token_urlsafe(32)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

        await conn.execute("DELETE FROM password_reset_tokens WHERE email = $1", email)
        await conn.execute(
            "INSERT INTO password_reset_tokens (token, email, expires_at, used) VALUES ($1,$2,$3,$4)",
            token, email, expires_at, False,
        )

    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
    reset_link = f"{frontend_url}/reset-password?token={token}"

    resend.api_key = os.environ.get("RESEND_API_KEY", "")
    try:
        resend.Emails.send({
            "from": "Supervision 2 <noreply@notify.1two.one>",
            "to": [email],
            "subject": "Reset your password",
            "html": (
                "<div style='font-family:Poppins,sans-serif;max-width:480px;margin:0 auto;"
                "padding:32px 24px;background:#f8fafc;border-radius:12px;'>"
                "<h2 style='color:#1E3A8A;font-size:22px;margin-bottom:8px;'>Reset your password</h2>"
                "<p style='color:#475569;font-size:15px;margin-bottom:24px;'>Click the button below to set a new password. "
                "This link expires in <strong>1 hour</strong>.</p>"
                f"<a href='{reset_link}' style='display:inline-block;background:#1E3A8A;color:#fff;"
                "text-decoration:none;padding:12px 28px;border-radius:8px;font-size:15px;"
                "font-weight:600;'>Reset Password</a>"
                "<p style='color:#94a3b8;font-size:12px;margin-top:28px;'>"
                "If you didn't request this, you can safely ignore this email.</p>"
                "</div>"
            ),
        })
    except Exception:
        pass
    return {"message": "If that email exists, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(data: ResetPasswordRequest):
    validate_password_strength(data.new_password)
    async with database.with_admin() as conn:
        record = await conn.fetchrow(
            "SELECT * FROM password_reset_tokens WHERE token = $1 AND used = FALSE", data.token
        )
        if not record:
            raise HTTPException(status_code=400, detail="Invalid or expired reset link.")
        if record["expires_at"] < datetime.now(timezone.utc).isoformat():
            raise HTTPException(status_code=400, detail="This reset link has expired.")

        now = datetime.now(timezone.utc).isoformat()
        await conn.execute(
            """UPDATE users SET password_hash=$1, must_change_password=FALSE,
               password_changed_at=$2 WHERE email=$3""",
            hash_password(data.new_password), now, record["email"],
        )
        await conn.execute("UPDATE password_reset_tokens SET used=TRUE WHERE token=$1", data.token)
    return {"message": "Password updated successfully. You can now log in."}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
async def change_password(data: ChangePasswordRequest, current_user=Depends(get_current_user)):
    validate_password_strength(data.new_password)
    async with database.with_admin() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", current_user["id"])
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if not verify_password(data.current_password, user["password_hash"] or ""):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        if data.current_password == data.new_password:
            raise HTTPException(status_code=400, detail="New password must be different from the current one")
        now = datetime.now(timezone.utc).isoformat()
        await conn.execute(
            """UPDATE users SET password_hash=$1, must_change_password=FALSE,
               password_changed_at=$2 WHERE id=$3""",
            hash_password(data.new_password), now, current_user["id"],
        )
    return {"message": "Password changed successfully"}


@router.get("/invite/{token}")
async def validate_invite(token: str):
    now = datetime.now(timezone.utc).isoformat()
    async with database.with_admin() as conn:
        invite = await conn.fetchrow(
            "SELECT * FROM invitations WHERE token = $1 AND used_at IS NULL", token
        )
        if not invite:
            raise HTTPException(status_code=404, detail="Invitation not found or already used")
        if invite["expires_at"] < now:
            raise HTTPException(status_code=410, detail="Invitation link has expired")
        user = await conn.fetchrow("SELECT email, name FROM users WHERE id = $1", invite["user_id"])
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        org = await conn.fetchrow("SELECT name FROM organisations WHERE id = $1", invite["org_id"])
    return {
        "email": user["email"],
        "name": user["name"],
        "org_name": org["name"] if org else "Your Organisation",
    }


class AcceptInviteRequest(BaseModel):
    token: str
    name: str
    password: str


@router.post("/accept-invite")
async def accept_invite(data: AcceptInviteRequest, response: Response):
    validate_password_strength(data.password)
    now = datetime.now(timezone.utc).isoformat()
    async with database.with_admin() as conn:
        invite = await conn.fetchrow(
            "SELECT * FROM invitations WHERE token = $1 AND used_at IS NULL", data.token
        )
        if not invite:
            raise HTTPException(status_code=404, detail="Invitation not found or already used")
        if invite["expires_at"] < now:
            raise HTTPException(status_code=410, detail="Invitation link has expired")
        user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", invite["user_id"])
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        name = data.name.strip() or user["name"]
        await conn.execute(
            """UPDATE users SET password_hash=$1, name=$2, is_active=TRUE,
               must_change_password=FALSE WHERE id=$3""",
            hash_password(data.password), name, invite["user_id"],
        )
        await conn.execute("UPDATE invitations SET used_at=$1 WHERE token=$2", now, data.token)

    user_id = invite["user_id"]
    email = user["email"]
    access_token = create_access_token(user_id, email)
    refresh_token_val = create_refresh_token(user_id)
    set_auth_cookies(response, access_token, refresh_token_val)
    return {
        "id": user_id,
        "email": email,
        "name": name,
        "role": user["role"],
        "token": access_token,
        "refresh_token": refresh_token_val,
    }
