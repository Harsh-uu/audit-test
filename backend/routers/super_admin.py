from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from bson import ObjectId
from datetime import datetime, timezone, timedelta
from typing import Optional
import re as _re
import secrets
import asyncio
import os
import logging
from deps import get_db, get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


def _slugify(name: str) -> str:
    return _re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def _to(doc):
    if doc is None:
        return None
    doc = dict(doc)
    doc["id"] = str(doc["_id"])
    del doc["_id"]
    return doc


def _require_super_admin(current_user):
    if current_user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin only")


class CreateOrgRequest(BaseModel):
    name: str


class UpdateOrgRequest(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None  # active | suspended


class OrgBrandingUpdate(BaseModel):
    primary_color: Optional[str] = None
    logo_url: Optional[str] = None  # "" to clear logo


class CreateOrgUserRequest(BaseModel):
    email: EmailStr
    name: str
    password: str
    role: str = "manager"


class UpdateOrgUserRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    password: Optional[str] = None   # only updated if provided


@router.get("/orgs")
async def list_orgs(db=Depends(get_db), current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    orgs = []
    async for org in db.organisations.find({}).sort("name", 1):
        org_id = str(org["_id"])
        user_count = await db.users.count_documents({"org_id": org_id})
        meeting_count = await db.meetings.count_documents({"org_id": org_id})
        orgs.append({
            "id": org_id,
            "name": org["name"],
            "slug": org.get("slug", ""),
            "status": org.get("status", "active"),
            "created_at": org.get("created_at"),
            "user_count": user_count,
            "meeting_count": meeting_count,
        })
    return orgs


@router.post("/orgs")
async def create_org(data: CreateOrgRequest, db=Depends(get_db), current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    slug = _slugify(data.name)
    existing = await db.organisations.find_one({"slug": slug})
    if existing:
        raise HTTPException(status_code=400, detail="Organisation with this name already exists")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "name": data.name.strip(),
        "slug": slug,
        "status": "active",
        "created_at": now,
    }
    result = await db.organisations.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    del doc["_id"]
    return doc


@router.patch("/orgs/{org_id}")
async def update_org(org_id: str, data: UpdateOrgRequest, db=Depends(get_db), current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    try:
        obj_id = ObjectId(org_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid org ID")
    existing = await db.organisations.find_one({"_id": obj_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Organisation not found")
    update = {}
    if data.name is not None:
        update["name"] = data.name.strip()
        update["slug"] = _slugify(data.name)
    if data.status is not None and data.status in ["active", "suspended"]:
        update["status"] = data.status
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.organisations.update_one({"_id": obj_id}, {"$set": update})
    return {"message": "Organisation updated"}


@router.put("/orgs/{org_id}/branding")
async def update_org_branding(org_id: str, data: OrgBrandingUpdate, db=Depends(get_db), current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    try:
        obj_id = ObjectId(org_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid org ID")
    update: dict = {}
    if data.primary_color is not None:
        update["branding.primary_color"] = data.primary_color
    if data.logo_url == "":
        update["branding.logo_path"] = None
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.organisations.update_one({"_id": obj_id}, {"$set": update})
    return {"message": "Branding updated"}


@router.get("/orgs/{org_id}/users")
async def list_org_users(org_id: str, db=Depends(get_db), current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    users = []
    async for doc in db.users.find({"org_id": org_id}, {"password_hash": 0}).sort("name", 1):
        users.append(_to(doc))
    return users


@router.post("/orgs/{org_id}/users")
async def create_org_user(
    org_id: str,
    data: CreateOrgUserRequest,
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    _require_super_admin(current_user)
    try:
        obj_id = ObjectId(org_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid org ID")
    org = await db.organisations.find_one({"_id": obj_id})
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    from routers.auth import hash_password
    existing = await db.users.find_one({"email": data.email.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="Email already exists")
    role = data.role if data.role in ["admin", "manager", "attendee", "shared_reviewer"] else "manager"
    doc = {
        "email": data.email.lower(),
        "password_hash": hash_password(data.password),
        "name": data.name.strip(),
        "role": role,
        "org_id": org_id,
        "is_active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    result = await db.users.insert_one(doc)
    return {
        "id": str(result.inserted_id),
        "email": doc["email"],
        "name": doc["name"],
        "role": doc["role"],
        "org_id": org_id,
    }


@router.patch("/orgs/{org_id}/users/{user_id}")
async def update_org_user(
    org_id: str,
    user_id: str,
    data: UpdateOrgUserRequest,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    _require_super_admin(current_user)
    try:
        uid = ObjectId(user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user ID")

    user = await db.users.find_one({"_id": uid, "org_id": org_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found in this organisation")

    updates: dict = {}
    if data.name is not None:
        updates["name"] = data.name.strip()
    if data.email is not None:
        email_lower = data.email.lower()
        clash = await db.users.find_one({"email": email_lower, "_id": {"$ne": uid}})
        if clash:
            raise HTTPException(status_code=400, detail="Email already in use by another account")
        updates["email"] = email_lower
    if data.role is not None:
        valid_roles = {"admin", "manager", "attendee", "shared_reviewer"}
        if data.role not in valid_roles:
            raise HTTPException(status_code=400, detail=f"Role must be one of {valid_roles}")
        updates["role"] = data.role
    if data.password:
        from routers.auth import hash_password
        updates["password_hash"] = hash_password(data.password)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.users.update_one({"_id": uid}, {"$set": updates})

    updated = await db.users.find_one({"_id": uid}, {"password_hash": 0})
    return _to(updated)


@router.delete("/orgs/{org_id}/users/{user_id}", status_code=204)
async def delete_org_user(
    org_id: str,
    user_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    _require_super_admin(current_user)
    try:
        uid = ObjectId(user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user ID")

    user = await db.users.find_one({"_id": uid, "org_id": org_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found in this organisation")

    await db.users.delete_one({"_id": uid})


# ── Invite Admin ──────────────────────────────────────────────────────────────

class InviteAdminRequest(BaseModel):
    email: EmailStr
    name: str


def _build_invite_email(name: str, org_name: str, invite_link: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<body style="margin:0;padding:0;background:#F1F5F9;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="padding:40px 16px;">
  <tr><td align="center">
    <table width="520" cellpadding="0" cellspacing="0" style="background:white;border-radius:12px;overflow:hidden;box-shadow:0 4px 32px rgba(0,0,0,0.10);">

      <!-- Header -->
      <tr><td style="background:#1E3A8A;padding:32px 40px;">
        <p style="color:white;margin:0;font-size:24px;font-weight:700;letter-spacing:-0.5px;">1two.one</p>
        <p style="color:rgba(255,255,255,0.60);margin:6px 0 0;font-size:13px;font-weight:500;">Care Supervision Platform</p>
      </td></tr>

      <!-- Body -->
      <tr><td style="padding:40px 40px 32px;">
        <h2 style="color:#111827;font-size:20px;margin:0 0 20px;font-weight:700;">You've been invited to join {org_name}</h2>
        <p style="color:#4B5563;font-size:15px;line-height:1.7;margin:0 0 10px;">Hi {name},</p>
        <p style="color:#4B5563;font-size:15px;line-height:1.7;margin:0 0 10px;">
          Your account has been created on <strong>1two.one</strong> as an
          <strong>Organisation Admin</strong> for <strong>{org_name}</strong>.
        </p>
        <p style="color:#4B5563;font-size:15px;line-height:1.7;margin:0 0 32px;">
          Click the button below to set your password and get started. This link expires in
          <strong>72 hours</strong>.
        </p>

        <!-- CTA -->
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr><td align="center" style="padding-bottom:32px;">
            <a href="{invite_link}"
               style="background:#1E3A8A;color:white;padding:14px 40px;text-decoration:none;
                      border-radius:8px;font-weight:600;font-size:15px;display:inline-block;
                      letter-spacing:0.2px;">
              Accept Invitation &rarr;
            </a>
          </td></tr>
        </table>

        <p style="color:#9CA3AF;font-size:13px;text-align:center;margin:0;line-height:1.6;">
          If you weren&rsquo;t expecting this invitation, you can safely ignore this email.
        </p>
      </td></tr>

      <!-- Footer -->
      <tr><td style="padding:20px 40px;border-top:1px solid #F3F4F6;background:#F9FAFB;">
        <p style="color:#9CA3AF;font-size:12px;margin:0;text-align:center;">
          &copy; 2025 1two.one &mdash; Supervision &amp; Compliance Platform
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""


@router.post("/orgs/{org_id}/invite")
async def invite_org_admin(
    org_id: str,
    data: InviteAdminRequest,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    _require_super_admin(current_user)
    try:
        obj_id = ObjectId(org_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid org ID")
    org = await db.organisations.find_one({"_id": obj_id})
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    existing = await db.users.find_one({"email": data.email.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    # Create inactive user — activated when they accept the invite
    from routers.auth import hash_password
    user_doc = {
        "email": data.email.lower(),
        "password_hash": hash_password(secrets.token_urlsafe(32)),  # placeholder
        "name": data.name.strip(),
        "role": "admin",
        "org_id": org_id,
        "is_active": False,  # activated on invite acceptance
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    user_result = await db.users.insert_one(user_doc)
    user_id = str(user_result.inserted_id)

    # Generate single-use invite token (72-hour expiry)
    token = secrets.token_urlsafe(32)
    await db.invitations.insert_one({
        "token": token,
        "user_id": user_id,
        "org_id": org_id,
        "email": data.email.lower(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    frontend_url = os.environ.get("FRONTEND_URL", "")
    invite_link = f"{frontend_url}/accept-invite?token={token}"

    try:
        import resend
        resend.api_key = os.environ.get("RESEND_API_KEY", "")
        html = _build_invite_email(data.name.strip(), org["name"], invite_link)
        await asyncio.to_thread(resend.Emails.send, {
            "from": os.environ.get("SENDER_EMAIL", "onboarding@resend.dev"),
            "to": [data.email.lower()],
            "subject": f"You've been invited to join {org['name']} on 1two.one",
            "html": html,
        })
        logger.info(f"Invite email sent to {data.email}")
    except Exception as e:
        logger.warning(f"Invite email failed (user still created): {e}")
        # Return the link so super admin can share it manually
        return {
            "message": "User created but email failed to send — share the link below manually.",
            "invite_link": invite_link,
            "user_id": user_id,
            "email_failed": True,
        }

    return {"message": f"Invitation sent to {data.email}", "user_id": user_id}
