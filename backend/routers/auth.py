from fastapi import APIRouter, HTTPException, Depends, Response, Request
from pydantic import BaseModel, EmailStr
from bson import ObjectId
import bcrypt
import jwt
import os
import secrets
import resend
from datetime import datetime, timezone, timedelta
from deps import get_db, get_current_user

router = APIRouter()
JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


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
    response.set_cookie("access_token", access_token, httponly=True, secure=False, samesite="lax", max_age=28800, path="/")  # noqa: E501
    response.set_cookie("refresh_token", refresh_token, httponly=True, secure=False, samesite="lax", max_age=604800, path="/")  # noqa: E501


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str
    # role is accepted for API compatibility but always overridden to "attendee" on public registration
    role: str = "attendee"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/register")
async def register(data: RegisterRequest, response: Response, db=Depends(get_db)):
    email = data.email.lower()
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    # Public self-registration is always attendee — elevated roles require admin/super-admin
    role = "attendee"
    user_doc = {
        "email": email,
        "password_hash": hash_password(data.password),
        "name": data.name,
        "role": role,
        "is_active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    result = await db.users.insert_one(user_doc)
    user_id = str(result.inserted_id)
    access_token = create_access_token(user_id, email)
    refresh_token = create_refresh_token(user_id)
    set_auth_cookies(response, access_token, refresh_token)
    return {"id": user_id, "email": email, "name": data.name, "role": role, "token": access_token, "refresh_token": refresh_token}


@router.post("/login")
async def login(data: LoginRequest, response: Response, request: Request, db=Depends(get_db)):
    email = data.email.lower()
    identifier = f"{request.client.host}:{email}"

    # Check brute force
    attempts = await db.login_attempts.find_one({"identifier": identifier})
    if attempts and attempts.get("count", 0) >= 5:
        lockout_until = attempts.get("locked_until")
        if lockout_until and datetime.fromisoformat(lockout_until) > datetime.now(timezone.utc):
            raise HTTPException(status_code=429, detail="Account temporarily locked. Try again later.")

    user = await db.users.find_one({"email": email})
    if not user or not verify_password(data.password, user.get("password_hash", "")):
        await db.login_attempts.update_one(
            {"identifier": identifier},
            {"$inc": {"count": 1}, "$set": {"locked_until": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()}},  # noqa: E501
            upsert=True,
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")

    await db.login_attempts.delete_one({"identifier": identifier})
    user_id = str(user["_id"])
    access_token = create_access_token(user_id, email)
    refresh_token = create_refresh_token(user_id)
    set_auth_cookies(response, access_token, refresh_token)
    return {"id": user_id, "email": email, "name": user["name"], "role": user["role"], "token": access_token, "refresh_token": refresh_token}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return {"message": "Logged out"}


@router.get("/me")
async def me(current_user=Depends(get_current_user), db=Depends(get_db)):
    org_id = current_user.get("org_id")
    if org_id:
        try:
            org = await db.organisations.find_one({"_id": ObjectId(org_id)})
            if org:
                b = org.get("branding") or {}
                current_user["org_branding"] = {
                    "has_logo": bool(b.get("logo_path")),
                    "primary_color": b.get("primary_color"),
                }
                current_user["org_name"] = org.get("name", "")
        except Exception:
            pass
    return current_user


@router.post("/refresh")
async def refresh_token(request: Request, response: Response, db=Depends(get_db)):
    # Accept refresh token from cookie OR Authorization header (for non-cookie clients)
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
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        if not user.get("is_active", True):
            raise HTTPException(status_code=401, detail="Account is deactivated")
        user_id = str(user["_id"])
        new_access = create_access_token(user_id, user["email"])
        new_refresh = create_refresh_token(user_id)
        response.set_cookie("access_token", new_access, httponly=True, secure=False, samesite="lax", max_age=86400, path="/")  # noqa: E501
        response.set_cookie("refresh_token", new_refresh, httponly=True, secure=False, samesite="lax", max_age=604800, path="/")  # noqa: E501
        return {"access_token": new_access, "refresh_token": new_refresh, "message": "Token refreshed"}
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordRequest, db=Depends(get_db)):
    email = data.email.lower()
    user = await db.users.find_one({"email": email})
    # Always return success to prevent email enumeration
    if not user:
        return {"message": "If that email exists, a reset link has been sent."}

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    await db.password_reset_tokens.delete_many({"email": email})
    await db.password_reset_tokens.insert_one({
        "token": token,
        "email": email,
        "expires_at": expires_at,
        "used": False,
    })

    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
    reset_link = f"{frontend_url}/reset-password?token={token}"

    resend.api_key = os.environ.get("RESEND_API_KEY", "")
    sender = os.environ.get("SENDER_EMAIL", "noreply@1two.one")
    try:
        resend.Emails.send({
            "from": f"1two.one <{sender}>",
            "to": [email],
            "subject": "Reset your password",
            "html": (
                "<div style='font-family:Poppins,sans-serif;max-width:480px;margin:0 auto;"
                "padding:32px 24px;background:#f8fafc;border-radius:12px;'>"
                f"<h2 style='color:#1E3A8A;font-size:22px;margin-bottom:8px;'>Reset your password</h2>"
                "<p style='color:#475569;font-size:15px;margin-bottom:24px;'>Click the button below to set a new password. "  # noqa: E501
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
        pass  # Don't expose email sending errors

    return {"message": "If that email exists, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(data: ResetPasswordRequest, db=Depends(get_db)):
    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    record = await db.password_reset_tokens.find_one({"token": data.token, "used": False})
    if not record:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link.")
    if record["expires_at"].replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="This reset link has expired.")

    await db.users.update_one(
        {"email": record["email"]},
        {"$set": {"password_hash": hash_password(data.new_password)}}
    )
    await db.password_reset_tokens.update_one({"token": data.token}, {"$set": {"used": True}})

    return {"message": "Password updated successfully. You can now log in."}


async def seed_admin(db):
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@supervision.com")
    admin_password = os.environ.get("ADMIN_PASSWORD", "Admin123!")
    existing = await db.users.find_one({"email": admin_email})
    if existing is None:
        await db.users.insert_one({
            "email": admin_email,
            "password_hash": hash_password(admin_password),
            "name": "Admin",
            "role": "admin",
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    elif not verify_password(admin_password, existing.get("password_hash", "")):
        await db.users.update_one({"email": admin_email}, {"$set": {"password_hash": hash_password(admin_password)}})

    # Seed test manager and attendee
    for test_user in [
        {"email": "manager@supervision.com", "name": "Test Manager", "role": "manager", "password": "Manager123!"},
        {"email": "staff@supervision.com", "name": "Test Staff", "role": "attendee", "password": "Staff123!"},
    ]:
        exists = await db.users.find_one({"email": test_user["email"]})
        if not exists:
            await db.users.insert_one({
                "email": test_user["email"],
                "password_hash": hash_password(test_user["password"]),
                "name": test_user["name"],
                "role": test_user["role"],
                "is_active": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })



# ── Invite acceptance (public endpoints) ─────────────────────────────────────

@router.get("/invite/{token}")
async def validate_invite(token: str, db=Depends(get_db)):
    """Check if an invite token is valid and return the associated user/org info."""
    now = datetime.now(timezone.utc).isoformat()
    invite = await db.invitations.find_one({"token": token, "used_at": {"$exists": False}})
    if not invite:
        raise HTTPException(status_code=404, detail="Invitation not found or already used")
    if invite.get("expires_at", "") < now:
        raise HTTPException(status_code=410, detail="Invitation link has expired")

    user = await db.users.find_one({"_id": ObjectId(invite["user_id"])})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    org = await db.organisations.find_one({"_id": ObjectId(invite["org_id"])})
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
async def accept_invite(data: AcceptInviteRequest, response: Response, db=Depends(get_db)):
    """Claim an invite: set password, activate the user, return a JWT session."""
    if len(data.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    now = datetime.now(timezone.utc).isoformat()
    invite = await db.invitations.find_one({"token": data.token, "used_at": {"$exists": False}})
    if not invite:
        raise HTTPException(status_code=404, detail="Invitation not found or already used")
    if invite.get("expires_at", "") < now:
        raise HTTPException(status_code=410, detail="Invitation link has expired")

    user = await db.users.find_one({"_id": ObjectId(invite["user_id"])})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Activate user with the chosen password
    name = data.name.strip() or user["name"]
    await db.users.update_one(
        {"_id": ObjectId(invite["user_id"])},
        {"$set": {
            "password_hash": hash_password(data.password),
            "name": name,
            "is_active": True,
        }}
    )

    # Mark invite as used (single-use)
    await db.invitations.update_one({"token": data.token}, {"$set": {"used_at": now}})

    # Return the same shape as /login so the frontend can log in immediately
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
