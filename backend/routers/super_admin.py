from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional
import re as _re
from deps import get_db, get_current_user

router = APIRouter()


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


class CreateOrgUserRequest(BaseModel):
    email: EmailStr
    name: str
    password: str
    role: str = "manager"


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
