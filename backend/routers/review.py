from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional, List
import asyncio
import logging
from deps import get_db, get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


def doc_to_dict(doc):
    if doc is None:
        return None
    doc = dict(doc)
    doc["id"] = str(doc["_id"])
    del doc["_id"]
    return doc


class UpdateSummaryRequest(BaseModel):
    summary: str


class UpdateActionsRequest(BaseModel):
    actions: List[dict]


class UpdateEvidenceRequest(BaseModel):
    edited_evidence_summary: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None  # accepted|rejected|needs_followup|pending


class ShareRequest(BaseModel):
    user_ids: List[str]


class CommentRequest(BaseModel):
    text: str


class EmailRequest(BaseModel):
    recipients: List[str]
    message: Optional[str] = None


async def delete_audio_after_grace(meeting_id: str, db):
    """Background task: delete audio after 5 minute grace period"""
    await asyncio.sleep(300)  # 5 minutes
    try:
        meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id)})
        if not meeting or meeting.get("status") != "signed_off":
            return

        audio_file_id = meeting.get("audio_file_id")
        if audio_file_id:
            await db.audio_files.update_one(
                {"_id": ObjectId(audio_file_id)},
                {"$set": {"is_deleted": True, "deletion_status": "deleted", "deleted_at": datetime.now(timezone.utc).isoformat()}}
            )

        now = datetime.now(timezone.utc).isoformat()
        await db.meetings.update_one(
            {"_id": ObjectId(meeting_id)},
            {"$set": {
                "audio_deletion_status": "deleted",
                "audio_deleted_at": now,
                "updated_at": now,
            }}
        )
        logger.info(f"Audio deleted for meeting {meeting_id}")
    except Exception as e:
        logger.error(f"Audio deletion failed for meeting {meeting_id}: {e}")


@router.get("/{meeting_id}")
async def get_review_data(meeting_id: str, db=Depends(get_db), current_user=Depends(get_current_user)):
    doc = await db.meetings.find_one({"_id": ObjectId(meeting_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = doc_to_dict(doc)

    if meeting.get("transcript_id"):
        try:
            tdoc = await db.transcripts.find_one({"_id": ObjectId(meeting["transcript_id"])})
            if tdoc:
                meeting["transcript"] = doc_to_dict(tdoc)
        except Exception:
            pass

    if meeting.get("analysis_id"):
        try:
            adoc = await db.analyses.find_one({"_id": ObjectId(meeting["analysis_id"])})
            if adoc:
                meeting["analysis"] = doc_to_dict(adoc)
        except Exception:
            pass

    # Comments
    comments = []
    async for c in db.reviewer_comments.find({"meeting_id": meeting_id}).sort("created_at", 1):
        comments.append(doc_to_dict(c))
    meeting["comments"] = comments

    return meeting


@router.put("/{meeting_id}/summary")
async def update_summary(meeting_id: str, data: UpdateSummaryRequest, db=Depends(get_db), current_user=Depends(get_current_user)):
    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id)})
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.get("status") not in ["in_review", "reviewed"]:
        raise HTTPException(status_code=400, detail="Meeting not in review state")

    analysis_id = meeting.get("analysis_id")
    if not analysis_id:
        raise HTTPException(status_code=400, detail="No analysis found")

    now = datetime.now(timezone.utc).isoformat()
    await db.analyses.update_one(
        {"_id": ObjectId(analysis_id)},
        {"$set": {"edited_summary": data.summary, "last_edited_at": now, "last_edited_by": current_user["id"]}}
    )

    # Log edit
    await db.review_edits.insert_one({
        "meeting_id": meeting_id,
        "editor_id": current_user["id"],
        "editor_name": current_user["name"],
        "edit_type": "summary",
        "content": data.summary,
        "created_at": now,
    })
    return {"message": "Summary updated"}


@router.put("/{meeting_id}/actions")
async def update_actions(meeting_id: str, data: UpdateActionsRequest, db=Depends(get_db), current_user=Depends(get_current_user)):
    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id)})
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.get("status") not in ["in_review", "reviewed"]:
        raise HTTPException(status_code=400, detail="Meeting not in review state")

    analysis_id = meeting.get("analysis_id")
    if not analysis_id:
        raise HTTPException(status_code=400, detail="No analysis found")

    now = datetime.now(timezone.utc).isoformat()
    await db.analyses.update_one(
        {"_id": ObjectId(analysis_id)},
        {"$set": {"actions": data.actions, "last_edited_at": now, "last_edited_by": current_user["id"]}}
    )
    await db.review_edits.insert_one({
        "meeting_id": meeting_id,
        "editor_id": current_user["id"],
        "editor_name": current_user["name"],
        "edit_type": "actions",
        "created_at": now,
    })
    return {"message": "Actions updated"}


@router.put("/{meeting_id}/evidence/{evidence_id}")
async def update_evidence(meeting_id: str, evidence_id: str, data: UpdateEvidenceRequest, db=Depends(get_db), current_user=Depends(get_current_user)):
    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id)})
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    analysis_id = meeting.get("analysis_id")
    if not analysis_id:
        raise HTTPException(status_code=400, detail="No analysis found")

    analysis = await db.analyses.find_one({"_id": ObjectId(analysis_id)})
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    update_data = {}
    for mapping_type in ["cqc_mappings", "care_cert_mappings"]:
        mappings = analysis.get(mapping_type, [])
        for i, m in enumerate(mappings):
            if m.get("id") == evidence_id:
                if data.edited_evidence_summary is not None:
                    mappings[i]["edited_evidence_summary"] = data.edited_evidence_summary
                if data.notes is not None:
                    mappings[i]["notes"] = data.notes
                if data.status is not None:
                    mappings[i]["status"] = data.status
                update_data[mapping_type] = mappings
                break

    if update_data:
        now = datetime.now(timezone.utc).isoformat()
        update_data["last_edited_at"] = now
        update_data["last_edited_by"] = current_user["id"]
        await db.analyses.update_one({"_id": ObjectId(analysis_id)}, {"$set": update_data})

    return {"message": "Evidence updated"}


@router.post("/{meeting_id}/mark-reviewed")
async def mark_reviewed(meeting_id: str, db=Depends(get_db), current_user=Depends(get_current_user)):
    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id)})
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.get("status") not in ["in_review"]:
        raise HTTPException(status_code=400, detail="Meeting not in review state")

    user_id = current_user["id"]
    now = datetime.now(timezone.utc).isoformat()

    # Update attendee reviewed status
    attendees = meeting.get("attendees", [])
    found = False
    for a in attendees:
        if a.get("user_id") == user_id:
            a["reviewed"] = True
            a["reviewed_at"] = now
            found = True
            break

    if not found:
        # Allow the creator to also mark as reviewed
        if meeting.get("created_by") != user_id:
            raise HTTPException(status_code=403, detail="You are not an attendee of this meeting")

    # Check if all attendees reviewed
    all_reviewed = all(a.get("reviewed", False) for a in attendees) if attendees else True
    new_status = "reviewed" if all_reviewed else "in_review"

    await db.meetings.update_one(
        {"_id": ObjectId(meeting_id)},
        {"$set": {"attendees": attendees, "status": new_status, "updated_at": now}}
    )
    return {"message": "Marked as reviewed", "all_reviewed": all_reviewed, "status": new_status}


@router.post("/{meeting_id}/signoff")
async def sign_off(meeting_id: str, background_tasks: BackgroundTasks, db=Depends(get_db), current_user=Depends(get_current_user)):
    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id)})
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    # Must be the assigned manager
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can sign off")

    if meeting.get("sign_off_manager_id") and meeting.get("sign_off_manager_id") != current_user["id"]:
        if current_user["role"] != "admin":
            raise HTTPException(status_code=403, detail="You are not the assigned sign-off manager")

    if meeting.get("status") not in ["reviewed", "in_review"]:
        raise HTTPException(status_code=400, detail="Meeting must be reviewed before sign-off")

    # Check all attendees reviewed (allow sign-off anyway if no attendees)
    attendees = meeting.get("attendees", [])
    unreviewed = [a for a in attendees if not a.get("reviewed", False)]
    if unreviewed:
        raise HTTPException(
            status_code=400,
            detail=f"{len(unreviewed)} attendee(s) have not yet reviewed: {', '.join([a['name'] for a in unreviewed])}"
        )

    now = datetime.now(timezone.utc).isoformat()
    sign_off_record = {
        "signed_by": current_user["id"],
        "signed_by_name": current_user["name"],
        "signed_at": now,
    }
    await db.meetings.update_one(
        {"_id": ObjectId(meeting_id)},
        {"$set": {
            "status": "signed_off",
            "sign_off_record": sign_off_record,
            "audio_deletion_status": "grace_period",
            "audio_grace_period_started_at": now,
            "updated_at": now,
        }}
    )

    # Schedule audio deletion after 5 minutes
    background_tasks.add_task(delete_audio_after_grace, meeting_id, db)

    return {"message": "Meeting signed off successfully", "signed_at": now}


@router.post("/{meeting_id}/share")
async def share_meeting(meeting_id: str, data: ShareRequest, db=Depends(get_db), current_user=Depends(get_current_user)):
    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id)})
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.get("status") not in ["signed_off", "shared"]:
        raise HTTPException(status_code=400, detail="Meeting must be signed off before sharing")

    now = datetime.now(timezone.utc).isoformat()
    shared_with = meeting.get("shared_with", [])
    for uid in data.user_ids:
        if not any(s.get("user_id") == uid for s in shared_with):
            user = await db.users.find_one({"_id": ObjectId(uid)})
            if user:
                shared_with.append({"user_id": uid, "name": user["name"], "email": user["email"], "shared_at": now})

    await db.meetings.update_one(
        {"_id": ObjectId(meeting_id)},
        {"$set": {"status": "shared", "shared_with": shared_with, "updated_at": now}}
    )
    return {"message": "Meeting shared", "shared_with": shared_with}


@router.post("/{meeting_id}/comments")
async def add_comment(meeting_id: str, data: CommentRequest, db=Depends(get_db), current_user=Depends(get_current_user)):
    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id)})
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    # Admins and managers can comment at any stage; others only after sign-off
    role = current_user.get("role")
    if role not in ["admin", "manager"] and meeting.get("status") not in ["signed_off", "shared"]:
        raise HTTPException(status_code=400, detail="Comments are only available after sign-off")

    # Must have at least some processed content to comment on
    if not meeting.get("analysis_id") and role not in ["admin", "manager"]:
        raise HTTPException(status_code=400, detail="Meeting has not been processed yet")

    now = datetime.now(timezone.utc).isoformat()
    comment_doc = {
        "meeting_id": meeting_id,
        "user_id": current_user["id"],
        "user_name": current_user["name"],
        "text": data.text,
        "created_at": now,
    }
    result = await db.reviewer_comments.insert_one(comment_doc)
    comment_doc["id"] = str(result.inserted_id)
    del comment_doc["_id"]
    return comment_doc


@router.get("/{meeting_id}/audit-trail")
async def get_audit_trail(meeting_id: str, db=Depends(get_db), current_user=Depends(get_current_user)):
    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id)})
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    events = []

    # 1. Meeting created
    if meeting.get("created_at"):
        events.append({
            "type": "meeting_created",
            "label": "Meeting created",
            "actor": meeting.get("created_by_name", "Unknown"),
            "timestamp": meeting["created_at"],
            "detail": meeting.get("title", ""),
        })

    # 2. Recording events
    label_map_rec = {
        "notice_acknowledged": "Recording notice acknowledged",
        "started": "Recording started",
        "paused": "Recording paused",
        "resumed": "Recording resumed",
        "stopped": "Recording stopped",
    }
    for ev in meeting.get("recording_events", []):
        ev_type = ev.get("event_type", "unknown")
        events.append({
            "type": f"recording_{ev_type}",
            "label": label_map_rec.get(ev_type, f"Recording {ev_type}"),
            "actor": ev.get("user_name", "System"),
            "timestamp": ev.get("timestamp", ""),
            "detail": None,
        })

    # 3. Transcript created
    if meeting.get("transcript_id"):
        try:
            tdoc = await db.transcripts.find_one({"_id": ObjectId(meeting["transcript_id"])})
            if tdoc and tdoc.get("created_at"):
                events.append({
                    "type": "transcribed",
                    "label": "Audio transcribed",
                    "actor": "System (Whisper)",
                    "timestamp": tdoc["created_at"],
                    "detail": None,
                })
        except Exception:
            pass

    # 4. Analysis completed
    if meeting.get("analysis_id"):
        try:
            adoc = await db.analyses.find_one({"_id": ObjectId(meeting["analysis_id"])})
            if adoc and adoc.get("created_at"):
                events.append({
                    "type": "analyzed",
                    "label": "AI analysis completed",
                    "actor": "System (GPT-4o)",
                    "timestamp": adoc["created_at"],
                    "detail": None,
                })
        except Exception:
            pass

    # 5. Review edits
    label_map_edit = {
        "summary": "Summary edited",
        "actions": "Action items updated",
        "evidence": "Evidence item updated",
    }
    async for edit in db.review_edits.find({"meeting_id": meeting_id}).sort("created_at", 1):
        edit_type = edit.get("edit_type", "unknown")
        events.append({
            "type": f"edit_{edit_type}",
            "label": label_map_edit.get(edit_type, f"'{edit_type}' edited"),
            "actor": edit.get("editor_name", "Unknown"),
            "timestamp": edit.get("created_at", ""),
            "detail": None,
        })

    # 6. Attendees marked as reviewed
    for a in meeting.get("attendees", []):
        if a.get("reviewed") and a.get("reviewed_at"):
            events.append({
                "type": "mark_reviewed",
                "label": "Marked as reviewed",
                "actor": a.get("name", "Unknown"),
                "timestamp": a["reviewed_at"],
                "detail": None,
            })

    # 7. Sign-off
    sign_off = meeting.get("sign_off_record")
    if sign_off:
        events.append({
            "type": "signed_off",
            "label": "Meeting signed off",
            "actor": sign_off.get("signed_by_name", "Unknown"),
            "timestamp": sign_off.get("signed_at", ""),
            "detail": None,
        })

    # 8. Comments
    async for c in db.reviewer_comments.find({"meeting_id": meeting_id}).sort("created_at", 1):
        text = c.get("text", "")
        events.append({
            "type": "comment_added",
            "label": "Comment added",
            "actor": c.get("user_name", "Unknown"),
            "timestamp": c.get("created_at", ""),
            "detail": text[:100] + ("…" if len(text) > 100 else ""),
        })

    # 9. Audio deleted
    if meeting.get("audio_deletion_status") == "deleted" and meeting.get("audio_deleted_at"):
        events.append({
            "type": "audio_deleted",
            "label": "Raw audio deleted (GDPR)",
            "actor": "System",
            "timestamp": meeting["audio_deleted_at"],
            "detail": "Audio file removed after sign-off grace period",
        })

    events.sort(key=lambda e: e.get("timestamp") or "")
    return {"events": events}


@router.get("/{meeting_id}/comments")
async def get_comments(meeting_id: str, db=Depends(get_db), current_user=Depends(get_current_user)):
    comments = []
    async for c in db.reviewer_comments.find({"meeting_id": meeting_id}).sort("created_at", 1):
        comments.append(doc_to_dict(c))
    return comments


@router.post("/{meeting_id}/send-email")
async def send_email_report(meeting_id: str, data: EmailRequest, db=Depends(get_db), current_user=Depends(get_current_user)):
    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id)})
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.get("status") not in ["signed_off", "shared"]:
        raise HTTPException(status_code=400, detail="Meeting must be signed off")

    try:
        import resend
        import os
        resend.api_key = os.environ.get("RESEND_API_KEY", "")

        backend_url = os.environ.get("FRONTEND_URL", "")
        html = f"""
<html><body style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
<h2 style="color: #1E3A8A;">Supervision Meeting Report</h2>
<p><strong>Meeting:</strong> {meeting.get('title')}</p>
<p><strong>Date:</strong> {meeting.get('date')}</p>
<p><strong>Status:</strong> Signed Off</p>
<p>{data.message or 'Please review the meeting report linked below.'}</p>
<p><a href="{backend_url}/meetings/{meeting_id}/report" style="background:#1E3A8A;color:white;padding:10px 20px;text-decoration:none;border-radius:4px;">View Report</a></p>
<hr/>
<p style="color:#666;font-size:12px;">Supervision 2.0 - Compliance Evidence Platform</p>
</body></html>"""

        import asyncio
        params = {
            "from": os.environ.get("SENDER_EMAIL", "onboarding@resend.dev"),
            "to": data.recipients,
            "subject": f"Meeting Report: {meeting.get('title')}",
            "html": html,
        }
        await asyncio.to_thread(resend.Emails.send, params)
        return {"message": f"Email sent to {len(data.recipients)} recipient(s)"}
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return {"message": "Email sending requires Resend API key configuration", "error": str(e)}
