import uuid
import json
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone, date
import calendar
from pydantic import BaseModel
from typing import List, Optional
from deps import get_db, get_current_user, get_manager_scope, get_scoped_staff_ids
import database

router = APIRouter()

DEFAULT_MEETING_TYPES = [
    {"name": "Monthly Supervision",       "default_frequency": "monthly",   "color": "#3B82F6"},
    {"name": "Quarterly Team Meeting",    "default_frequency": "quarterly", "color": "#10B981"},
    {"name": "Quarterly Appraisal",       "default_frequency": "quarterly", "color": "#F59E0B"},
    {"name": "Annual Performance Review", "default_frequency": "annual",    "color": "#8B5CF6"},
]

FREQ_MONTHS = {"monthly": 1, "quarterly": 3, "annual": 12}
FREQ_LABELS = {"monthly": "Monthly", "quarterly": "Quarterly", "annual": "Annual"}


def freq_label(frequency: str) -> str:
    if frequency and frequency.startswith("weeks_"):
        try:
            n = int(frequency.split("_")[1])
            return f"Every {n} week{'s' if n != 1 else ''}"
        except (IndexError, ValueError):
            pass
    return FREQ_LABELS.get(frequency, frequency.capitalize() if frequency else "")


def add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def next_due_date(start_date_str: str, frequency: str, completed_count: int) -> str:
    try:
        start = date.fromisoformat(start_date_str)
        if frequency and frequency.startswith("weeks_"):
            from datetime import timedelta
            weeks = int(frequency.split("_")[1])
            return (start + timedelta(weeks=weeks * completed_count)).isoformat()
        months = FREQ_MONTHS.get(frequency, 1) * completed_count
        return add_months(start, months).isoformat()
    except Exception:
        return start_date_str


async def seed_meeting_types(conn, org_id: str):
    count = await conn.fetchval("SELECT COUNT(*) FROM meeting_types WHERE org_id = $1 AND is_active = TRUE", org_id)
    if count == 0:
        now = datetime.now(timezone.utc).isoformat()
        for t in DEFAULT_MEETING_TYPES:
            await conn.execute(
                """INSERT INTO meeting_types (id, org_id, name, default_frequency, color, is_active, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)""",
                str(uuid.uuid4()), org_id, t["name"], t["default_frequency"], t["color"], True, now,
            )


async def _enriched_schedules(conn, org_id: str, staff_ids=None):
    if staff_ids is not None:
        s_rows = await conn.fetch(
            "SELECT * FROM schedules WHERE org_id=$1 AND is_active=TRUE AND staff_user_id=ANY($2)",
            org_id, staff_ids,
        )
    else:
        s_rows = await conn.fetch(
            "SELECT * FROM schedules WHERE org_id = $1 AND is_active = TRUE", org_id
        )
    if not s_rows:
        return []

    schedule_ids = [s["id"] for s in s_rows]

    # Count completed meetings per schedule
    m_rows = await conn.fetch(
        """SELECT schedule_id FROM meetings
           WHERE org_id = $1 AND schedule_id = ANY($2)
             AND status IN ('signed_off', 'reviewed', 'in_review')""",
        org_id, schedule_ids,
    )
    completed_counts = {}
    for m in m_rows:
        sid = m["schedule_id"]
        completed_counts[sid] = completed_counts.get(sid, 0) + 1

    # Meeting type map
    mt_rows = await conn.fetch("SELECT * FROM meeting_types WHERE org_id = $1", org_id)
    type_map = {t["id"]: dict(t) for t in mt_rows}

    # User map
    u_rows = await conn.fetch(
        "SELECT id, name, role, email FROM users WHERE org_id = $1", org_id
    )
    user_map = {u["id"]: dict(u) for u in u_rows}

    today = date.today().isoformat()
    result = []
    for s in s_rows:
        s = dict(s)
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


@router.get("/meeting-types")
async def list_meeting_types(current_user=Depends(get_current_user)):
    org_id = current_user["org_id"]
    async with database.with_org(org_id) as conn:
        await seed_meeting_types(conn, org_id)
        rows = await conn.fetch(
            "SELECT * FROM meeting_types WHERE org_id = $1 AND is_active = TRUE ORDER BY name ASC", org_id
        )
    return [dict(r) for r in rows]


@router.post("/meeting-types")
async def create_meeting_type(data: MeetingTypeCreate, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user["org_id"]
    mt_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    async with database.with_org(org_id) as conn:
        await conn.execute(
            """INSERT INTO meeting_types (id, org_id, name, default_frequency, color, is_active, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7)""",
            mt_id, org_id, data.name.strip(), data.default_frequency, data.color, True, now,
        )
    return {"id": mt_id, "org_id": org_id, "name": data.name.strip(), "default_frequency": data.default_frequency, "color": data.color, "is_active": True, "created_at": now}


@router.put("/meeting-types/{type_id}")
async def update_meeting_type(type_id: str, data: MeetingTypeCreate, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403)
    org_id = current_user["org_id"]
    async with database.with_org(org_id) as conn:
        await conn.execute(
            "UPDATE meeting_types SET name=$1, default_frequency=$2, color=$3 WHERE id=$4",
            data.name.strip(), data.default_frequency, data.color, type_id,
        )
    return {"ok": True}


@router.delete("/meeting-types/{type_id}")
async def delete_meeting_type(type_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403)
    org_id = current_user["org_id"]
    async with database.with_org(org_id) as conn:
        await conn.execute("UPDATE meeting_types SET is_active=FALSE WHERE id=$1", type_id)
    return {"ok": True}


@router.get("/due")
async def get_due_meetings(current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403)
    org_id = current_user["org_id"]
    scope = get_manager_scope(current_user)
    async with database.with_org(org_id) as conn:
        staff_ids = await get_scoped_staff_ids(conn, org_id, scope)
        all_s = await _enriched_schedules(conn, org_id, staff_ids)
    today = date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    month_end = date(today.year, today.month, last_day).isoformat()
    due = [s for s in all_s if s["next_due"] <= month_end]
    due.sort(key=lambda s: s["next_due"])
    return due


@router.get("/")
async def list_schedules(current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403)
    org_id = current_user["org_id"]
    scope = get_manager_scope(current_user)
    async with database.with_org(org_id) as conn:
        staff_ids = await get_scoped_staff_ids(conn, org_id, scope)
        return await _enriched_schedules(conn, org_id, staff_ids)


@router.post("/bulk")
async def bulk_create_schedules(data: ScheduleBulkCreate, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403)
    org_id = current_user["org_id"]
    now = datetime.now(timezone.utc).isoformat()
    async with database.with_org(org_id) as conn:
        existing_rows = await conn.fetch(
            "SELECT staff_user_id FROM schedules WHERE org_id=$1 AND meeting_type_id=$2 AND is_active=TRUE",
            org_id, data.meeting_type_id,
        )
        existing_staff = {r["staff_user_id"] for r in existing_rows}
        created, skipped = 0, 0
        for uid in data.staff_user_ids:
            if uid in existing_staff:
                skipped += 1
                continue
            u = await conn.fetchrow("SELECT id FROM users WHERE id=$1 AND org_id=$2", uid, org_id)
            if not u:
                continue
            await conn.execute(
                """INSERT INTO schedules (id, org_id, staff_user_id, meeting_type_id, frequency, start_date, is_active, created_by, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
                str(uuid.uuid4()), org_id, uid, data.meeting_type_id, data.frequency,
                data.start_date, True, current_user["id"], now,
            )
            created += 1
    return {"created": created, "skipped": skipped, "total": len(data.staff_user_ids)}


@router.post("/")
async def create_schedule(data: ScheduleCreate, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403)
    org_id = current_user["org_id"]
    now = datetime.now(timezone.utc).isoformat()
    async with database.with_org(org_id) as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM schedules WHERE org_id=$1 AND staff_user_id=$2 AND meeting_type_id=$3 AND is_active=TRUE",
            org_id, data.staff_user_id, data.meeting_type_id,
        )
        if existing:
            raise HTTPException(400, "Schedule already exists for this staff member and meeting type")
        sched_id = str(uuid.uuid4())
        await conn.execute(
            """INSERT INTO schedules (id, org_id, staff_user_id, meeting_type_id, frequency, start_date, is_active, created_by, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
            sched_id, org_id, data.staff_user_id, data.meeting_type_id,
            data.frequency, data.start_date, True, current_user["id"], now,
        )
    return {"id": sched_id, "org_id": org_id, "staff_user_id": data.staff_user_id,
            "meeting_type_id": data.meeting_type_id, "frequency": data.frequency,
            "start_date": data.start_date, "is_active": True}


@router.put("/{schedule_id}")
async def update_schedule(schedule_id: str, data: ScheduleUpdate, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403)
    org_id = current_user["org_id"]
    async with database.with_org(org_id) as conn:
        if data.meeting_type_id:
            await conn.execute(
                "UPDATE schedules SET frequency=$1, start_date=$2, meeting_type_id=$3 WHERE id=$4",
                data.frequency, data.start_date, data.meeting_type_id, schedule_id,
            )
        else:
            await conn.execute(
                "UPDATE schedules SET frequency=$1, start_date=$2 WHERE id=$3",
                data.frequency, data.start_date, schedule_id,
            )
    return {"ok": True}


@router.delete("/{schedule_id}")
async def delete_schedule(schedule_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403)
    org_id = current_user["org_id"]
    async with database.with_org(org_id) as conn:
        await conn.execute("UPDATE schedules SET is_active=FALSE WHERE id=$1", schedule_id)
    return {"ok": True}
