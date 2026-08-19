import json
import uuid
import logging
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from fastapi.responses import Response as _Response
from pydantic import BaseModel, EmailStr
from datetime import datetime, timezone
from typing import Optional
from deps import get_db, get_current_user, get_manager_scope
from utils.storage import put_object, get_object
import database

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Manager scope enforcement helpers ─────────────────────────────────────────

def _assert_setting_scope(scope: dict, setting_id: str) -> None:
    """Raise 403 if the manager's scope does not cover this setting."""
    if scope["level"] == "org":
        return
    if scope.get("setting_id") != setting_id:
        raise HTTPException(403, "Outside your management scope")


def _assert_team_scope(scope: dict, team_setting_id: str, team_id: str) -> None:
    """Raise 403 if the manager's scope does not cover this team."""
    if scope["level"] == "org":
        return
    if scope.get("setting_id") != team_setting_id:
        raise HTTPException(403, "Outside your management scope")
    if scope["level"] == "team" and scope.get("team_id") != team_id:
        raise HTTPException(403, "Outside your management scope")


def _jdict(raw) -> dict:
    """Safely parse a JSONB column that asyncpg may return as a string."""
    if not raw:
        return {}
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return dict(raw)


class SettingCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    manager_user_id: Optional[str] = None


class TeamCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    supervisor_user_id: Optional[str] = None


class OrgNameUpdate(BaseModel):
    name: str


class MemberAssign(BaseModel):
    user_id: str


class TeamAssignRequest(BaseModel):
    team_id: Optional[str] = None


class InviteUserRequest(BaseModel):
    name: str
    email: EmailStr
    role: str
    password: str


class BrandingUpdate(BaseModel):
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None


@router.patch("/name")
async def update_org_name(data: OrgNameUpdate, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    name = data.name.strip()
    if not name:
        raise HTTPException(400, "Name cannot be empty")
    org_id = current_user.get("org_id", "")
    async with database.with_admin() as conn:
        await conn.execute(
            "UPDATE organisations SET name=$1, updated_at=$2 WHERE id=$3",
            name, datetime.now(timezone.utc).isoformat(), org_id,
        )
    from utils.standards_cache import invalidate_org
    invalidate_org(org_id)
    return {"ok": True, "name": name}


@router.get("/structure")
async def get_structure(current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    scope = get_manager_scope(current_user)

    async with database.with_org(org_id) as conn:
        # Determine which settings to show
        if scope["level"] == "org":
            s_rows = await conn.fetch("SELECT * FROM org_settings ORDER BY name ASC")
        else:
            # Branch/team managers see only their own setting
            s_rows = await conn.fetch("SELECT * FROM org_settings WHERE id=$1", scope["setting_id"])

        settings = []
        for s_row in s_rows:
            s = dict(s_row)
            mgr_id = s.get("manager_user_id")
            if mgr_id:
                mgr = await conn.fetchrow("SELECT name FROM users WHERE id=$1", mgr_id)
                s["manager_name"] = mgr["name"] if mgr else None
            else:
                s["manager_name"] = None
            s["teams"] = []

            # Determine which teams to show within this setting
            if scope["level"] == "team":
                t_rows = await conn.fetch(
                    "SELECT * FROM teams WHERE setting_id=$1 AND id=$2 ORDER BY name ASC",
                    s["id"], scope["team_id"],
                )
            else:
                t_rows = await conn.fetch(
                    "SELECT * FROM teams WHERE setting_id=$1 ORDER BY name ASC", s["id"]
                )

            for t_row in t_rows:
                t = dict(t_row)
                sup_id = t.get("supervisor_user_id")
                if sup_id:
                    sup = await conn.fetchrow("SELECT name FROM users WHERE id=$1", sup_id)
                    t["supervisor_name"] = sup["name"] if sup else None
                else:
                    t["supervisor_name"] = None
                t["members"] = []
                m_rows = await conn.fetch(
                    "SELECT id, name, email, role FROM users WHERE team_id=$1 AND is_active=TRUE ORDER BY name ASC", t["id"]
                )
                t["members"] = [dict(m) for m in m_rows]
                s["teams"].append(t)
            settings.append(s)

        # Unassigned users — only relevant for org-level managers
        if scope["level"] == "org":
            unassigned_rows = await conn.fetch(
                "SELECT id, name, email, role FROM users WHERE org_id=$1 AND is_active=TRUE AND (team_id IS NULL OR team_id='') ORDER BY name ASC",
                org_id,
            )
            unassigned = [dict(r) for r in unassigned_rows]
        else:
            unassigned = []

    return {"settings": settings, "unassigned_users": unassigned}


@router.get("/settings")
async def list_settings(current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    scope = get_manager_scope(current_user)
    async with database.with_org(org_id) as conn:
        if scope["level"] == "org":
            rows = await conn.fetch("SELECT * FROM org_settings ORDER BY name ASC")
        else:
            rows = await conn.fetch("SELECT * FROM org_settings WHERE id=$1", scope["setting_id"])
    return [dict(r) for r in rows]


@router.post("/settings")
async def create_setting(data: SettingCreate, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    scope = get_manager_scope(current_user)
    if scope["level"] != "org":
        raise HTTPException(403, "Only org-level managers can create new branches")
    org_id = current_user.get("org_id", "")
    now = datetime.now(timezone.utc).isoformat()
    setting_id = str(uuid.uuid4())
    async with database.with_org(org_id) as conn:
        await conn.execute(
            "INSERT INTO org_settings (id, org_id, name, created_at, updated_at) VALUES ($1,$2,$3,$4,$4)",
            setting_id, org_id, data.name.strip(), now,
        )
        if data.manager_user_id:
            await conn.execute(
                "UPDATE users SET setting_id=$1 WHERE id=$2",
                setting_id, data.manager_user_id,
            )
    return {"id": setting_id, "org_id": org_id, "name": data.name.strip(), "created_at": now}


@router.put("/settings/{setting_id}")
async def update_setting(setting_id: str, data: SettingCreate, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    scope = get_manager_scope(current_user)
    _assert_setting_scope(scope, setting_id)
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        existing = await conn.fetchrow("SELECT * FROM org_settings WHERE id=$1", setting_id)
        if not existing:
            raise HTTPException(404, "Setting not found")
        old_mgr = existing.get("manager_user_id") if isinstance(existing, dict) else existing["manager_user_id"]
        if old_mgr and old_mgr != data.manager_user_id:
            await conn.execute("UPDATE users SET setting_id=NULL WHERE id=$1", old_mgr)
        await conn.execute(
            "UPDATE org_settings SET name=$1, updated_at=$2 WHERE id=$3",
            data.name.strip(), datetime.now(timezone.utc).isoformat(), setting_id,
        )
        if data.manager_user_id:
            await conn.execute("UPDATE users SET setting_id=$1 WHERE id=$2", setting_id, data.manager_user_id)
    return {"message": "Setting updated"}


@router.delete("/settings/{setting_id}")
async def delete_setting(setting_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        t_rows = await conn.fetch("SELECT id FROM teams WHERE setting_id=$1", setting_id)
        for t in t_rows:
            await conn.execute("UPDATE users SET team_id=NULL, setting_id=NULL WHERE team_id=$1", t["id"])
        await conn.execute("DELETE FROM teams WHERE setting_id=$1", setting_id)
        await conn.execute("UPDATE users SET setting_id=NULL WHERE setting_id=$1", setting_id)
        result = await conn.execute("DELETE FROM org_settings WHERE id=$1", setting_id)
    if result == "DELETE 0":
        raise HTTPException(404, "Setting not found")
    return {"message": "Setting deleted"}


@router.post("/settings/{setting_id}/teams")
async def create_team(setting_id: str, data: TeamCreate, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    scope = get_manager_scope(current_user)
    if scope["level"] == "team":
        raise HTTPException(403, "Team-scoped managers cannot create new teams")
    _assert_setting_scope(scope, setting_id)
    org_id = current_user.get("org_id", "")
    team_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    async with database.with_org(org_id) as conn:
        setting = await conn.fetchrow("SELECT id FROM org_settings WHERE id=$1", setting_id)
        if not setting:
            raise HTTPException(404, "Setting not found")
        await conn.execute(
            "INSERT INTO teams (id, org_id, setting_id, name, description, supervisor_user_id, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7)",
            team_id, org_id, setting_id, data.name.strip(), data.description or "", data.supervisor_user_id, now,
        )
        if data.supervisor_user_id:
            await conn.execute("UPDATE users SET team_id=$1, setting_id=$2 WHERE id=$3", team_id, setting_id, data.supervisor_user_id)
    return {"id": team_id, "org_id": org_id, "setting_id": setting_id, "name": data.name.strip(), "description": data.description or ""}


@router.put("/teams/{team_id}")
async def update_team(team_id: str, data: TeamCreate, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user.get("org_id", "")
    scope = get_manager_scope(current_user)
    async with database.with_org(org_id) as conn:
        existing = await conn.fetchrow("SELECT * FROM teams WHERE id=$1", team_id)
        if not existing:
            raise HTTPException(404, "Team not found")
        _assert_team_scope(scope, dict(existing).get("setting_id"), team_id)
        old_sup = dict(existing).get("supervisor_user_id")
        if old_sup and old_sup != data.supervisor_user_id:
            await conn.execute("UPDATE users SET team_id=NULL WHERE id=$1 AND team_id=$2", old_sup, team_id)
        await conn.execute("UPDATE teams SET name=$1, description=$2, supervisor_user_id=$3 WHERE id=$4", data.name.strip(), data.description or "", data.supervisor_user_id, team_id)
        if data.supervisor_user_id:
            setting_id = dict(existing).get("setting_id")
            await conn.execute("UPDATE users SET team_id=$1, setting_id=$2 WHERE id=$3", team_id, setting_id, data.supervisor_user_id)
    return {"message": "Team updated"}


@router.delete("/teams/{team_id}")
async def delete_team(team_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user.get("org_id", "")
    scope = get_manager_scope(current_user)
    async with database.with_org(org_id) as conn:
        if scope["level"] != "org":
            team_row = await conn.fetchrow("SELECT setting_id FROM teams WHERE id=$1", team_id)
            if not team_row:
                raise HTTPException(404, "Team not found")
            _assert_team_scope(scope, team_row["setting_id"], team_id)
        await conn.execute("UPDATE users SET team_id=NULL WHERE team_id=$1", team_id)
        result = await conn.execute("DELETE FROM teams WHERE id=$1", team_id)
    if result == "DELETE 0":
        raise HTTPException(404, "Team not found")
    return {"message": "Team deleted"}


@router.post("/teams/{team_id}/members")
async def add_member(team_id: str, data: MemberAssign, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user.get("org_id", "")
    scope = get_manager_scope(current_user)
    async with database.with_org(org_id) as conn:
        team = await conn.fetchrow("SELECT setting_id FROM teams WHERE id=$1", team_id)
        if not team:
            raise HTTPException(404, "Team not found")
        _assert_team_scope(scope, team["setting_id"], team_id)
        user = await conn.fetchrow("SELECT id FROM users WHERE id=$1 AND org_id=$2", data.user_id, org_id)
        if not user:
            raise HTTPException(404, "User not found")
        await conn.execute("UPDATE users SET team_id=$1, setting_id=$2 WHERE id=$3", team_id, team["setting_id"], data.user_id)
    return {"message": "Member added"}


@router.delete("/teams/{team_id}/members/{user_id}")
async def remove_member(team_id: str, user_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user.get("org_id", "")
    scope = get_manager_scope(current_user)
    async with database.with_org(org_id) as conn:
        if scope["level"] != "org":
            team_row = await conn.fetchrow("SELECT setting_id FROM teams WHERE id=$1", team_id)
            if team_row:
                _assert_team_scope(scope, team_row["setting_id"], team_id)
        await conn.execute("UPDATE users SET team_id=NULL, setting_id=NULL WHERE id=$1 AND team_id=$2", user_id, team_id)
    return {"message": "Member removed"}


@router.patch("/users/{user_id}/assign-team")
async def assign_user_to_team(user_id: str, data: TeamAssignRequest, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user.get("org_id", "")
    scope = get_manager_scope(current_user)
    async with database.with_org(org_id) as conn:
        user = await conn.fetchrow("SELECT id FROM users WHERE id=$1 AND org_id=$2", user_id, org_id)
        if not user:
            raise HTTPException(404, "User not found")
        if data.team_id:
            team = await conn.fetchrow("SELECT setting_id FROM teams WHERE id=$1", data.team_id)
            if not team:
                raise HTTPException(404, "Team not found")
            _assert_team_scope(scope, team["setting_id"], data.team_id)
            await conn.execute("UPDATE users SET team_id=$1, setting_id=$2 WHERE id=$3", data.team_id, team["setting_id"], user_id)
        else:
            # Unassign: verify the user being unassigned is within this manager's scope
            if scope["level"] != "org":
                target = await conn.fetchrow("SELECT setting_id FROM users WHERE id=$1", user_id)
                if target and target["setting_id"] and target["setting_id"] != scope.get("setting_id"):
                    raise HTTPException(403, "Outside your management scope")
            await conn.execute("UPDATE users SET team_id=NULL, setting_id=NULL WHERE id=$1", user_id)
    return {"ok": True}


@router.post("/invite-user")
async def invite_user_to_org(data: InviteUserRequest, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    from routers.auth import hash_password
    from utils.rate_limit import check_rate_limit
    allowed_roles = ["attendee", "manager", "shared_reviewer"]
    if current_user["role"] == "admin":
        allowed_roles.append("admin")
    role = data.role if data.role in allowed_roles else "attendee"
    user_id = str(uuid.uuid4())
    org_id = current_user.get("org_id", "")
    now = datetime.now(timezone.utc).isoformat()
    async with database.with_admin() as conn:
        # Rate limit: 20 invites per org / 60 min
        await check_rate_limit(
            conn,
            identifier=f"invite:{org_id}",
            max_attempts=20,
            window_minutes=60,
            error_detail="Invite limit reached. A maximum of 20 invites can be sent per hour.",
        )
        existing = await conn.fetchrow("SELECT id FROM users WHERE email=$1", data.email.lower())
        if existing:
            raise HTTPException(400, "Email already registered")
        await conn.execute(
            "INSERT INTO users (id, email, password_hash, name, role, org_id, is_active, must_change_password, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)",
            user_id, data.email.lower(), hash_password(data.password), data.name, role, org_id, True, True, now,
        )
    return {"id": user_id, "name": data.name, "email": data.email.lower(), "role": role}


@router.get("/branding")
async def get_branding(current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id")
    if not org_id:
        return {"has_logo": False, "primary_color": None}
    async with database.with_admin() as conn:
        org = await conn.fetchrow("SELECT branding FROM organisations WHERE id=$1", org_id)
    if not org:
        return {"has_logo": False, "primary_color": None}
    b = _jdict(org["branding"])
    return {"has_logo": bool(b.get("logo_path")), "primary_color": b.get("primary_color")}


@router.put("/branding")
async def update_branding(data: BrandingUpdate, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Admin or manager only")
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(400, "No organisation assigned")
    async with database.with_admin() as conn:
        org = await conn.fetchrow("SELECT branding FROM organisations WHERE id=$1", org_id)
        branding = _jdict(org["branding"]) if org else {}
        if data.primary_color is not None:
            branding["primary_color"] = data.primary_color
        if data.logo_url == "":
            branding["logo_path"] = None
        await conn.execute(
            "UPDATE organisations SET branding=$1::jsonb, updated_at=$2 WHERE id=$3",
            branding, datetime.now(timezone.utc).isoformat(), org_id,
        )
    return {"message": "Branding updated"}


@router.post("/branding/logo")
async def upload_logo(file: UploadFile = File(...), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Admin or manager only")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 2 MB)")
    # SVG excluded — SVG files can embed JavaScript and execute in the browser
    allowed_ext = {"png", "jpg", "jpeg", "webp"}
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "png"
    if ext not in allowed_ext:
        raise HTTPException(400, f"Unsupported type. Allowed: {', '.join(sorted(allowed_ext))}")
    # Validate magic bytes — reject extension-spoofed files
    from utils.file_security import validate_upload
    try:
        canonical_mime = validate_upload(data, ext)
    except ValueError as e:
        raise HTTPException(400, str(e))
    org_id = current_user.get("org_id") or "shared"
    path = f"branding/{org_id}/{uuid.uuid4()}.{ext}"
    try:
        put_object(path, data, canonical_mime)
    except Exception as e:
        logger.error(f"Logo upload failed: {e}")
        raise HTTPException(500, "Storage upload failed")
    async with database.with_admin() as conn:
        org_row = await conn.fetchrow("SELECT branding FROM organisations WHERE id=$1", org_id)
        branding = _jdict(org_row["branding"]) if org_row else {}
        branding["logo_path"] = path
        await conn.execute(
            "UPDATE organisations SET branding=$1::jsonb, updated_at=$2 WHERE id=$3",
            branding, datetime.now(timezone.utc).isoformat(), org_id,
        )
    return {"logo_path": path, "has_logo": True}


@router.get("/branding/logo/{org_id}")
async def get_org_logo(org_id: str):
    try:
        async with database.with_admin() as conn:
            org = await conn.fetchrow("SELECT branding FROM organisations WHERE id=$1", org_id)
        if not org:
            raise HTTPException(404, "Not found")
        path = _jdict(org["branding"]).get("logo_path")
        if not path:
            raise HTTPException(404, "No logo")
        content, content_type = get_object(path)
        return _Response(content=content, media_type=content_type, headers={"Cache-Control": "public, max-age=3600"})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Logo serve failed: {e}")
        raise HTTPException(404, "Logo not available")
