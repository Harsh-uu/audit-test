from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional, List
from deps import get_db, get_current_user

router = APIRouter()


def doc_to_dict(doc):
    if doc is None:
        return None
    doc = dict(doc)
    doc["id"] = str(doc["_id"])
    del doc["_id"]
    return doc


class CreateMeetingRequest(BaseModel):
    title: str
    date: str
    location: Optional[str] = None
    meeting_type: str = "supervision"
    attendee_ids: List[str] = []
    sign_off_manager_id: Optional[str] = None


class UpdateAttendeesRequest(BaseModel):
    attendee_ids: List[str]


class UpdateManagerRequest(BaseModel):
    manager_id: str


@router.post("/")
async def create_meeting(data: CreateMeetingRequest, db=Depends(get_db), current_user=Depends(get_current_user)):
    # Resolve attendees in a single bulk query
    attendees = []
    if data.attendee_ids:
        valid_ids = []
        for uid in data.attendee_ids:
            try:
                valid_ids.append(ObjectId(uid))
            except Exception:
                pass
        users_map = {str(u["_id"]): u async for u in db.users.find({"_id": {"$in": valid_ids}})}
        for uid in data.attendee_ids:
            user = users_map.get(uid)
            if user:
                attendees.append({
                    "user_id": str(user["_id"]),
                    "name": user["name"],
                    "email": user["email"],
                    "role": user["role"],
                    "present": True,
                    "reviewed": False,
                    "reviewed_at": None,
                })

    manager_name = None
    if data.sign_off_manager_id:
        try:
            mgr = await db.users.find_one({"_id": ObjectId(data.sign_off_manager_id)})
            if mgr:
                manager_name = mgr["name"]
        except Exception:
            pass

    now = datetime.now(timezone.utc).isoformat()
    meeting_doc = {
        "title": data.title,
        "date": data.date,
        "location": data.location,
        "meeting_type": data.meeting_type,
        "org_id": current_user.get("org_id"),
        "created_by": current_user["id"],
        "created_by_name": current_user["name"],
        "sign_off_manager_id": data.sign_off_manager_id,
        "sign_off_manager_name": manager_name,
        "attendees": attendees,
        "team_id": current_user.get("team_id") or None,
        "setting_id": current_user.get("setting_id") or None,
        "status": "draft",
        "recording_events": [],
        "paused_periods": [],
        "total_paused_duration_seconds": 0,
        "recording_notice_shown_at": None,
        "audio_file_id": None,
        "transcript_id": None,
        "analysis_id": None,
        "sign_off_record": None,
        "audio_deletion_status": "none",
        "audio_grace_period_started_at": None,
        "audio_deleted_at": None,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.meetings.insert_one(meeting_doc)
    meeting_doc["id"] = str(result.inserted_id)
    del meeting_doc["_id"]
    return meeting_doc


@router.get("/")
async def list_meetings(db=Depends(get_db), current_user=Depends(get_current_user)):
    user_id = current_user["id"]
    role = current_user["role"]

    # Super admin has no org scope — return empty from regular dashboard
    if role == "super_admin":
        return []

    org_id = current_user.get("org_id")
    org_filter = {"org_id": org_id} if org_id else {}

    if role == "admin":
        cursor = db.meetings.find(org_filter).sort("created_at", -1).limit(500)
    elif role == "manager":
        or_conditions = [
            {"created_by": user_id},
            {"sign_off_manager_id": user_id},
            {"attendees.user_id": user_id},
        ]
        if current_user.get("team_id"):
            or_conditions.append({"team_id": current_user["team_id"]})
        if current_user.get("setting_id"):
            or_conditions.append({"setting_id": current_user["setting_id"]})
        query = {**org_filter, "$or": or_conditions}
        cursor = db.meetings.find(query).sort("created_at", -1).limit(500)
    else:
        query = {
            **org_filter,
            "$or": [
                {"created_by": user_id},
                {"attendees.user_id": user_id},
            ]
        }
        cursor = db.meetings.find(query).sort("created_at", -1).limit(500)

    meetings = []
    async for doc in cursor:
        meetings.append(doc_to_dict(doc))
    return meetings


@router.get("/{meeting_id}")
async def get_meeting(meeting_id: str, db=Depends(get_db), current_user=Depends(get_current_user)):
    try:
        doc = await db.meetings.find_one({"_id": ObjectId(meeting_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid meeting ID")
    if not doc:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = doc_to_dict(doc)

    # Attach transcript
    if meeting.get("transcript_id"):
        try:
            tdoc = await db.transcripts.find_one({"_id": ObjectId(meeting["transcript_id"])})
            if tdoc:
                meeting["transcript"] = doc_to_dict(tdoc)
        except Exception:
            pass

    # Attach analysis
    if meeting.get("analysis_id"):
        try:
            adoc = await db.analyses.find_one({"_id": ObjectId(meeting["analysis_id"])})
            if adoc:
                meeting["analysis"] = doc_to_dict(adoc)
        except Exception:
            pass

    # Attach comments
    meeting["comments"] = []
    async for c in db.reviewer_comments.find({"meeting_id": str(meeting["id"])}).sort("created_at", 1):
        meeting["comments"].append(doc_to_dict(c))

    return meeting


@router.put("/{meeting_id}/attendees")
async def update_attendees(meeting_id: str, data: UpdateAttendeesRequest, db=Depends(get_db), current_user=Depends(get_current_user)):  # noqa: E501
    attendees = []
    if data.attendee_ids:
        valid_ids = []
        for uid in data.attendee_ids:
            try:
                valid_ids.append(ObjectId(uid))
            except Exception:
                pass
        users_map = {str(u["_id"]): u async for u in db.users.find({"_id": {"$in": valid_ids}})}
        for uid in data.attendee_ids:
            user = users_map.get(uid)
            if user:
                attendees.append({
                    "user_id": str(user["_id"]),
                    "name": user["name"],
                    "email": user["email"],
                    "role": user["role"],
                    "present": True,
                    "reviewed": False,
                    "reviewed_at": None,
                })
    await db.meetings.update_one(
        {"_id": ObjectId(meeting_id)},
        {"$set": {"attendees": attendees, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    return {"message": "Attendees updated"}


@router.put("/{meeting_id}/manager")
async def update_manager(meeting_id: str, data: UpdateManagerRequest, db=Depends(get_db), current_user=Depends(get_current_user)):  # noqa: E501
    mgr = await db.users.find_one({"_id": ObjectId(data.manager_id)})
    if not mgr:
        raise HTTPException(status_code=404, detail="Manager not found")
    await db.meetings.update_one(
        {"_id": ObjectId(meeting_id)},
        {"$set": {
            "sign_off_manager_id": data.manager_id,
            "sign_off_manager_name": mgr["name"],
            "updated_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    return {"message": "Manager updated"}


@router.delete("/{meeting_id}")
async def delete_meeting(meeting_id: str, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    try:
        result = await db.meetings.delete_one({"_id": ObjectId(meeting_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Meeting not found")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid meeting ID")
    return {"message": "Meeting deleted"}
