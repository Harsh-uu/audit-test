from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional
from deps import get_db, get_current_user

router = APIRouter()


class RecordingEventRequest(BaseModel):
    timestamp: Optional[str] = None
    pause_start: Optional[str] = None


@router.post("/{meeting_id}/notice")
async def log_notice(meeting_id: str, db=Depends(get_db), current_user=Depends(get_current_user)):
    now = datetime.now(timezone.utc).isoformat()
    await db.meetings.update_one(
        {"_id": ObjectId(meeting_id)},
        {"$set": {"recording_notice_shown_at": now, "updated_at": now}}
    )
    return {"message": "Notice logged", "timestamp": now}


@router.post("/{meeting_id}/start")
async def start_recording(meeting_id: str, data: RecordingEventRequest, db=Depends(get_db), current_user=Depends(get_current_user)):
    ts = data.timestamp or datetime.now(timezone.utc).isoformat()
    event = {"type": "started", "timestamp": ts, "user_id": current_user["id"]}
    await db.meetings.update_one(
        {"_id": ObjectId(meeting_id)},
        {
            "$push": {"recording_events": event},
            "$set": {"status": "recording", "updated_at": datetime.now(timezone.utc).isoformat()}
        }
    )
    return {"message": "Recording started", "timestamp": ts}


@router.post("/{meeting_id}/pause")
async def pause_recording(meeting_id: str, data: RecordingEventRequest, db=Depends(get_db), current_user=Depends(get_current_user)):
    ts = data.timestamp or datetime.now(timezone.utc).isoformat()
    event = {"type": "paused", "timestamp": ts, "user_id": current_user["id"]}
    await db.meetings.update_one(
        {"_id": ObjectId(meeting_id)},
        {
            "$push": {"recording_events": event},
            "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}
        }
    )
    return {"message": "Recording paused", "timestamp": ts}


@router.post("/{meeting_id}/resume")
async def resume_recording(meeting_id: str, data: RecordingEventRequest, db=Depends(get_db), current_user=Depends(get_current_user)):
    ts = data.timestamp or datetime.now(timezone.utc).isoformat()
    event = {"type": "resumed", "timestamp": ts, "user_id": current_user["id"]}

    # Calculate pause duration if pause_start provided
    update_ops = {
        "$push": {"recording_events": event},
        "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}
    }

    if data.pause_start:
        try:
            pause_dt = datetime.fromisoformat(data.pause_start.replace("Z", "+00:00"))
            resume_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            duration = int((resume_dt - pause_dt).total_seconds())
            paused_period = {"paused_at": data.pause_start, "resumed_at": ts, "duration_seconds": duration}
            update_ops["$push"]["paused_periods"] = paused_period
            update_ops["$inc"] = {"total_paused_duration_seconds": duration}
        except Exception:
            pass

    await db.meetings.update_one({"_id": ObjectId(meeting_id)}, update_ops)
    return {"message": "Recording resumed", "timestamp": ts}


@router.post("/{meeting_id}/stop")
async def stop_recording(meeting_id: str, data: RecordingEventRequest, db=Depends(get_db), current_user=Depends(get_current_user)):
    ts = data.timestamp or datetime.now(timezone.utc).isoformat()
    event = {"type": "stopped", "timestamp": ts, "user_id": current_user["id"]}
    await db.meetings.update_one(
        {"_id": ObjectId(meeting_id)},
        {
            "$push": {"recording_events": event},
            "$set": {"status": "stopped", "updated_at": datetime.now(timezone.utc).isoformat()}
        }
    )
    return {"message": "Recording stopped", "timestamp": ts}


@router.get("/{meeting_id}/events")
async def get_events(meeting_id: str, db=Depends(get_db), current_user=Depends(get_current_user)):
    doc = await db.meetings.find_one({"_id": ObjectId(meeting_id)}, {"recording_events": 1, "paused_periods": 1, "total_paused_duration_seconds": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return {
        "recording_events": doc.get("recording_events", []),
        "paused_periods": doc.get("paused_periods", []),
        "total_paused_duration_seconds": doc.get("total_paused_duration_seconds", 0)
    }
