import asyncio
import json
import uuid
import secrets
import logging
import os
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from fastapi.responses import Response as _Response
from pydantic import BaseModel, EmailStr, field_validator
from datetime import datetime, timezone, timedelta
from typing import Optional, List
import re
from deps import get_db, get_current_user, get_manager_scope
from utils.storage import put_object, get_object
import database

router = APIRouter()
logger = logging.getLogger(__name__)

# Virtual setting id (never a real org_settings row) surfaced in the
# Meetings-page filter dropdown for teams with no setting assigned
# (setting_id IS NULL) — must match Meetings.js's UNASSIGNED_SETTING_ID.
UNASSIGNED_SETTING_ID = "unassigned"


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


async def _sync_user_team(conn, user_id: str, team_id: str | None) -> None:
    """Single source of truth for keeping a team member's users.setting_id in
    sync with users.team_id. setting_id is always DERIVED here from
    teams.setting_id for the given team_id (NULL when team_id is NULL) —
    never passed in as a separately-tracked value — so the two columns can
    no longer drift apart (root cause of the "orphaned teams" / stale
    setting_id symptom). Every write path in this file that changes a
    regular member's team assignment must go through this helper.
    NOTE: this is for team MEMBERSHIP only. A setting/team MANAGER's
    authority scope (org_settings.manager_user_id / teams.supervisor_user_id)
    is a separate concept, set directly elsewhere (create/update_setting) —
    intentionally not touched here."""
    setting_id = None
    if team_id:
        team = await conn.fetchrow("SELECT setting_id FROM teams WHERE id=$1", team_id)
        setting_id = team["setting_id"] if team else None
    await conn.execute(
        "UPDATE users SET team_id=$1, setting_id=$2 WHERE id=$3",
        team_id, setting_id, user_id,
    )


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


class BulkMoveRequest(BaseModel):
    to_team_id: Optional[str] = None


class InviteUserRequest(BaseModel):
    name: str
    email: EmailStr
    role: str


ROLE_LABELS = {
    "admin": "Admin",
    "manager": "Manager",
    "shared_reviewer": "Shared Reviewer",
    "attendee": "Staff / Supervisee",
}


_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class SpeakerColorsUpdate(BaseModel):
    manager: Optional[str] = None
    attendees: Optional[List[str]] = None

    @field_validator("manager")
    @classmethod
    def _validate_manager(cls, v):
        if v is not None and not _HEX_COLOR_RE.match(v):
            raise ValueError("manager colour must be a hex value like #93C5FD")
        return v

    @field_validator("attendees")
    @classmethod
    def _validate_attendees(cls, v):
        if v is not None:
            if len(v) != 4:
                raise ValueError("attendees must contain exactly 4 colours")
            for c in v:
                if not _HEX_COLOR_RE.match(c):
                    raise ValueError("each attendee colour must be a hex value like #FCA5A5")
        return v


class BrandingUpdate(BaseModel):
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    speaker_colors: Optional[SpeakerColorsUpdate] = None


@router.patch("/name")
async def update_org_name(data: OrgNameUpdate, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "super_admin"]:
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
            s_rows = await conn.fetch("SELECT id, name, manager_user_id FROM org_settings ORDER BY name ASC")
        else:
            # Branch/team managers see only their own setting
            s_rows = await conn.fetch(
                "SELECT id, name, manager_user_id FROM org_settings WHERE id=$1", scope["setting_id"]
            )
        s_dicts = [dict(r) for r in s_rows]
        setting_ids = [s["id"] for s in s_dicts]

        # Determine which teams to show, in a single batched query (avoids N+1 per setting)
        if scope["level"] == "team":
            t_rows = await conn.fetch(
                "SELECT id, name, description, supervisor_user_id, setting_id FROM teams "
                "WHERE setting_id = ANY($1::uuid[]) AND id=$2 ORDER BY name ASC",
                setting_ids, scope["team_id"],
            )
        else:
            t_rows = await conn.fetch(
                "SELECT id, name, description, supervisor_user_id, setting_id FROM teams "
                "WHERE setting_id = ANY($1::uuid[]) ORDER BY name ASC", setting_ids,
            )
        t_dicts = [dict(r) for r in t_rows]
        team_ids = [t["id"] for t in t_dicts]

        # Batch-resolve setting-manager + team-supervisor display names in one query
        mgr_ids = {s["manager_user_id"] for s in s_dicts if s.get("manager_user_id")}
        sup_ids = {t["supervisor_user_id"] for t in t_dicts if t.get("supervisor_user_id")}
        name_ids = list(mgr_ids | sup_ids)
        names_by_id = {}
        if name_ids:
            n_rows = await conn.fetch("SELECT id, name FROM users WHERE id = ANY($1::uuid[])", name_ids)
            names_by_id = {r["id"]: r["name"] for r in n_rows}

        # Batch-load all team members in one query instead of one per team
        members_by_team = {tid: [] for tid in team_ids}
        if team_ids:
            m_rows = await conn.fetch(
                "SELECT id, name, email, role, team_id FROM users WHERE team_id = ANY($1::uuid[]) AND is_active=TRUE ORDER BY name ASC",
                team_ids,
            )
            for m in m_rows:
                members_by_team[m["team_id"]].append({"id": m["id"], "name": m["name"], "email": m["email"], "role": m["role"]})

        teams_by_setting = {sid: [] for sid in setting_ids}
        for t in t_dicts:
            sup_id = t.get("supervisor_user_id")
            t["supervisor_name"] = names_by_id.get(sup_id) if sup_id else None
            t["members"] = members_by_team.get(t["id"], [])
            teams_by_setting.setdefault(t["setting_id"], []).append(t)

        settings = []
        for s in s_dicts:
            mgr_id = s.get("manager_user_id")
            s["manager_name"] = names_by_id.get(mgr_id) if mgr_id else None
            s["teams"] = teams_by_setting.get(s["id"], [])
            settings.append(s)

        # Unassigned users — only relevant for org-level managers. Excludes
        # admins (always org-level, never "unassigned") and ALL managers —
        # a manager with team_id IS NULL always has a home: either a whole
        # setting (setting_id set) or the whole org ("Promote to Org-Wide
        # Manager" clears both). Only non-manager staff with no team are
        # genuinely orphaned.
        if scope["level"] == "org":
            unassigned_rows = await conn.fetch(
                """SELECT id, name, email, role FROM users
                   WHERE org_id=$1 AND is_active=TRUE AND team_id IS NULL
                     AND role NOT IN ('admin', 'manager')
                   ORDER BY name ASC""",
                org_id,
            )
            unassigned = [dict(r) for r in unassigned_rows]
        else:
            unassigned = []

        # Org-level users — Admins (always) plus any manager with team_id IS
        # NULL (org-wide via "Promote to Org-Wide Manager", or scoped to a
        # whole Setting instead of one team). None of these ever show up in
        # a team's member list, so without this the Structure tree would
        # have no way to view/manage them at all. Only computed for org-level
        # viewers, same restriction as unassigned_users above.
        if scope["level"] == "org":
            org_level_rows = await conn.fetch(
                """SELECT id, name, email, role, setting_id FROM users
                   WHERE org_id=$1 AND is_active=TRUE
                     AND (role='admin' OR (role='manager' AND team_id IS NULL))
                   ORDER BY (role != 'admin'), name ASC""",
                org_id,
            )
            setting_name_by_id = {s["id"]: s["name"] for s in s_dicts}
            org_level_users = [
                {"id": r["id"], "name": r["name"], "email": r["email"], "role": r["role"],
                 "setting_name": setting_name_by_id.get(r["setting_id"]) if r["setting_id"] else None}
                for r in org_level_rows
            ]
        else:
            org_level_users = []

    return {"settings": settings, "unassigned_users": unassigned, "org_level_users": org_level_users}


async def get_structure_lite_data(current_user: dict, reused_conn=None) -> dict:
    """Shared logic behind GET /org/structure-lite — extracted so the
    combined GET /meetings/page-data endpoint can call it directly, reusing
    the SAME already-open connection instead of opening a separate block.
    reused_conn: optional already-open with_org() connection for this exact
    org_id (see get_current_user_conn's docstring)."""
    role = current_user["role"]
    if role not in ("admin", "manager"):
        return {"settings": [], "unassigned_users": []}
    org_id = current_user.get("org_id", "")
    if not org_id:
        return {"settings": [], "unassigned_users": []}
    scope = get_manager_scope(current_user)

    async def _run(conn):
        if scope["level"] == "org":
            s_rows = await conn.fetch("SELECT id, name FROM org_settings ORDER BY name ASC")
        else:
            s_rows = await conn.fetch(
                "SELECT id, name FROM org_settings WHERE id=$1", scope["setting_id"]
            )
        s_dicts = [dict(r) for r in s_rows]
        setting_ids = [s["id"] for s in s_dicts]

        # Batched: one teams query for all settings instead of one per setting.
        if scope["level"] == "team":
            t_rows = await conn.fetch(
                "SELECT id, name, setting_id FROM teams WHERE setting_id = ANY($1::uuid[]) AND id=$2 ORDER BY name ASC",
                setting_ids, scope["team_id"],
            )
        else:
            t_rows = await conn.fetch(
                "SELECT id, name, setting_id FROM teams WHERE setting_id = ANY($1::uuid[]) ORDER BY name ASC",
                setting_ids,
            )
        teams_by_setting = {sid: [] for sid in setting_ids}
        for t in t_rows:
            teams_by_setting.setdefault(t["setting_id"], []).append({"id": t["id"], "name": t["name"]})

        settings = []
        for s in s_dicts:
            s["teams"] = teams_by_setting.get(s["id"], [])
            settings.append(s)

        # Orphan teams (setting_id IS NULL) were previously invisible in this
        # dropdown entirely — surface them as a virtual "Unassigned" setting so
        # they're still filterable. Org-level scope only: a setting/team-scoped
        # manager can never own a team with no setting.
        if scope["level"] == "org":
            orphan_rows = await conn.fetch(
                "SELECT id, name FROM teams WHERE org_id=$1 AND setting_id IS NULL ORDER BY name ASC",
                org_id,
            )
            if orphan_rows:
                settings.append({
                    "id": UNASSIGNED_SETTING_ID,
                    "name": "Unassigned (no setting)",
                    "teams": [{"id": t["id"], "name": t["name"]} for t in orphan_rows],
                })
        return settings

    if reused_conn is not None:
        settings = await _run(reused_conn)
    else:
        async with database.with_org(org_id) as conn:
            settings = await _run(conn)
    return {"settings": settings, "unassigned_users": []}


@router.get("/structure-lite")
async def get_structure_lite(current_user=Depends(get_current_user)):
    """Lightweight settings+teams list (id/name only, no member detail) —
    used by pages that only need it to populate a filter dropdown (e.g. the
    Meetings page's Setting/Team filter). Logic moved here unchanged from
    dashboard.py's fetch_structure(), which is now dead code: nothing calls
    GET /dashboard/ any more, so its heavier due-schedules/action-stats
    computation never has to run just to serve this small dropdown list.
    Admin/manager only — every other role gets an empty settings list, same
    as before, so the Meetings page's filter bar stays hidden for them."""
    return await get_structure_lite_data(current_user)


@router.get("/settings")
async def list_settings(current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    scope = get_manager_scope(current_user)
    async with database.with_org(org_id) as conn:
        if scope["level"] == "org":
            rows = await conn.fetch("SELECT id, name, manager_user_id FROM org_settings ORDER BY name ASC")
        else:
            rows = await conn.fetch(
                "SELECT id, name, manager_user_id FROM org_settings WHERE id=$1", scope["setting_id"]
            )
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
    mgr_id = data.manager_user_id or None
    async with database.with_org(org_id) as conn:
        await conn.execute(
            "INSERT INTO org_settings (id, org_id, name, manager_user_id, created_at, updated_at) VALUES ($1,$2,$3,$4,$5,$5)",
            setting_id, org_id, data.name.strip(), mgr_id, now,
        )
        if mgr_id:
            await conn.execute(
                "UPDATE users SET setting_id=$1 WHERE id=$2",
                setting_id, mgr_id,
            )
    return {"id": setting_id, "org_id": org_id, "name": data.name.strip(), "created_at": now}


@router.put("/settings/{setting_id}")
async def update_setting(setting_id: str, data: SettingCreate, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    scope = get_manager_scope(current_user)
    _assert_setting_scope(scope, setting_id)
    org_id = current_user.get("org_id", "")
    mgr_id = data.manager_user_id or None
    async with database.with_org(org_id) as conn:
        existing = await conn.fetchrow("SELECT manager_user_id FROM org_settings WHERE id=$1", setting_id)
        if not existing:
            raise HTTPException(404, "Setting not found")
        old_mgr = existing["manager_user_id"]
        if old_mgr and old_mgr != mgr_id:
            await conn.execute("UPDATE users SET setting_id=NULL WHERE id=$1", old_mgr)
        await conn.execute(
            "UPDATE org_settings SET name=$1, manager_user_id=$2, updated_at=$3 WHERE id=$4",
            data.name.strip(), mgr_id, datetime.now(timezone.utc).isoformat(), setting_id,
        )
        if mgr_id:
            await conn.execute("UPDATE users SET setting_id=$1 WHERE id=$2", setting_id, mgr_id)
    return {"message": "Setting updated"}



@router.delete("/settings/{setting_id}")
async def delete_setting(setting_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        setting = await conn.fetchrow("SELECT id FROM org_settings WHERE id=$1", setting_id)
        if not setting:
            raise HTTPException(404, "Setting not found")
        # Deletion is only allowed on a genuinely empty container — no admin
        # or manager can delete a setting out from under its teams/staff.
        # Staff/teams must be moved to their new home first; only then does
        # this become "just deleting an empty container".
        team_count = await conn.fetchval("SELECT COUNT(*) FROM teams WHERE setting_id=$1", setting_id)
        staff_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE setting_id=$1 AND is_active=TRUE", setting_id)
        if team_count or staff_count:
            raise HTTPException(
                400,
                f"Can't delete — this setting still has {team_count} team(s) and {staff_count} staff assigned. Move them to their new home first.",
            )
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
    sup_id = data.supervisor_user_id or None
    async with database.with_org(org_id) as conn:
        setting = await conn.fetchrow("SELECT id FROM org_settings WHERE id=$1", setting_id)
        if not setting:
            raise HTTPException(404, "Setting not found")
        await conn.execute(
            "INSERT INTO teams (id, org_id, setting_id, name, description, supervisor_user_id, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7)",
            team_id, org_id, setting_id, data.name.strip(), data.description or "", sup_id, now,
        )
        if sup_id:
            await _sync_user_team(conn, sup_id, team_id)
    return {"id": team_id, "org_id": org_id, "setting_id": setting_id, "name": data.name.strip(), "description": data.description or ""}


@router.put("/teams/{team_id}")
async def update_team(team_id: str, data: TeamCreate, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user.get("org_id", "")
    scope = get_manager_scope(current_user)
    sup_id = data.supervisor_user_id or None
    async with database.with_org(org_id) as conn:
        existing = await conn.fetchrow("SELECT setting_id, supervisor_user_id FROM teams WHERE id=$1", team_id)
        if not existing:
            raise HTTPException(404, "Team not found")
        _assert_team_scope(scope, dict(existing).get("setting_id"), team_id)
        old_sup = dict(existing).get("supervisor_user_id")
        if old_sup and old_sup != sup_id:
            # BUGFIX: previously only cleared team_id, leaving setting_id stale
            # (pointing at a team the old supervisor no longer belongs to) —
            # this was one of the two real drift sources behind the "orphaned
            # teams" symptom. Guard old_sup's own team_id to avoid clobbering
            # them if they were reassigned elsewhere in the meantime.
            row = await conn.fetchrow("SELECT team_id FROM users WHERE id=$1", old_sup)
            if row and row["team_id"] == team_id:
                await _sync_user_team(conn, old_sup, None)
        await conn.execute("UPDATE teams SET name=$1, description=$2, supervisor_user_id=$3 WHERE id=$4", data.name.strip(), data.description or "", sup_id, team_id)
        if sup_id:
            await _sync_user_team(conn, sup_id, team_id)
    return {"message": "Team updated"}


@router.delete("/teams/{team_id}")
async def delete_team(team_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user.get("org_id", "")
    scope = get_manager_scope(current_user)
    async with database.with_org(org_id) as conn:
        team_row = await conn.fetchrow("SELECT setting_id FROM teams WHERE id=$1", team_id)
        if not team_row:
            raise HTTPException(404, "Team not found")
        if scope["level"] != "org":
            _assert_team_scope(scope, team_row["setting_id"], team_id)
        # Deletion is only allowed on a genuinely empty container — no admin
        # or manager can delete a team out from under its members; they must
        # be moved to their new team/setting first.
        member_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE team_id=$1 AND is_active=TRUE", team_id)
        if member_count:
            raise HTTPException(400, f"Can't delete — this team still has {member_count} staff assigned. Move them to their new team first.")
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
        await _sync_user_team(conn, data.user_id, team_id)
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
        user = await conn.fetchrow("SELECT id, role FROM users WHERE id=$1 AND org_id=$2", user_id, org_id)
        if not user:
            raise HTTPException(404, "User not found")
        if user["role"] == "admin":
            raise HTTPException(400, "Admins stay at the top Organisation level and can't be assigned to a team")
        if data.team_id:
            team = await conn.fetchrow("SELECT setting_id FROM teams WHERE id=$1", data.team_id)
            if not team:
                raise HTTPException(404, "Team not found")
            _assert_team_scope(scope, team["setting_id"], data.team_id)
            await _sync_user_team(conn, user_id, data.team_id)
        else:
            # Unassign: verify the user being unassigned is within this manager's scope
            if scope["level"] != "org":
                target = await conn.fetchrow("SELECT setting_id FROM users WHERE id=$1", user_id)
                if target and target["setting_id"] and target["setting_id"] != scope.get("setting_id"):
                    raise HTTPException(403, "Outside your management scope")
            await _sync_user_team(conn, user_id, None)
    return {"ok": True}


@router.patch("/teams/{team_id}/bulk-move")
async def bulk_move_team_members(team_id: str, data: BulkMoveRequest, current_user=Depends(get_current_user)):
    """Move every current member of `team_id` to `to_team_id` (or unassign
    all, if null) in one shot — the bulk counterpart of assign-team, so an
    admin/manager doesn't have to move a whole team's staff one by one before
    the now-empty team/setting can be deleted."""
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    if data.to_team_id == team_id:
        raise HTTPException(400, "Destination team must be different from the source team")
    org_id = current_user.get("org_id", "")
    scope = get_manager_scope(current_user)
    async with database.with_org(org_id) as conn:
        from_team = await conn.fetchrow("SELECT setting_id FROM teams WHERE id=$1", team_id)
        if not from_team:
            raise HTTPException(404, "Team not found")
        _assert_team_scope(scope, from_team["setting_id"], team_id)
        to_setting_id = None
        if data.to_team_id:
            to_team = await conn.fetchrow("SELECT setting_id FROM teams WHERE id=$1", data.to_team_id)
            if not to_team:
                raise HTTPException(404, "Destination team not found")
            _assert_team_scope(scope, to_team["setting_id"], data.to_team_id)
            to_setting_id = to_team["setting_id"]
        result = await conn.execute(
            "UPDATE users SET team_id=$1, setting_id=$2 WHERE team_id=$3",
            data.to_team_id, to_setting_id, team_id,
        )
    moved = int(result.split()[-1]) if result else 0
    return {"moved": moved}


@router.post("/invite-user")
async def invite_user_to_org(data: InviteUserRequest, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    from utils.rate_limit import check_rate_limit
    from utils.org_provisioning import invite_user_core, send_invite_email
    allowed_roles = ["attendee", "manager", "shared_reviewer"]
    if current_user["role"] == "admin":
        allowed_roles.append("admin")
    role = data.role if data.role in allowed_roles else "attendee"
    org_id = current_user.get("org_id", "")
    async with database.with_admin() as conn:
        # Rate limit: 20 invites per org / 60 min
        await check_rate_limit(
            conn,
            identifier=f"invite:{org_id}",
            max_attempts=20,
            window_minutes=60,
            error_detail="Invite limit reached. A maximum of 20 invites can be sent per hour.",
        )
        org = await conn.fetchrow("SELECT name FROM organisations WHERE id=$1", org_id)
        try:
            result = await invite_user_core(conn, org_id=org_id, org_name=org["name"], email=data.email, name=data.name, role=role)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    email_sent = await send_invite_email(data.email, data.name.strip(), org["name"], result["invite_link"], role_label=ROLE_LABELS.get(role, "Staff"))
    if not email_sent:
        return {
            "id": result["user_id"], "name": data.name, "email": data.email.lower(), "role": role,
            "message": "User created but the invite email failed to send — share the link below manually.",
            "invite_link": result["invite_link"], "email_failed": True,
        }
    return {"id": result["user_id"], "name": data.name, "email": data.email.lower(), "role": role, "message": f"Invite sent to {data.email}"}


@router.post("/invite-user/{user_id}/resend")
async def resend_invite(user_id: str, current_user=Depends(get_current_user)):
    """Regenerates a fresh 72h invite token/link and re-sends the email.
    Only valid for a still-pending (must_change_password=TRUE) user."""
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    from utils.rate_limit import check_rate_limit
    from utils.org_provisioning import send_invite_email
    org_id = current_user.get("org_id", "")
    async with database.with_admin() as conn:
        await check_rate_limit(
            conn,
            identifier=f"invite:{org_id}",
            max_attempts=20,
            window_minutes=60,
            error_detail="Invite limit reached. A maximum of 20 invites can be sent per hour.",
        )
        user = await conn.fetchrow(
            "SELECT id, name, email, role, must_change_password FROM users WHERE id=$1 AND org_id=$2", user_id, org_id,
        )
        if not user:
            raise HTTPException(404, "User not found")
        if not user["must_change_password"]:
            raise HTTPException(400, "This invite has already been accepted")
        org = await conn.fetchrow("SELECT name FROM organisations WHERE id=$1", org_id)
        now = datetime.now(timezone.utc).isoformat()
        token = secrets.token_urlsafe(32)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat()
        # Invalidate any still-open previous invite, then issue a fresh one
        await conn.execute("UPDATE invitations SET used_at=$1 WHERE user_id=$2 AND used_at IS NULL", now, user_id)
        await conn.execute(
            "INSERT INTO invitations (id, org_id, user_id, token, expires_at, created_at) VALUES ($1,$2,$3,$4,$5,$6)",
            str(uuid.uuid4()), org_id, user_id, token, expires_at, now,
        )

    frontend_url = os.environ.get("FRONTEND_URL", "")
    invite_link = f"{frontend_url}/accept-invite?token={token}"
    email_sent = await send_invite_email(user["email"], user["name"], org["name"], invite_link, role_label=ROLE_LABELS.get(user["role"], "Staff"))
    if not email_sent:
        return {"message": "Invite regenerated but the email failed to send — share the link below manually.", "invite_link": invite_link, "email_failed": True}
    return {"message": f"Invite re-sent to {user['email']}"}


@router.get("/branding")
async def get_branding(current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id")
    if not org_id:
        return {"has_logo": False, "primary_color": None, "speaker_colors": {}}
    async with database.with_admin() as conn:
        org = await conn.fetchrow("SELECT branding FROM organisations WHERE id=$1", org_id)
    if not org:
        return {"has_logo": False, "primary_color": None, "speaker_colors": {}}
    b = _jdict(org["branding"])
    return {
        "has_logo": bool(b.get("logo_path")),
        "primary_color": b.get("primary_color"),
        "speaker_colors": b.get("speaker_colors") or {},
    }


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
        if data.speaker_colors is not None:
            branding["speaker_colors"] = {
                "manager": data.speaker_colors.manager,
                "attendees": data.speaker_colors.attendees,
            }
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
        # PERF-001: same asyncio.to_thread pattern as bcrypt/PDF-generation/email —
        # put_object() uses the synchronous `requests` library, which would
        # otherwise block the single event loop for the full upload round-trip.
        await asyncio.to_thread(put_object, path, data, canonical_mime)
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
        content, content_type = await asyncio.to_thread(get_object, path)
        return _Response(content=content, media_type=content_type, headers={"Cache-Control": "public, max-age=3600"})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Logo serve failed: {e}")
        raise HTTPException(404, "Logo not available")


# ── HR Webhook Integration (MVP) ─────────────────────────────────────────────
# Pushes summary/achievements/actions/learning_needs to an org-configured URL
# on meeting sign-off. Admin-only: this configures where org data is shared
# externally, a bigger-than-usual privilege even by this app's admin-only bar.

class WebhookConfigUpdate(BaseModel):
    url: str
    enabled: bool


def _mask_secret(secret: str) -> str:
    if not secret or len(secret) < 8:
        return ""
    return f"whsec_{'•' * 8}{secret[-4:]}"


@router.get("/webhook")
async def get_webhook_config(current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    org_id = current_user.get("org_id")
    async with database.with_org(org_id) as conn:
        cfg = await conn.fetchrow("SELECT url, secret, enabled, updated_at FROM webhook_configs WHERE org_id=$1", org_id)
    if not cfg:
        return {"url": "", "enabled": False, "secret_masked": "", "configured": False}
    return {
        "url": cfg["url"], "enabled": cfg["enabled"],
        "secret_masked": _mask_secret(cfg["secret"]),
        "configured": bool(cfg["url"]),
        "updated_at": cfg["updated_at"],
    }


@router.put("/webhook")
async def update_webhook_config(data: WebhookConfigUpdate, current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    if data.enabled and not data.url:
        raise HTTPException(400, "A URL is required to enable the webhook")
    if data.url and not (data.url.startswith("https://") or data.url.startswith("http://")):
        raise HTTPException(400, "URL must start with http:// or https://")
    org_id = current_user.get("org_id")
    now = datetime.now(timezone.utc)
    async with database.with_org(org_id) as conn:
        existing = await conn.fetchrow("SELECT id, secret FROM webhook_configs WHERE org_id=$1", org_id)
        if existing:
            await conn.execute(
                "UPDATE webhook_configs SET url=$1, enabled=$2, updated_at=$3 WHERE org_id=$4",
                data.url, data.enabled, now, org_id,
            )
        else:
            secret = f"whsec_{uuid.uuid4().hex}{uuid.uuid4().hex}"
            await conn.execute(
                """INSERT INTO webhook_configs (org_id, url, secret, enabled, created_by_id, created_by_name, updated_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)""",
                org_id, data.url, secret, data.enabled, current_user["id"], current_user.get("name", ""), now,
            )
    return {"message": "Webhook settings saved"}


@router.post("/webhook/regenerate-secret")
async def regenerate_webhook_secret(current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    org_id = current_user.get("org_id")
    new_secret = f"whsec_{uuid.uuid4().hex}{uuid.uuid4().hex}"
    async with database.with_org(org_id) as conn:
        result = await conn.execute(
            "UPDATE webhook_configs SET secret=$1, updated_at=$2 WHERE org_id=$3",
            new_secret, datetime.now(timezone.utc), org_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(404, "No webhook configured yet — save a URL first")
    return {"secret_masked": _mask_secret(new_secret)}


@router.post("/webhook/test")
async def test_webhook(current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    org_id = current_user.get("org_id")
    async with database.with_org(org_id) as conn:
        cfg = await conn.fetchrow("SELECT url, secret FROM webhook_configs WHERE org_id=$1", org_id)
    if not cfg or not cfg["url"]:
        raise HTTPException(400, "Save a webhook URL first")
    from utils.webhooks import _send_and_log
    test_payload = {
        "event": "webhook.test", "meeting_id": None, "meeting_title": "Test ping",
        "meeting_date": datetime.now(timezone.utc).date().isoformat(),
        "signed_off_at": datetime.now(timezone.utc).isoformat(),
        "staff": [{"name": "Test Staff Member", "email": "test@example.com"}],
        "summary": "This is a test ping from 1two.one to verify your webhook endpoint is reachable.",
        "achievements": ["Sample achievement"], "actions": [], "learning_needs": ["Sample learning need"],
    }
    await _send_and_log(org_id, None, cfg["url"], cfg["secret"], test_payload)
    async with database.with_org(org_id) as conn:
        latest = await conn.fetchrow(
            "SELECT success, http_status, error_message FROM webhook_deliveries WHERE org_id=$1 ORDER BY attempted_at DESC LIMIT 1",
            org_id,
        )
    return dict(latest) if latest else {"success": False, "error_message": "No response logged"}


@router.get("/webhook/deliveries")
async def list_webhook_deliveries(current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    org_id = current_user.get("org_id")
    async with database.with_org(org_id) as conn:
        rows = await conn.fetch(
            """SELECT id, meeting_id, event, success, http_status, error_message, attempted_at
               FROM webhook_deliveries WHERE org_id=$1 ORDER BY attempted_at DESC LIMIT 50""",
            org_id,
        )
    return [
        {
            "id": r["id"], "meeting_id": r["meeting_id"], "event": r["event"],
            "success": r["success"], "http_status": r["http_status"], "error_message": r["error_message"],
            "attempted_at": r["attempted_at"],
        }
        for r in rows
    ]


@router.post("/webhook/deliveries/{delivery_id}/resend")
async def resend_webhook_delivery(delivery_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    org_id = current_user.get("org_id")
    from utils.webhooks import resend_delivery
    await resend_delivery(delivery_id, org_id)
    async with database.with_org(org_id) as conn:
        latest = await conn.fetchrow(
            "SELECT success, http_status, error_message FROM webhook_deliveries WHERE org_id=$1 ORDER BY attempted_at DESC LIMIT 1",
            org_id,
        )
    return dict(latest) if latest else {"success": False, "error_message": "No response logged"}
