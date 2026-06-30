from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from datetime import datetime, timezone, date
import calendar
from pydantic import BaseModel
from typing import List, Optional
from deps import get_db, get_current_user

router = APIRouter()

DEFAULT_MEETING_TYPES = [
    {"name": "Monthly Supervision",        "default_frequency": "monthly",   "color": "#3B82F6"},
    {"name": "Quarterly Team Meeting",     "default_frequency": "quarterly", "color": "#10B981"},
    {"name": "Quarterly Appraisal",        "default_frequency": "quarterly", "color": "#F59E0B"},
    {"name": "Annual Performance Review",  "default_frequency": "annual",    "color": "#8B5CF6"},
]

FREQ_MONTHS = {"monthly": 1, "quarterly": 3, "annual": 12}
FREQ_LABELS = {"monthly": "Monthly", "quarterly": "Quarterly", "annual": "Annual"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def next_due_date(start_date_str: str, frequency: str, completed_count: int) -> str:
    try:
        start = date.fromisoformat(start_date_str)
        months = FREQ_MONTHS.get(frequency, 1) * completed_count
        return add_months(start, months).isoformat()
    except Exception:
        return start_date_str


async def seed_meeting_types(db, org_id: str):
    """Auto-seed the 4 default meeting types for a new org on first use."""
    count = await db.meeting_types.count_documents({"org_id": org_id, "is_active": True})
    if count == 0:
        now = datetime.now(timezone.utc).isoformat()
        docs = [{"org_id": org_id, "is_active": True, "created_at": now, **t} for t in DEFAULT_MEETING_TYPES]
        await db.meeting_types.insert_many(docs)


async def _enriched_schedules(db, org_id: str):
    """Returns all active schedules enriched with next_due, staff name, type name etc."""
    schedules = []
    async for s in db.schedules.find({"org_id": org_id, "is_active": True}):
        s["id"] = str(s["_id"])
        del s["_id"]
        schedules.append(s)

    if not schedules:
        return []

    schedule_ids = [s["id"] for s in schedules]

    # Count completed meetings per schedule
    completed_counts: dict = {}
    async for m in db.meetings.find({
        "org_id": org_id,
        "schedule_id": {"$in": schedule_ids},
        "status": {"$in": ["signed_off", "reviewed", "in_review"]},
    }):
        sid = m.get("schedule_id", "")
        completed_counts[sid] = completed_counts.get(sid, 0) + 1

    # Meeting type map
    type_map: dict = {}
    async for t in db.meeting_types.find({"org_id": org_id}):
        type_map[str(t["_id"])] = t

    # User map
    user_map: dict = {}
    async for u in db.users.find({"org_id": org_id}):
        user_map[str(u["_id"])] = {
            "id": str(u["_id"]), "name": u.get("name", ""),
            "role": u.get("role", ""), "email": u.get("email", ""),
        }

    today = date.today().isoformat()
    result = []
    for s in schedules:
        completed = completed_counts.get(s["id"], 0)
        nd = next_due_date(s["start_date"], s["frequency"], completed)
        mt = type_map.get(s.get("meeting_type_id", ""), {})
        staff = user_map.get(s.get("staff_user_id", ""), {})
        days_diff = (date.fromisoformat(nd) - date.today()).days
        result.append({
            **s,
            "next_due": nd,
            "completed_count": completed,
            "is_overdue": nd < today,
            "days_until_due": days_diff,
            "meeting_type_name": mt.get("name", "Unknown"),
            "meeting_type_color": mt.get("color", "#3B82F6"),
            "staff_name": staff.get("name", "Unknown"),
            "staff_role": staff.get("role", ""),
            "staff_email": staff.get("email", ""),
        })

    return result


# ── Models ────────────────────────────────────────────────────────────────────

class MeetingTypeCreate(BaseModel):
    name: str
    default_frequency: str = "monthly"
    color: str = "#3B82F6"


class ScheduleCreate(BaseModel):
    staff_user_id: str
    meeting_type_id: str
    frequency: str
    start_date: str


class ScheduleBulkCreate(BaseModel):
    meeting_type_id: str
    frequency: str
    start_date: str
    staff_user_ids: List[str]


class ScheduleUpdate(BaseModel):
    frequency: str
    start_date: str
    meeting_type_id: Optional[str] = None


# ── Meeting Types ─────────────────────────────────────────────────────────────

@router.get("/meeting-types")
async def list_meeting_types(db=Depends(get_db), current_user=Depends(get_current_user)):
    org_id = current_user["org_id"]
    await seed_meeting_types(db, org_id)
    types = []
    async for t in db.meeting_types.find({"org_id": org_id, "is_active": True}).sort("name", 1):
        t["id"] = str(t["_id"])
        del t["_id"]
        types.append(t)
    return types


@router.post("/meeting-types")
async def create_meeting_type(data: MeetingTypeCreate, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    doc = {
        "org_id": current_user["org_id"],
        "name": data.name.strip(),
        "default_frequency": data.default_frequency,
        "color": data.color,
        "is_active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    result = await db.meeting_types.insert_one(doc)
    return {"id": str(result.inserted_id), **{k: v for k, v in doc.items() if k != "_id"}}


@router.put("/meeting-types/{type_id}")
async def update_meeting_type(type_id: str, data: MeetingTypeCreate, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403)
    await db.meeting_types.update_one(
        {"_id": ObjectId(type_id), "org_id": current_user["org_id"]},
        {"$set": {"name": data.name.strip(), "default_frequency": data.default_frequency, "color": data.color}},
    )
    return {"ok": True}


@router.delete("/meeting-types/{type_id}")
async def delete_meeting_type(type_id: str, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403)
    await db.meeting_types.update_one(
        {"_id": ObjectId(type_id), "org_id": current_user["org_id"]},
        {"$set": {"is_active": False}},
    )
    return {"ok": True}


# ── Schedules ─────────────────────────────────────────────────────────────────

@router.get("/due")
async def get_due_meetings(db=Depends(get_db), current_user=Depends(get_current_user)):
    """Dashboard widget: overdue + due-this-month schedules."""
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403)
    all_s = await _enriched_schedules(db, current_user["org_id"])
    today = date.today()
    # End of current month
    last_day = calendar.monthrange(today.year, today.month)[1]
    month_end = date(today.year, today.month, last_day).isoformat()
    today_iso = today.isoformat()
    due = [s for s in all_s if s["next_due"] <= month_end]
    due.sort(key=lambda s: s["next_due"])
    return due


@router.get("/")
async def list_schedules(db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403)
    return await _enriched_schedules(db, current_user["org_id"])


@router.post("/bulk")
async def bulk_create_schedules(data: ScheduleBulkCreate, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403)
    org_id = current_user["org_id"]
    now = datetime.now(timezone.utc).isoformat()

    # Find existing schedules of same type to skip duplicates
    existing_staff = set()
    async for s in db.schedules.find({
        "org_id": org_id, "meeting_type_id": data.meeting_type_id, "is_active": True,
    }):
        existing_staff.add(s["staff_user_id"])

    docs = []
    skipped = 0
    for uid in data.staff_user_ids:
        if uid in existing_staff:
            skipped += 1
            continue
        u = await db.users.find_one({"_id": ObjectId(uid), "org_id": org_id})
        if not u:
            continue
        docs.append({
            "org_id": org_id,
            "staff_user_id": uid,
            "meeting_type_id": data.meeting_type_id,
            "frequency": data.frequency,
            "start_date": data.start_date,
            "is_active": True,
            "created_by": current_user["id"],
            "created_at": now,
        })

    created = 0
    if docs:
        result = await db.schedules.insert_many(docs)
        created = len(result.inserted_ids)

    return {"created": created, "skipped": skipped, "total": len(data.staff_user_ids)}


@router.post("/")
async def create_schedule(data: ScheduleCreate, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403)
    org_id = current_user["org_id"]

    existing = await db.schedules.find_one({
        "org_id": org_id,
        "staff_user_id": data.staff_user_id,
        "meeting_type_id": data.meeting_type_id,
        "is_active": True,
    })
    if existing:
        raise HTTPException(400, "Schedule already exists for this staff member and meeting type")

    doc = {
        "org_id": org_id,
        "staff_user_id": data.staff_user_id,
        "meeting_type_id": data.meeting_type_id,
        "frequency": data.frequency,
        "start_date": data.start_date,
        "is_active": True,
        "created_by": current_user["id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    result = await db.schedules.insert_one(doc)
    return {"id": str(result.inserted_id), **{k: v for k, v in doc.items() if k != "_id"}}


@router.put("/{schedule_id}")
async def update_schedule(schedule_id: str, data: ScheduleUpdate, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403)
    update = {"frequency": data.frequency, "start_date": data.start_date}
    if data.meeting_type_id:
        update["meeting_type_id"] = data.meeting_type_id
    await db.schedules.update_one(
        {"_id": ObjectId(schedule_id), "org_id": current_user["org_id"]},
        {"$set": update},
    )
    return {"ok": True}


@router.delete("/{schedule_id}")
async def delete_schedule(schedule_id: str, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403)
    await db.schedules.update_one(
        {"_id": ObjectId(schedule_id), "org_id": current_user["org_id"]},
        {"$set": {"is_active": False}},
    )
    return {"ok": True}
