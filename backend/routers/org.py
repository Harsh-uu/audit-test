from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from fastapi.responses import Response as _Response
from pydantic import BaseModel
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional
import uuid
import logging
from deps import get_db, get_current_user
from utils.storage import put_object, get_object

logger = logging.getLogger(__name__)

router = APIRouter()


def _to(doc):
    if doc is None:
        return None
    doc = dict(doc)
    doc["id"] = str(doc["_id"])
    del doc["_id"]
    for key in ("manager_user_id", "supervisor_user_id", "setting_id"):
        if key in doc and doc[key]:
            doc[key] = str(doc[key])
    return doc


class SettingCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    manager_user_id: Optional[str] = None


class TeamCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    supervisor_user_id: Optional[str] = None


class MemberAssign(BaseModel):
    user_id: str


@router.get("/structure")
async def get_structure(db=Depends(get_db), current_user=Depends(get_current_user)):
    """Full nested org structure for the UI."""
    org_id = current_user.get("org_id")
    org_filter = {"org_id": org_id} if org_id else {}

    settings = []
    async for s in db.org_settings.find(org_filter).sort("name", 1):
        sd = _to(s)
        if sd.get("manager_user_id"):
            mgr = await db.users.find_one({"_id": ObjectId(sd["manager_user_id"])})
            sd["manager_name"] = mgr["name"] if mgr else None
        else:
            sd["manager_name"] = None
        sd["teams"] = []

        async for t in db.teams.find({"setting_id": sd["id"]}).sort("name", 1):
            td = _to(t)
            if td.get("supervisor_user_id"):
                sup = await db.users.find_one({"_id": ObjectId(td["supervisor_user_id"])})
                td["supervisor_name"] = sup["name"] if sup else None
            else:
                td["supervisor_name"] = None
            td["members"] = []
            async for u in db.users.find({"team_id": td["id"]}).sort("name", 1):
                td["members"].append({
                    "id": str(u["_id"]),
                    "name": u["name"],
                    "email": u["email"],
                    "role": u["role"],
                })
            sd["teams"].append(td)

        settings.append(sd)

    unassigned_query = {
        **org_filter,
        "$and": [
            {"is_active": {"$ne": False}},
            {"$or": [{"team_id": {"$exists": False}}, {"team_id": None}]},
        ]
    }
    unassigned = []
    async for u in db.users.find(unassigned_query).sort("name", 1):
        unassigned.append({
            "id": str(u["_id"]),
            "name": u["name"],
            "email": u["email"],
            "role": u["role"],
        })

    return {"settings": settings, "unassigned_users": unassigned}


@router.get("/settings")
async def list_settings(db=Depends(get_db), current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id")
    org_filter = {"org_id": org_id} if org_id else {}
    result = []
    async for s in db.org_settings.find(org_filter).sort("name", 1):
        result.append(_to(s))
    return result


@router.post("/settings")
async def create_setting(data: SettingCreate, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "name": data.name,
        "description": data.description or "",
        "manager_user_id": data.manager_user_id or None,
        "org_id": current_user.get("org_id"),
        "created_at": now,
        "updated_at": now,
    }
    result = await db.org_settings.insert_one(doc)
    # Update manager's setting_id and org_scope
    if data.manager_user_id:
        await db.users.update_one(
            {"_id": ObjectId(data.manager_user_id)},
            {"$set": {"setting_id": str(result.inserted_id), "org_scope": "setting"}}
        )
    doc["id"] = str(result.inserted_id)
    del doc["_id"]
    return doc


@router.put("/settings/{setting_id}")
async def update_setting(setting_id: str, data: SettingCreate, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    existing = await db.org_settings.find_one({"_id": ObjectId(setting_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Setting not found")
    # Remove org_scope from old manager if changed
    old_mgr = existing.get("manager_user_id")
    if old_mgr and str(old_mgr) != data.manager_user_id:
        await db.users.update_one({"_id": ObjectId(str(old_mgr))}, {"$unset": {"setting_id": "", "org_scope": ""}})
    update = {"name": data.name, "description": data.description or "", "manager_user_id": data.manager_user_id or None, "updated_at": datetime.now(timezone.utc).isoformat()}
    await db.org_settings.update_one({"_id": ObjectId(setting_id)}, {"$set": update})
    if data.manager_user_id:
        await db.users.update_one(
            {"_id": ObjectId(data.manager_user_id)},
            {"$set": {"setting_id": setting_id, "org_scope": "setting"}}
        )
    return {"message": "Setting updated"}


@router.delete("/settings/{setting_id}")
async def delete_setting(setting_id: str, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    # Remove team memberships
    team_ids = [str(t["_id"]) async for t in db.teams.find({"setting_id": setting_id})]
    for tid in team_ids:
        await db.users.update_many({"team_id": tid}, {"$unset": {"team_id": "", "setting_id": "", "org_scope": ""}})
    await db.teams.delete_many({"setting_id": setting_id})
    await db.users.update_many({"setting_id": setting_id}, {"$unset": {"setting_id": "", "org_scope": ""}})
    result = await db.org_settings.delete_one({"_id": ObjectId(setting_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Setting not found")
    return {"message": "Setting deleted"}


@router.post("/settings/{setting_id}/teams")
async def create_team(setting_id: str, data: TeamCreate, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if not await db.org_settings.find_one({"_id": ObjectId(setting_id)}):
        raise HTTPException(status_code=404, detail="Setting not found")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "name": data.name,
        "description": data.description or "",
        "setting_id": setting_id,
        "supervisor_user_id": data.supervisor_user_id or None,
        "org_id": current_user.get("org_id"),
        "created_at": now,
        "updated_at": now,
    }
    result = await db.teams.insert_one(doc)
    team_id = str(result.inserted_id)
    doc["id"] = team_id
    del doc["_id"]
    if data.supervisor_user_id:
        await db.users.update_one(
            {"_id": ObjectId(data.supervisor_user_id)},
            {"$set": {"team_id": team_id, "setting_id": setting_id, "org_scope": "team"}}
        )
    return doc


@router.put("/teams/{team_id}")
async def update_team(team_id: str, data: TeamCreate, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    existing = await db.teams.find_one({"_id": ObjectId(team_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Team not found")
    old_sup = existing.get("supervisor_user_id")
    if old_sup and str(old_sup) != data.supervisor_user_id:
        await db.users.update_one({"_id": ObjectId(str(old_sup))}, {"$unset": {"org_scope": ""}})
    update = {"name": data.name, "description": data.description or "", "supervisor_user_id": data.supervisor_user_id or None, "updated_at": datetime.now(timezone.utc).isoformat()}
    await db.teams.update_one({"_id": ObjectId(team_id)}, {"$set": update})
    if data.supervisor_user_id:
        await db.users.update_one(
            {"_id": ObjectId(data.supervisor_user_id)},
            {"$set": {"team_id": team_id, "setting_id": existing.get("setting_id"), "org_scope": "team"}}
        )
    return {"message": "Team updated"}


@router.delete("/teams/{team_id}")
async def delete_team(team_id: str, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    await db.users.update_many({"team_id": team_id}, {"$unset": {"team_id": "", "org_scope": ""}})
    result = await db.teams.delete_one({"_id": ObjectId(team_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Team not found")
    return {"message": "Team deleted"}


@router.post("/teams/{team_id}/members")
async def add_member(team_id: str, data: MemberAssign, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    team = await db.teams.find_one({"_id": ObjectId(team_id)})
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    await db.users.update_one(
        {"_id": ObjectId(data.user_id)},
        {"$set": {"team_id": team_id, "setting_id": team.get("setting_id", "")}}
    )
    return {"message": "Member added"}


@router.delete("/teams/{team_id}/members/{user_id}")
async def remove_member(team_id: str, user_id: str, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$unset": {"team_id": "", "setting_id": "", "org_scope": ""}}
    )
    return {"message": "Member removed"}



# ── Branding ──────────────────────────────────────────────────────────────────

class BrandingUpdate(BaseModel):
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None


@router.get("/branding")
async def get_branding(db=Depends(get_db), current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id")
    if not org_id:
        return {"has_logo": False, "primary_color": None}
    org = await db.organisations.find_one({"_id": ObjectId(org_id)})
    if not org:
        return {"has_logo": False, "primary_color": None}
    b = org.get("branding") or {}
    return {"has_logo": bool(b.get("logo_path")), "primary_color": b.get("primary_color")}


@router.put("/branding")
async def update_branding(data: BrandingUpdate, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="No organisation assigned")
    update: dict = {}
    if data.primary_color is not None:
        update["branding.primary_color"] = data.primary_color
    # logo_url used to clear logo
    if data.logo_url == "":
        update["branding.logo_path"] = None
    await db.organisations.update_one(
        {"_id": ObjectId(org_id)},
        {"$set": {**update, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    return {"message": "Branding updated"}


@router.post("/branding/logo")
async def upload_logo(
    file: UploadFile = File(...),
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 2 MB)")
    allowed_ext = {"png", "jpg", "jpeg", "svg", "webp"}
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "png"
    if ext not in allowed_ext:
        raise HTTPException(status_code=400, detail=f"Unsupported type. Allowed: {', '.join(sorted(allowed_ext))}")
    org_id = current_user.get("org_id") or "shared"
    path = f"branding/{org_id}/{uuid.uuid4()}.{ext}"
    try:
        put_object(path, data, file.content_type or "image/png")
    except Exception as e:
        logger.error(f"Logo upload failed: {e}")
        raise HTTPException(status_code=500, detail="Storage upload failed")
    await db.organisations.update_one(
        {"_id": ObjectId(org_id)},
        {"$set": {"branding.logo_path": path, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    return {"logo_path": path, "has_logo": True}


@router.get("/branding/logo/{org_id}")
async def get_org_logo(org_id: str, db=Depends(get_db)):
    """Public endpoint — no auth needed — serves org logo for <img> tags."""
    try:
        org = await db.organisations.find_one({"_id": ObjectId(org_id)})
        if not org:
            raise HTTPException(status_code=404, detail="Not found")
        path = (org.get("branding") or {}).get("logo_path")
        if not path:
            raise HTTPException(status_code=404, detail="No logo")
        content, content_type = get_object(path)
        return _Response(
            content=content,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Logo serve failed: {e}")
        raise HTTPException(status_code=404, detail="Logo not available")
