from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional
from deps import get_db, get_current_user

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
    settings = []
    async for s in db.org_settings.find({}).sort("name", 1):
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

    unassigned = []
    async for u in db.users.find({
        "$and": [
            {"is_active": {"$ne": False}},
            {"$or": [{"team_id": {"$exists": False}}, {"team_id": None}]},
        ]
    }).sort("name", 1):
        unassigned.append({
            "id": str(u["_id"]),
            "name": u["name"],
            "email": u["email"],
            "role": u["role"],
        })

    return {"settings": settings, "unassigned_users": unassigned}


@router.get("/settings")
async def list_settings(db=Depends(get_db), current_user=Depends(get_current_user)):
    result = []
    async for s in db.org_settings.find({}).sort("name", 1):
        result.append(_to(s))
    return result


@router.post("/settings")
async def create_setting(data: SettingCreate, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    now = datetime.now(timezone.utc).isoformat()
    doc = {"name": data.name, "description": data.description or "", "manager_user_id": data.manager_user_id or None, "created_at": now, "updated_at": now}
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
    doc = {"name": data.name, "description": data.description or "", "setting_id": setting_id, "supervisor_user_id": data.supervisor_user_id or None, "created_at": now, "updated_at": now}
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
