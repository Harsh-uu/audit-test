import uuid
import re as _re
import secrets
import asyncio
import os
import logging
import html
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from datetime import datetime, timezone, timedelta
from typing import Optional
from deps import get_db, get_current_user
import database
from utils.supabase_storage import delete_audio

router = APIRouter()
logger = logging.getLogger(__name__)


def _slugify(name: str) -> str:
    return _re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def _require_super_admin(current_user):
    if current_user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin only")


VALID_JURISDICTIONS = ("england", "wales", "scotland", "northern_ireland")
VALID_SERVICE_TYPES = ("residential", "domiciliary")


class CreateOrgRequest(BaseModel):
    name: str
    jurisdiction: Optional[str] = "england"
    service_type: Optional[str] = None  # required for northern_ireland


class UpdateOrgRequest(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    jurisdiction: Optional[str] = None
    service_type: Optional[str] = None


class OrgBrandingUpdate(BaseModel):
    primary_color: Optional[str] = None
    logo_url: Optional[str] = None


class CreateOrgUserRequest(BaseModel):
    email: EmailStr
    name: str
    password: str
    role: str = "manager"


class UpdateOrgUserRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    password: Optional[str] = None


@router.get("/orgs")
async def list_orgs(current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    async with database.with_admin() as conn:
        # Batched: one query with per-org counts as correlated subqueries,
        # instead of 2 extra round-trips per org (was 2N+1 queries total).
        org_rows = await conn.fetch(
            """SELECT o.*,
                      (SELECT COUNT(*) FROM users u WHERE u.org_id = o.id) AS user_count,
                      (SELECT COUNT(*) FROM meetings m WHERE m.org_id = o.id) AS meeting_count
               FROM organisations o ORDER BY o.name ASC"""
        )
        result = []
        for org in org_rows:
            result.append({
                "id": org["id"], "name": org["name"], "slug": org["slug"],
                "status": org["status"], "jurisdiction": org.get("jurisdiction") or "england",
                "service_type": org.get("service_type"),
                "created_at": org["created_at"],
                "user_count": org["user_count"], "meeting_count": org["meeting_count"],
            })
    return result


@router.post("/orgs")
async def create_org(data: CreateOrgRequest, current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    slug = _slugify(data.name)
    now = datetime.now(timezone.utc).isoformat()
    org_id = str(uuid.uuid4())
    async with database.with_admin() as conn:
        existing = await conn.fetchrow("SELECT id FROM organisations WHERE slug = $1", slug)
        if existing:
            raise HTTPException(status_code=400, detail="Organisation with this name already exists")
        jurisdiction = data.jurisdiction if data.jurisdiction in VALID_JURISDICTIONS else "england"
        service_type = data.service_type if data.service_type in VALID_SERVICE_TYPES else None
        # NI orgs must declare service_type
        if jurisdiction == "northern_ireland" and not service_type:
            raise HTTPException(status_code=400, detail="service_type ('residential' or 'domiciliary') is required for Northern Ireland organisations")
        await conn.execute(
            "INSERT INTO organisations (id, name, slug, status, branding, jurisdiction, service_type, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
            org_id, data.name.strip(), slug, "active", "{}", jurisdiction, service_type, now,
        )
    return {"id": org_id, "name": data.name.strip(), "slug": slug, "status": "active", "jurisdiction": jurisdiction, "service_type": service_type, "created_at": now}


@router.patch("/orgs/{org_id}")
async def update_org(org_id: str, data: UpdateOrgRequest, current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    updates = {}
    if data.name is not None:
        updates["name"] = data.name.strip()
        updates["slug"] = _slugify(data.name)
    if data.status in ("active", "suspended"):
        updates["status"] = data.status
    if data.jurisdiction in VALID_JURISDICTIONS:
        updates["jurisdiction"] = data.jurisdiction
    if data.service_type in VALID_SERVICE_TYPES:
        updates["service_type"] = data.service_type
    elif data.service_type == "" or (data.jurisdiction and data.jurisdiction != "northern_ireland"):
        # Clear service_type when switching away from NI
        updates["service_type"] = None

    # If switching TO northern_ireland, must provide service_type
    effective_jurisdiction = updates.get("jurisdiction") or data.jurisdiction
    if effective_jurisdiction == "northern_ireland":
        resolved_service_type = updates.get("service_type")
        if resolved_service_type is None and data.service_type not in VALID_SERVICE_TYPES:
            raise HTTPException(
                status_code=400,
                detail="service_type ('residential' or 'domiciliary') is required for Northern Ireland organisations",
            )

    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()

    set_clause = ", ".join(f"{k}=${i+2}" for i, k in enumerate(updates.keys()))
    async with database.with_admin() as conn:
        await conn.execute(f"UPDATE organisations SET {set_clause} WHERE id=$1", *([org_id] + list(updates.values())))
        from utils.standards_cache import invalidate_org
        invalidate_org(org_id)
    return {"message": "Organisation updated"}


@router.delete("/orgs/{org_id}", status_code=200)
async def delete_org(org_id: str, current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    async with database.with_admin() as conn:
        org = await conn.fetchrow("SELECT name FROM organisations WHERE id = $1", org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organisation not found")
        org_name = org["name"]
        totals = {}

        # Get meeting IDs
        meeting_ids = [r["id"] for r in await conn.fetch("SELECT id FROM meetings WHERE org_id = $1", org_id)]

        # Any audio must be deleted from storage too — fetch paths before the rows
        # disappear below. delete_audio() is idempotent on an already-removed path.
        audio_paths = []
        if meeting_ids:
            audio_paths = [
                r["storage_path"] for r in await conn.fetch(
                    "SELECT storage_path FROM audio_files WHERE meeting_id = ANY($1::uuid[]) AND storage_path IS NOT NULL",
                    meeting_ids,
                )
            ]

        if meeting_ids:
            for table in ["transcripts", "analyses", "audit_logs", "reviewer_comments", "review_edits", "audio_files", "evidence_feedback", "jobs"]:
                result = await conn.execute(f"DELETE FROM {table} WHERE meeting_id = ANY($1::uuid[])", meeting_ids)
                totals[table] = int(result.split()[-1])

        for table in ["meetings", "users", "schedules", "meeting_types", "standards_documents",
                       "supervision_uploads", "invitations", "settings"]:
            result = await conn.execute(f"DELETE FROM {table} WHERE org_id = $1", org_id)
            totals[table] = int(result.split()[-1])

        await conn.execute("DELETE FROM organisations WHERE id = $1", org_id)

    for path in audio_paths:
        try:
            await delete_audio(path)
        except Exception as e:
            logger.error("Failed to delete audio from storage during org '%s' deletion: path=%s error=%s", org_id, path, e)

    logger.info("Deleted org '%s' (%s): %s", org_name, org_id, totals)
    return {"message": f"Organisation '{org_name}' permanently deleted", "deleted": totals}


@router.get("/orgs/{org_id}/users")
async def list_org_users(org_id: str, current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    async with database.with_admin() as conn:
        rows = await conn.fetch(
            "SELECT id, org_id, email, name, role, is_active, team_id, setting_id, created_at FROM users WHERE org_id = $1 ORDER BY name ASC",
            org_id,
        )
    return [dict(r) for r in rows]


@router.post("/orgs/{org_id}/users")
async def create_org_user(org_id: str, data: CreateOrgUserRequest, current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    from routers.auth import hash_password, validate_password_strength
    from utils import supabase_auth
    validate_password_strength(data.password)
    role = data.role if data.role in ["admin", "manager", "attendee", "shared_reviewer"] else "manager"
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Phase 1: local insert only — commits and closes before any network call,
    # so the DB session never sits idle-in-transaction waiting on Supabase Auth
    # (which can exceed idle_in_transaction_session_timeout under load).
    async with database.with_admin() as conn:
        org = await conn.fetchrow("SELECT id FROM organisations WHERE id = $1", org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organisation not found")
        existing = await conn.fetchrow("SELECT id FROM users WHERE email = $1", data.email.lower())
        if existing:
            raise HTTPException(status_code=400, detail="Email already exists")
        await conn.execute(
            """INSERT INTO users (id, email, password_hash, name, role, org_id, is_active, must_change_password, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
            user_id, data.email.lower(), await hash_password(data.password),
            data.name.strip(), role, org_id, True, True, now,
        )

    # Phase 2: Supabase Auth network calls — deliberately outside any open
    # transaction. A failure here is logged and left for retry; the user can
    # still log in locally via password_hash until supabase_migrated is set.
    try:
        await supabase_auth.create_user(user_id, data.email.lower())
        await supabase_auth.set_password(user_id, data.password)
    except Exception as exc:
        logger.error("Supabase Auth provisioning failed for org user %s: %s", data.email, exc)
    else:
        # Phase 3: short follow-up transaction to persist the migration flags.
        async with database.with_admin() as conn:
            await conn.execute("UPDATE users SET supabase_migrated=TRUE, supabase_password_set=TRUE WHERE id=$1", user_id)
    return {"id": user_id, "email": data.email.lower(), "name": data.name.strip(), "role": role, "org_id": org_id}


@router.patch("/orgs/{org_id}/users/{user_id}")
async def update_org_user(org_id: str, user_id: str, data: UpdateOrgUserRequest, current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    updates = {}
    if data.name is not None:
        updates["name"] = data.name.strip()
    if data.role is not None:
        if data.role not in {"admin", "manager", "attendee", "shared_reviewer"}:
            raise HTTPException(status_code=400, detail="Invalid role")
        updates["role"] = data.role
    if data.password:
        from routers.auth import hash_password, validate_password_strength
        validate_password_strength(data.password)
        updates["password_hash"] = await hash_password(data.password)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()

    if data.email is not None:
        async with database.with_admin() as conn:
            clash = await conn.fetchrow(
                "SELECT id FROM users WHERE email = $1 AND id <> $2", data.email.lower(), user_id
            )
            if clash:
                raise HTTPException(status_code=400, detail="Email already in use")
        updates["email"] = data.email.lower()

    set_parts = [f"{k}=${i+2}" for i, k in enumerate(updates.keys())]
    async with database.with_admin() as conn:
        u = await conn.fetchrow("SELECT id FROM users WHERE id = $1 AND org_id = $2", user_id, org_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found in this organisation")
        await conn.execute(
            f"UPDATE users SET {', '.join(set_parts)} WHERE id=$1",
            user_id, *list(updates.values()),
        )
        row = await conn.fetchrow(
            "SELECT id, org_id, email, name, role, is_active, team_id, setting_id, created_at FROM users WHERE id=$1", user_id
        )
    return dict(row)


@router.delete("/orgs/{org_id}/users/{user_id}", status_code=200)
async def delete_org_user(org_id: str, user_id: str, current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    async with database.with_admin() as conn:
        u = await conn.fetchrow("SELECT name FROM users WHERE id = $1 AND org_id = $2", user_id, org_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        sched = await conn.execute("DELETE FROM schedules WHERE staff_user_id = $1", user_id)
        await conn.execute("DELETE FROM users WHERE id = $1", user_id)
    return {"message": f"User '{u['name']}' deleted"}


def _build_invite_email(name: str, org_name: str, invite_link: str) -> str:
    name = html.escape(name or "")
    org_name = html.escape(org_name or "")
    return f"""<!DOCTYPE html>
<html lang="en">
<body style="margin:0;padding:0;background:#F1F5F9;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="padding:40px 16px;">
  <tr><td align="center">
    <table width="520" cellpadding="0" cellspacing="0" style="background:white;border-radius:12px;overflow:hidden;box-shadow:0 4px 32px rgba(0,0,0,0.10);">
      <tr><td style="background:#1E3A8A;padding:32px 40px;">
        <p style="color:white;margin:0;font-size:24px;font-weight:700;">1two.one</p>
        <p style="color:rgba(255,255,255,0.60);margin:6px 0 0;font-size:13px;">Care Supervision Platform</p>
      </td></tr>
      <tr><td style="padding:40px 40px 32px;">
        <h2 style="color:#111827;font-size:20px;margin:0 0 20px;">You've been invited to join {org_name}</h2>
        <p style="color:#4B5563;font-size:15px;line-height:1.7;margin:0 0 10px;">Hi {name},</p>
        <p style="color:#4B5563;font-size:15px;line-height:1.7;margin:0 0 32px;">
          Your account has been created on <strong>1two.one</strong> as an
          <strong>Organisation Admin</strong> for <strong>{org_name}</strong>.
          Click below to set your password (expires in 72 hours).
        </p>
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr><td align="center" style="padding-bottom:32px;">
            <a href="{invite_link}" style="background:#1E3A8A;color:white;padding:14px 40px;text-decoration:none;border-radius:8px;font-weight:600;font-size:15px;display:inline-block;">
              Accept Invitation &rarr;
            </a>
          </td></tr>
        </table>
        <p style="color:#9CA3AF;font-size:13px;text-align:center;margin:0;">If you weren't expecting this, safely ignore this email.</p>
      </td></tr>
      <tr><td style="padding:20px 40px;border-top:1px solid #F3F4F6;background:#F9FAFB;">
        <p style="color:#9CA3AF;font-size:12px;margin:0;text-align:center;">&copy; 2025 1two.one</p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""


class InviteAdminRequest(BaseModel):
    email: EmailStr
    name: str


@router.post("/orgs/{org_id}/invite")
async def invite_org_admin(org_id: str, data: InviteAdminRequest, current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    now = datetime.now(timezone.utc).isoformat()
    user_id = str(uuid.uuid4())
    invite_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat()

    async with database.with_admin() as conn:
        org = await conn.fetchrow("SELECT name FROM organisations WHERE id = $1", org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organisation not found")
        existing = await conn.fetchrow("SELECT id FROM users WHERE email = $1", data.email.lower())
        if existing:
            raise HTTPException(status_code=400, detail="An account with this email already exists")

        from routers.auth import hash_password
        from utils import supabase_auth
        await conn.execute(
            """INSERT INTO users (id, email, password_hash, name, role, org_id, is_active, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
            user_id, data.email.lower(), await hash_password(secrets.token_urlsafe(32)),
            data.name.strip(), "admin", org_id, False, now,
        )
        await conn.execute(
            "INSERT INTO invitations (id, org_id, user_id, token, expires_at, created_at) VALUES ($1,$2,$3,$4,$5,$6)",
            invite_id, org_id, user_id, token, expires_at, now,
        )
        # No password set yet — real password is set in accept-invite below.
        try:
            await supabase_auth.create_user(user_id, data.email.lower())
            await conn.execute("UPDATE users SET supabase_migrated=TRUE WHERE id=$1", user_id)
        except Exception as exc:
            logger.error("Supabase Auth provisioning failed for invited admin %s: %s", data.email, exc)

    frontend_url = os.environ.get("FRONTEND_URL", "")
    invite_link = f"{frontend_url}/accept-invite?token={token}"

    try:
        import resend
        resend.api_key = os.environ.get("RESEND_API_KEY", "")
        html = _build_invite_email(data.name.strip(), org["name"], invite_link)
        await asyncio.to_thread(resend.Emails.send, {
            "from": os.environ.get("SENDER_EMAIL", "noreply@notify.1two.one"),
            "to": [data.email.lower()],
            "subject": f"You've been invited to join {org['name']} on 1two.one",
            "html": html,
        })
        logger.info(f"Invite email sent to {data.email}")
    except Exception as e:
        logger.warning(f"Invite email failed (user still created): {e}")
        return {
            "message": "User created but email failed to send — share the link below manually.",
            "invite_link": invite_link,
            "user_id": user_id,
            "email_failed": True,
        }

    return {"message": f"Invitation sent to {data.email}", "user_id": user_id}
