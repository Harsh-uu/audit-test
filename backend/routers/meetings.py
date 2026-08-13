import json
import uuid
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from datetime import datetime, timezone
from typing import Optional, List
from deps import get_db, get_current_user, get_manager_scope, get_scoped_staff_ids
import database

router = APIRouter()


class CreateMeetingRequest(BaseModel):
    title: str
    date: str
    location: Optional[str] = None
    meeting_type: str = "supervision"
    attendee_ids: List[str] = []
    sign_off_manager_id: Optional[str] = None
    schedule_id: Optional[str] = None


class UpdateAttendeesRequest(BaseModel):
    attendee_ids: List[str]


class UpdateManagerRequest(BaseModel):
    manager_id: str


async def _resolve_attendees(conn, attendee_ids: List[str], org_id: str) -> list:
    if not attendee_ids:
        return []
    rows = await conn.fetch(
        "SELECT id, name, email, role FROM users WHERE id = ANY($1) AND org_id = $2",
        attendee_ids, org_id,
    )
    user_map = {r["id"]: dict(r) for r in rows}
    attendees = []
    for uid in attendee_ids:
        u = user_map.get(uid)
        if u:
            attendees.append({
                "user_id": u["id"], "name": u["name"], "email": u["email"],
                "role": u["role"], "present": True, "reviewed": False, "reviewed_at": None,
            })
    return attendees


def _ensure_list(val, field=""):
    """Return val as a Python list; json.loads if it's a string."""
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return val or []


def _ensure_dict(val):
    """Return val as a Python dict; json.loads if it's a string."""
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return val or {}


def _parse_meeting_row(m: dict) -> dict:
    """Normalize JSONB list/dict fields on a meeting row."""
    for field in ("attendees", "recording_events", "paused_periods", "shared_with", "pii_redactions"):
        m[field] = _ensure_list(m.get(field))
    for field in ("sign_off_record", "reopen_record"):
        m[field] = _ensure_dict(m.get(field))
    return m


def _parse_analysis_row(a: dict) -> dict:
    """Normalize JSONB fields on an analysis row."""
    for field in ("actions", "risks", "cqc_mappings", "care_cert_mappings", "custom_mappings", "pii_redactions", "achievements", "learning_needs"):
        a[field] = _ensure_list(a.get(field))
    for field in ("speaker_colors",):
        a[field] = _ensure_dict(a.get(field))
    return a


@router.post("/")
async def create_meeting(data: CreateMeetingRequest, current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    now = datetime.now(timezone.utc).isoformat()
    meeting_id = str(uuid.uuid4())

    async with database.with_org(org_id) as conn:
        attendees = await _resolve_attendees(conn, data.attendee_ids, org_id)
        manager_name = None
        if data.sign_off_manager_id:
            mgr = await conn.fetchrow(
                "SELECT name FROM users WHERE id = $1 AND org_id = $2",
                data.sign_off_manager_id, org_id,
            )
            if mgr:
                manager_name = mgr["name"]

        await conn.execute(
            """INSERT INTO meetings
               (id, org_id, title, date, location, meeting_type, created_by, created_by_name,
                sign_off_manager_id, sign_off_manager_name, attendees, team_id, setting_id,
                schedule_id, status, recording_events, paused_periods,
                total_paused_duration_seconds, audio_deletion_status, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$20)""",
            meeting_id, org_id, data.title, data.date, data.location, data.meeting_type,
            current_user["id"], current_user.get("name", ""),
            data.sign_off_manager_id, manager_name,
            attendees,
            current_user.get("team_id"), current_user.get("setting_id"),
            data.schedule_id, "draft",
            [], [], 0, "none", now,
        )

    return {
        "id": meeting_id, "org_id": org_id, "title": data.title, "date": data.date,
        "location": data.location, "meeting_type": data.meeting_type,
        "created_by": current_user["id"], "created_by_name": current_user.get("name", ""),
        "sign_off_manager_id": data.sign_off_manager_id, "sign_off_manager_name": manager_name,
        "attendees": attendees, "status": "draft",
        "recording_events": [], "paused_periods": [], "total_paused_duration_seconds": 0,
        "audio_deletion_status": "none", "created_at": now, "updated_at": now,
    }


@router.get("/")
async def list_meetings(current_user=Depends(get_current_user)):
    role = current_user["role"]
    if role == "super_admin":
        return []
    org_id = current_user.get("org_id", "")
    user_id = current_user["id"]
    scope = get_manager_scope(current_user)

    # Attendees / shared_reviewers with no org_id (e.g. some invited users whose
    # org_id was not written during invite acceptance) — bypass RLS and query
    # directly by user_id so they can still see their meetings.
    if role not in ("admin", "manager") and not org_id:
        async with database.with_admin() as conn:
            rows = await conn.fetch(
                """SELECT * FROM meetings
                   WHERE created_by=$1
                      OR EXISTS (
                          SELECT 1 FROM jsonb_array_elements(COALESCE(attendees,'[]'::jsonb)) a
                          WHERE a->>'user_id' = $1::text
                      )
                      OR EXISTS (
                          SELECT 1 FROM jsonb_array_elements(COALESCE(shared_with,'[]'::jsonb)) s
                          WHERE s->>'user_id' = $1::text
                      )
                   ORDER BY created_at DESC LIMIT 500""",
                user_id,
            )
        return [_parse_meeting_row(dict(r)) for r in rows]

    if not org_id:
        return []

    async with database.with_org(org_id) as conn:
        if role == "admin":
            rows = await conn.fetch(
                "SELECT * FROM meetings ORDER BY created_at DESC LIMIT 500"
            )

        elif role == "manager":
            if scope["level"] == "org":
                # Org-level manager sees every meeting in the org
                rows = await conn.fetch(
                    "SELECT * FROM meetings ORDER BY created_at DESC LIMIT 500"
                )
            else:
                # Scoped manager — get current team/setting members
                scoped_staff_ids_list = await get_scoped_staff_ids(conn, org_id, scope)
                scoped_staff_ids = set(scoped_staff_ids_list or [])
                # Include the manager themselves so their personally-created meetings appear
                all_scoped = list(scoped_staff_ids | {user_id})

                # Convert UUIDs to strings so text = ANY(text[]) comparisons work
                all_scoped_str = [str(uid) for uid in all_scoped]

                rows = await conn.fetch(
                    """SELECT * FROM meetings
                       WHERE created_by::text = ANY($1)
                          OR sign_off_manager_id::text = ANY($1)
                          OR EXISTS (
                              SELECT 1 FROM jsonb_array_elements(COALESCE(attendees,'[]'::jsonb)) a
                              WHERE a->>'user_id' = ANY($1)
                          )
                       ORDER BY created_at DESC LIMIT 500""",
                    all_scoped_str,
                )
                result = []
                scoped_staff_ids_str = {str(uid) for uid in scoped_staff_ids}
                user_id_str = str(user_id)
                for row in rows:
                    m = _parse_meeting_row(dict(row))
                    attendee_ids = {str(a.get("user_id", "")) for a in m.get("attendees", [])}
                    # Staff attendees = everyone except the manager themselves
                    staff_attendees = attendee_ids - {user_id_str}
                    if staff_attendees:
                        # Historical if NONE of the staff attendees are still in scope
                        m["is_historical"] = len(staff_attendees & scoped_staff_ids_str) == 0
                    else:
                        m["is_historical"] = False
                    result.append(m)
                return result

        else:
            rows = await conn.fetch(
                """SELECT * FROM meetings
                   WHERE created_by=$1
                      OR EXISTS (
                          SELECT 1 FROM jsonb_array_elements(COALESCE(attendees,'[]'::jsonb)) a
                          WHERE a->>'user_id' = $1::text
                      )
                      OR EXISTS (
                          SELECT 1 FROM jsonb_array_elements(COALESCE(shared_with,'[]'::jsonb)) s
                          WHERE s->>'user_id' = $1::text
                      )
                   ORDER BY created_at DESC LIMIT 500""",
                user_id,
            )

    return [_parse_meeting_row(dict(r)) for r in rows]


@router.get("/{meeting_id}")
async def get_meeting(meeting_id: str, current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    user_id = current_user.get("id", "")

    async with database.with_org(org_id) as conn:
        row = await conn.fetchrow("SELECT * FROM meetings WHERE id = $1", meeting_id)
        if not row:
            raise HTTPException(status_code=404, detail="Meeting not found")
        meeting = _parse_meeting_row(dict(row))

        # Access check for non-admin/manager
        if current_user["role"] not in ["admin", "manager", "super_admin"]:
            attendee_ids = [a.get("user_id", "") for a in meeting["attendees"]]
            shared_with = meeting["shared_with"]
            is_shared_with_user = any(isinstance(s, dict) and s.get("user_id") == user_id for s in shared_with)
            if user_id not in attendee_ids and not is_shared_with_user and user_id != meeting.get("created_by", ""):
                raise HTTPException(status_code=404, detail="Meeting not found")

        # Attach transcript
        if meeting.get("transcript_id"):
            t_row = await conn.fetchrow("SELECT * FROM transcripts WHERE id = $1", meeting["transcript_id"])
            if t_row:
                tr = dict(t_row)
                tr["safety_warnings"] = _ensure_list(tr.get("safety_warnings"))
                tr["speaker_colors"] = _ensure_dict(tr.get("speaker_colors"))
                meeting["transcript"] = tr

        # Attach analysis
        if meeting.get("analysis_id"):
            a_row = await conn.fetchrow("SELECT * FROM analyses WHERE id = $1", meeting["analysis_id"])
            if a_row:
                meeting["analysis"] = _parse_analysis_row(dict(a_row))

        # Attach comments
        c_rows = await conn.fetch(
            "SELECT * FROM reviewer_comments WHERE meeting_id = $1 ORDER BY created_at ASC", meeting_id
        )
        meeting["comments"] = [dict(c) for c in c_rows]

    # Enrich attendee emails from live user accounts
    if meeting.get("attendees"):
        async with database.with_admin() as conn:
            enriched = []
            for attendee in meeting["attendees"]:
                uid = attendee.get("user_id")
                if uid:
                    u = await conn.fetchrow("SELECT email FROM users WHERE id = $1", uid)
                    if u and u["email"]:
                        attendee = {**attendee, "email": u["email"]}
                enriched.append(attendee)
            meeting["attendees"] = enriched

            if meeting.get("created_by"):
                creator = await conn.fetchrow(
                    "SELECT email, name FROM users WHERE id = $1", meeting["created_by"]
                )
                if creator:
                    meeting["created_by_email"] = creator["email"]
                    meeting["created_by_name"] = meeting.get("created_by_name") or creator["name"]

    # Apply PII redactions
    from routers.review import _apply_redactions_to_text, _apply_redactions_deep, _has_privileged_access
    redactions = meeting.get("pii_redactions") or []
    if redactions and meeting.get("transcript"):
        t = meeting["transcript"]
        if t.get("speaker_text"):
            t["speaker_text"] = _apply_redactions_to_text(t["speaker_text"], redactions)
        if not _has_privileged_access(meeting, user_id) and t.get("text"):
            t["text"] = _apply_redactions_to_text(t["text"], redactions)
    if redactions:
        if not _has_privileged_access(meeting, user_id):
            meeting.pop("pii_redactions", None)
            meeting["pii_redactions_count"] = len(redactions)
    if meeting.get("analysis") and redactions:
        meeting["analysis"] = _apply_redactions_deep(meeting["analysis"], redactions)

    return meeting


@router.put("/{meeting_id}/attendees")
async def update_attendees(meeting_id: str, data: UpdateAttendeesRequest, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        attendees = await _resolve_attendees(conn, data.attendee_ids, org_id)
        result = await conn.execute(
            "UPDATE meetings SET attendees=$1, updated_at=$2 WHERE id=$3",
            attendees, datetime.now(timezone.utc).isoformat(), meeting_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Meeting not found")
    return {"message": "Attendees updated"}


@router.put("/{meeting_id}/manager")
async def update_manager(meeting_id: str, data: UpdateManagerRequest, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        mgr = await conn.fetchrow("SELECT name FROM users WHERE id = $1 AND org_id = $2", data.manager_id, org_id)
        if not mgr:
            raise HTTPException(status_code=404, detail="Manager not found")
        await conn.execute(
            """UPDATE meetings SET sign_off_manager_id=$1, sign_off_manager_name=$2, updated_at=$3
               WHERE id=$4""",
            data.manager_id, mgr["name"], datetime.now(timezone.utc).isoformat(), meeting_id,
        )
    return {"message": "Manager updated"}


@router.delete("/{meeting_id}")
async def delete_meeting(meeting_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        result = await conn.execute("DELETE FROM meetings WHERE id = $1", meeting_id)
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="Meeting not found")
        # Cascade deletes
        for table in ["transcripts", "analyses", "audio_files", "reviewer_comments", "review_edits", "audit_logs"]:
            await conn.execute(f"DELETE FROM {table} WHERE meeting_id = $1", meeting_id)
    return {"message": "Meeting deleted"}
