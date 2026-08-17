from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, EmailStr
import bcrypt
import jwt
import os
import re
import uuid
import secrets
import logging
import resend
from datetime import datetime, timezone, timedelta
from deps import get_db, get_current_user
import database

logger = logging.getLogger(__name__)

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


def _to_pwd_ts(user: dict) -> float:
    """Convert a user's password_changed_at field to a Unix float for JWT embedding."""
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


def create_access_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
        "type": "access",
    }
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str, pwd_ts: float = 0.0) -> str:
    """
    pwd_ts: Unix timestamp of the user's last password change.
    The refresh endpoint rejects any token where pwd_ts < current password_changed_at,
    so stolen tokens are cut off immediately after a password reset.
    """
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "type": "refresh",
        "pwd_ts": pwd_ts,
    }
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm=JWT_ALGORITHM)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: str = "attendee"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class VerifyMfaRequest(BaseModel):
    mfa_session: str
    code: str


class MfaConfirmRequest(BaseModel):
    code: str


# ── MFA helpers ──────────────────────────────────────────────────────────────

MFA_REQUIRES_ROLES = {"super_admin", "admin", "manager"}


def _mfa_required_for_role(role: str, mfa_enabled: bool) -> bool:
    """Admins, managers and super_admins always require MFA — mandatory, not opt-in."""
    return role in ("super_admin", "admin", "manager")


def create_mfa_session_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "type": "mfa_pending",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
    }
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm=JWT_ALGORITHM)


async def _generate_and_send_mfa(conn, user: dict) -> None:
    """Generate a 6-digit OTP, hash it, store it, and email it to the user."""
    code = f"{secrets.randbelow(1000000):06d}"
    code_hash = bcrypt.hashpw(code.encode(), bcrypt.gensalt()).decode()
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    await conn.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE id=$3",
        code_hash, expires_at, user["id"],
    )
    resend.api_key = os.environ.get("RESEND_API_KEY", "")
    try:
        resend.Emails.send({
            "from": "Supervision 2 <noreply@notify.1two.one>",
            "to": [user["email"]],
            "subject": "Your verification code",
            "html": (
                "<div style='font-family:Poppins,sans-serif;max-width:480px;margin:0 auto;"
                "padding:32px 24px;background:#f8fafc;border-radius:12px;'>"
                "<h2 style='color:#1E3A8A;font-size:22px;margin-bottom:8px;'>Verification code</h2>"
                f"<p style='color:#475569;font-size:15px;margin-bottom:20px;'>Hi {user.get('name','')}, "
                "enter the code below to complete your sign-in. It expires in <strong>10 minutes</strong>.</p>"
                f"<div style='font-size:36px;font-weight:700;letter-spacing:10px;color:#1E3A8A;"
                f"text-align:center;padding:20px 0;'>{code}</div>"
                "<p style='color:#94a3b8;font-size:12px;margin-top:24px;'>"
                "If you didn't attempt to sign in, your account may be at risk — "
                "please change your password immediately.</p></div>"
            ),
        })
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(f"MFA email send failed: {exc}")


@router.post("/register")
async def register(_data: dict = {}):
    """Self-registration is disabled — users must be invited by an organisation admin."""
    raise HTTPException(
        status_code=403,
        detail="Self-registration is disabled. Contact your organisation admin to receive an invitation.",
    )


@router.post("/login")
async def login(data: LoginRequest, request: Request):
    email = data.email.lower()
    identifier = email.lower()  # email-only — ingress pod IPs are unreliable in k8s/proxy setups

    # ── IP-wide secondary rate limit (20 per IP / 15 min) ────────────────────
    # Wrapped in try/except: a rate-limit DB failure must never block login
    # or return an unparseable response to the CDN.
    from utils.rate_limit import check_rate_limit
    xff = request.headers.get("X-Forwarded-For", "")
    _ip = (
        request.headers.get("X-Real-IP")
        or (xff.split(",")[-1].strip() if xff else None)
        or (request.client.host if request.client else "unknown")
    )
    try:
        async with database.with_admin() as _rl_conn:
            await check_rate_limit(
                _rl_conn,
                identifier=f"login_ip:{_ip}",
                max_attempts=20,
                window_minutes=15,
                error_detail="Too many login attempts from this location. Please wait 15 minutes before trying again.",
            )
    except HTTPException:
        raise  # legitimate 429 — re-raise as-is
    except Exception as _rl_err:
        logger.warning("IP rate-limit check failed (non-critical): %s", _rl_err)

    # ── Step 1: lockout check ─────────────────────────────────────────────────
    async with database.with_admin() as conn:
        attempts_row = await conn.fetchrow("SELECT count, locked_until FROM login_attempts WHERE identifier = $1", identifier)
    if attempts_row and attempts_row["count"] >= 3:
        lockout_until = attempts_row.get("locked_until")
        if lockout_until and lockout_until > datetime.now(timezone.utc).isoformat():
            raise HTTPException(status_code=429, detail="Too many failed attempts — your account is temporarily locked. Use the Forgot Password link to reset your access.")

    # ── Step 2: credential check ──────────────────────────────────────────────
    async with database.with_admin() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE email = $1", email)

    password_ok = bool(user and verify_password(data.password, user["password_hash"] or ""))

    # ── Step 3: record failed attempt (committed separately so rollback can't undo it)
    if not password_ok:
        now = datetime.now(timezone.utc).isoformat()
        locked_until = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        new_count = 1
        async with database.with_admin() as conn:
            result = await conn.fetchrow(
                """INSERT INTO login_attempts (identifier, count, locked_until, updated_at)
                   VALUES ($1, 1, $2, $3)
                   ON CONFLICT (identifier) DO UPDATE
                   SET count = login_attempts.count + 1,
                       locked_until = $2,
                       updated_at = $3
                   RETURNING count""",
                identifier, locked_until, now,
            )
            if result:
                new_count = result["count"]
        # Raise OUTSIDE the block so the INSERT is committed
        if new_count >= 3:
            raise HTTPException(status_code=401, detail="Invalid credentials — your account has been temporarily locked after 3 failed attempts. Use the Forgot Password link below to reset your access.")
        elif new_count == 2:
            raise HTTPException(status_code=401, detail="Invalid credentials — if you've forgotten your password, use the Forgot Password link below to reset your account.")
        else:
            raise HTTPException(status_code=401, detail="Invalid credentials")

    # ── Step 4: clear attempts on success ─────────────────────────────────────
    async with database.with_admin() as conn:
        await conn.execute("DELETE FROM login_attempts WHERE identifier = $1", identifier)

    user = dict(user)
    user_id = user["id"]

    # ── MFA gate ──────────────────────────────────────────────────────────────
    if _mfa_required_for_role(user["role"], bool(user.get("mfa_enabled"))):
        async with database.with_admin() as conn2:
            await _generate_and_send_mfa(conn2, user)
        mfa_session = create_mfa_session_token(user_id)
        return {
            "requires_mfa": True,
            "mfa_session": mfa_session,
        }

    access_token = create_access_token(user_id, user["email"])
    refresh_token = create_refresh_token(user_id, _to_pwd_ts(user))
    return {
        "id": user_id, "email": user["email"], "name": user["name"], "role": user["role"],
        "token": access_token, "refresh_token": refresh_token,
        "must_change_password": user.get("must_change_password", False),
    }


@router.post("/logout")
async def logout():
    return {"message": "Logged out"}


@router.post("/verify-mfa")
async def verify_mfa(data: VerifyMfaRequest):
    """Complete MFA login: validate OTP and issue full JWT."""
    try:
        payload = jwt.decode(data.mfa_session, os.environ["JWT_SECRET"], algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "mfa_pending":
            raise HTTPException(status_code=401, detail="Invalid session token")
        user_id = payload["sub"]
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")

    # ── Rate limit: 5 attempts per user / 30 min ─────────────────────────────
    from utils.rate_limit import check_rate_limit
    try:
        async with database.with_admin() as _rl_conn:
            await check_rate_limit(
                _rl_conn,
                identifier=f"mfa_uid:{user_id}",
                max_attempts=5,
                window_minutes=30,
                error_detail="Too many verification attempts. Please wait 30 minutes before trying again.",
            )
    except HTTPException:
        raise
    except Exception as _rl_err:
        logger.warning("MFA rate-limit check failed (non-critical): %s", _rl_err)

    async with database.with_admin() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE id=$1", user_id)
        if not user or not user["is_active"]:
            raise HTTPException(status_code=401, detail="User not found or inactive")
        user = dict(user)

        if (user.get("mfa_code_attempts") or 0) >= 5:
            raise HTTPException(status_code=429, detail="Too many attempts. Please sign in again to get a new code.")

        expires_at = user.get("mfa_code_expires_at") or ""
        if not expires_at or expires_at < datetime.now(timezone.utc).isoformat():
            raise HTTPException(status_code=401, detail="Code expired. Please sign in again.")

        code_hash = user.get("mfa_code") or ""
        if not code_hash or not bcrypt.checkpw(data.code.strip().encode(), code_hash.encode()):
            await conn.execute(
                "UPDATE users SET mfa_code_attempts = COALESCE(mfa_code_attempts, 0) + 1 WHERE id=$1",
                user_id,
            )
            raise HTTPException(status_code=401, detail="Invalid code")

        await conn.execute(
            "UPDATE users SET mfa_code=NULL, mfa_code_expires_at=NULL, mfa_code_attempts=0 WHERE id=$1",
            user_id,
        )

    access_token = create_access_token(user_id, user["email"])
    refresh_token = create_refresh_token(user_id, _to_pwd_ts(user))
    return {
        "id": user_id, "email": user["email"], "name": user["name"], "role": user["role"],
        "token": access_token, "refresh_token": refresh_token,
        "must_change_password": user.get("must_change_password", False),
    }


@router.post("/request-mfa-code")
async def request_mfa_code(current_user=Depends(get_current_user)):
    """Send OTP to current user's email for MFA enable/disable confirmation."""
    if current_user["role"] not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="MFA toggle is only available for admin and manager roles")
    async with database.with_admin() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE id=$1", current_user["id"])
        await _generate_and_send_mfa(conn, dict(user))
    return {"message": "A verification code has been sent to your email"}


class ToggleMfaRequest(BaseModel):
    code: str
    enable: bool


@router.post("/toggle-mfa")
async def toggle_mfa(data: ToggleMfaRequest, current_user=Depends(get_current_user)):
    """Enable or disable MFA for the current user after OTP verification."""
    if current_user["role"] not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="MFA toggle is only available for admin and manager roles")

    async with database.with_admin() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE id=$1", current_user["id"])
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        user = dict(user)

        if (user.get("mfa_code_attempts") or 0) >= 5:
            raise HTTPException(status_code=429, detail="Too many attempts. Please request a new code.")

        expires_at = user.get("mfa_code_expires_at") or ""
        if not expires_at or expires_at < datetime.now(timezone.utc).isoformat():
            raise HTTPException(status_code=401, detail="Code expired. Please request a new code.")

        code_hash = user.get("mfa_code") or ""
        if not code_hash or not bcrypt.checkpw(data.code.strip().encode(), code_hash.encode()):
            await conn.execute(
                "UPDATE users SET mfa_code_attempts = COALESCE(mfa_code_attempts, 0) + 1 WHERE id=$1",
                current_user["id"],
            )
            raise HTTPException(status_code=401, detail="Invalid code")

        await conn.execute(
            "UPDATE users SET mfa_enabled=$1, mfa_code=NULL, mfa_code_expires_at=NULL, mfa_code_attempts=0 WHERE id=$2",
            data.enable, current_user["id"],
        )

    return {"message": f"Two-factor authentication {'enabled' if data.enable else 'disabled'}", "mfa_enabled": data.enable}


@router.get("/me")
async def me(current_user=Depends(get_current_user)):
    import json as _json
    user = dict(current_user)
    user.pop("password_hash", None)
    user.pop("mfa_code", None)
    user.pop("mfa_code_expires_at", None)
    user.pop("mfa_code_attempts", None)
    org_id = user.get("org_id")
    if org_id:
        async with database.with_admin() as conn:
            org = await conn.fetchrow("SELECT name, branding, jurisdiction, service_type FROM organisations WHERE id = $1", org_id)
        if org:
            _b_raw = org["branding"]
            # Safely parse branding — handles None, "{}", "null", or dict
            if isinstance(_b_raw, str):
                try:
                    b = _json.loads(_b_raw)
                except Exception:
                    b = {}
            else:
                b = _b_raw
            if not isinstance(b, dict):
                b = {}
            user["org_branding"] = {
                "has_logo": bool(b.get("logo_path")),
                "primary_color": b.get("primary_color"),
            }
            user["org_name"] = org["name"] or ""
            user["org_jurisdiction"] = org["jurisdiction"] or "england"
            user["org_service_type"] = org["service_type"] or ""
    # Strip internal fields never consumed by the frontend
    for _f in ("password_changed_at", "is_active", "updated_at"):
        user.pop(_f, None)
    return user


@router.post("/refresh")
async def refresh_token(request: Request):
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else None
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        payload = jwt.decode(token, os.environ["JWT_SECRET"], algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")

        # SEC-001: reject tokens issued before the last password change.
        # Tokens without the pwd_ts claim are from before this fix — force re-login.
        token_pwd_ts = payload.get("pwd_ts")
        if token_pwd_ts is None:
            raise HTTPException(status_code=401, detail="Session expired — please sign in again.")

        async with database.with_admin() as conn:
            user = await conn.fetchrow(
                "SELECT id, email, is_active, password_changed_at FROM users WHERE id = $1", payload["sub"]
            )
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        if not user["is_active"]:
            raise HTTPException(status_code=401, detail="Account is deactivated")

        db_pwd_ts = _to_pwd_ts(dict(user))
        if token_pwd_ts < db_pwd_ts:
            raise HTTPException(status_code=401, detail="Password changed — please sign in again.")

        user_id = user["id"]
        new_access = create_access_token(user_id, user["email"])
        new_refresh = create_refresh_token(user_id, db_pwd_ts)
        return {"access_token": new_access, "refresh_token": new_refresh, "message": "Token refreshed"}
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordRequest, request: Request):
    email = data.email.lower()
    # H2: Prefer X-Real-IP (set by nginx/k8s ingress to the verified client IP).
    # Fall back to the rightmost X-Forwarded-For hop (added by the last trusted proxy,
    # not client-controlled) rather than the leftmost (which the client can forge).
    xff = request.headers.get("X-Forwarded-For", "")
    ip = (
        request.headers.get("X-Real-IP")
        or (xff.split(",")[-1].strip() if xff else None)
        or (request.client.host if request.client else "unknown")
    )

    async with database.with_admin() as conn:
        # Rate limit: 5 attempts per IP per 15 minutes
        from utils.rate_limit import check_rate_limit
        await check_rate_limit(
            conn,
            identifier=f"fp_ip:{ip}",
            max_attempts=5,
            window_minutes=15,
            error_detail="Too many password reset requests. Please wait 15 minutes before trying again.",
        )

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
async def accept_invite(data: AcceptInviteRequest):
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
            """UPDATE users SET password_hash=$1, name=$2, org_id=$3, is_active=TRUE,
               must_change_password=FALSE, password_changed_at=$5 WHERE id=$4""",
            hash_password(data.password), name, invite["org_id"], invite["user_id"], now,
        )
        await conn.execute("UPDATE invitations SET used_at=$1 WHERE token=$2", now, data.token)

    user_id = invite["user_id"]
    email = user["email"]
    # password_changed_at was just set to `now` in the UPDATE above — use it as
    # pwd_ts so the refresh token is valid immediately (pwd_ts=0.0 would be
    # rejected by the refresh endpoint because 0.0 < now).
    access_token = create_access_token(user_id, email)
    refresh_token_val = create_refresh_token(user_id, _to_pwd_ts({"password_changed_at": now}))
    return {
        "id": user_id,
        "email": email,
        "name": name,
        "role": user["role"],
        "token": access_token,
        "refresh_token": refresh_token_val,
    }
