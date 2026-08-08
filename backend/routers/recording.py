import json
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from datetime import datetime, timezone
from typing import Optional
from deps import get_db, get_current_user
import database

router = APIRouter()


class RecordingEventRequest(BaseModel):
    timestamp: Optional[str] = None
    pause_start: Optional[str] = None


@router.post("/{meeting_id}/notice")
async def log_notice(meeting_id: str, current_user=Depends(get_current_user)):
    now = datetime.now(timezone.utc).isoformat()
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        await conn.execute(
            "UPDATE meetings SET recording_notice_shown_at=$1, updated_at=$1 WHERE id=$2",
            now, meeting_id,
        )
    return {"message": "Notice logged", "timestamp": now}


@router.post("/{meeting_id}/start")
async def start_recording(meeting_id: str, request: Request, current_user=Depends(get_current_user)):
    try:
        body = await request.json()
        data = RecordingEventRequest(**body)
    except Exception:
        data = RecordingEventRequest()
    ts = data.timestamp or datetime.now(timezone.utc).isoformat()
    event = {"type": "started", "timestamp": ts, "user_id": current_user["id"]}
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        await conn.execute(
            """UPDATE meetings
               SET recording_events = recording_events || $1::jsonb,
                   status = 'recording',
                   updated_at = $2
               WHERE id = $3""",
            json.dumps([event]), datetime.now(timezone.utc).isoformat(), meeting_id,
        )
    return {"message": "Recording started", "timestamp": ts}


@router.post("/{meeting_id}/pause")
async def pause_recording(meeting_id: str, request: Request, current_user=Depends(get_current_user)):
    try:
        body = await request.json()
        data = RecordingEventRequest(**body)
    except Exception:
        data = RecordingEventRequest()
    ts = data.timestamp or datetime.now(timezone.utc).isoformat()
    event = {"type": "paused", "timestamp": ts, "user_id": current_user["id"]}
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        await conn.execute(
            """UPDATE meetings
               SET recording_events = recording_events || $1::jsonb,
                   updated_at = $2
               WHERE id = $3""",
            json.dumps([event]), datetime.now(timezone.utc).isoformat(), meeting_id,
        )
    return {"message": "Recording paused", "timestamp": ts}


@router.post("/{meeting_id}/resume")
async def resume_recording(meeting_id: str, request: Request, current_user=Depends(get_current_user)):
    try:
        body = await request.json()
        data = RecordingEventRequest(**body)
    except Exception:
        data = RecordingEventRequest()
    ts = data.timestamp or datetime.now(timezone.utc).isoformat()
    event = {"type": "resumed", "timestamp": ts, "user_id": current_user["id"]}
    org_id = current_user.get("org_id", "")
    now = datetime.now(timezone.utc).isoformat()

    async with database.with_org(org_id) as conn:
        if data.pause_start:
            try:
                pause_dt = datetime.fromisoformat(data.pause_start.replace("Z", "+00:00"))
                resume_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                duration = int((resume_dt - pause_dt).total_seconds())
                paused_period = {"paused_at": data.pause_start, "resumed_at": ts, "duration_seconds": duration}
                await conn.execute(
                    """UPDATE meetings
                       SET recording_events = recording_events || $1::jsonb,
                           paused_periods = paused_periods || $2::jsonb,
                           total_paused_duration_seconds = total_paused_duration_seconds + $3,
                           updated_at = $4
                       WHERE id = $5""",
                    json.dumps([event]), json.dumps([paused_period]), duration, now, meeting_id,
                )
            except Exception:
                await conn.execute(
                    "UPDATE meetings SET recording_events = recording_events || $1::jsonb, updated_at=$2 WHERE id=$3",
                    json.dumps([event]), now, meeting_id,
                )
        else:
            await conn.execute(
                "UPDATE meetings SET recording_events = recording_events || $1::jsonb, updated_at=$2 WHERE id=$3",
                json.dumps([event]), now, meeting_id,
            )
    return {"message": "Recording resumed", "timestamp": ts}


@router.post("/{meeting_id}/stop")
async def stop_recording(meeting_id: str, request: Request, current_user=Depends(get_current_user)):
    try:
        body = await request.json()
        data = RecordingEventRequest(**body)
    except Exception:
        data = RecordingEventRequest()
    ts = data.timestamp or datetime.now(timezone.utc).isoformat()
    event = {"type": "stopped", "timestamp": ts, "user_id": current_user["id"]}
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        await conn.execute(
            """UPDATE meetings
               SET recording_events = recording_events || $1::jsonb,
                   status = 'stopped',
                   updated_at = $2
               WHERE id = $3""",
            json.dumps([event]), datetime.now(timezone.utc).isoformat(), meeting_id,
        )
    return {"message": "Recording stopped", "timestamp": ts}


@router.get("/{meeting_id}/events")
async def get_events(meeting_id: str, current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        row = await conn.fetchrow(
            "SELECT recording_events, paused_periods, total_paused_duration_seconds FROM meetings WHERE id=$1",
            meeting_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return {
        "recording_events": row["recording_events"] if isinstance(row["recording_events"], list) else (json.loads(row["recording_events"]) if isinstance(row["recording_events"], str) else []),
        "paused_periods": row["paused_periods"] if isinstance(row["paused_periods"], list) else (json.loads(row["paused_periods"]) if isinstance(row["paused_periods"], str) else []),
        "total_paused_duration_seconds": row["total_paused_duration_seconds"] or 0,
    }
