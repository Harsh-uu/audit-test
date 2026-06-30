from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional, List
import asyncio
import logging
import re
import uuid
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


class AnonymiseRequest(BaseModel):
    phrase: str

class SpeakerTextUpdateRequest(BaseModel):
    speaker_text: str


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
    doc = await db.meetings.find_one({"_id": ObjectId(meeting_id), "org_id": current_user.get("org_id")})
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
    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id), "org_id": current_user.get("org_id")})
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
    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id), "org_id": current_user.get("org_id")})
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
    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id), "org_id": current_user.get("org_id")})
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    analysis_id = meeting.get("analysis_id")
    if not analysis_id:
        raise HTTPException(status_code=400, detail="No analysis found")

    analysis = await db.analyses.find_one({"_id": ObjectId(analysis_id)})
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    update_data = {}
    for mapping_type in ["cqc_mappings", "care_cert_mappings", "custom_mappings"]:
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
    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id), "org_id": current_user.get("org_id")})
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
    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id), "org_id": current_user.get("org_id")})
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

    now = datetime.now(timezone.utc).isoformat()
    attendees = meeting.get("attendees", [])
    unreviewed_names = [a["name"] for a in attendees if not a.get("reviewed", False)]
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

    return {"message": "Meeting signed off successfully", "signed_at": now, "unreviewed_attendees": unreviewed_names}


@router.patch("/{meeting_id}/actions/{action_id}")
async def toggle_action_complete(meeting_id: str, action_id: str, data: dict, db=Depends(get_db), current_user=Depends(get_current_user)):
    """Mark an action as complete or incomplete."""
    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id)})
    if not meeting or not meeting.get("analysis_id"):
        raise HTTPException(status_code=404, detail="Meeting or analysis not found")
    analysis = await db.analyses.find_one({"_id": ObjectId(meeting["analysis_id"])})
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    completed = bool(data.get("completed", False))
    now = datetime.now(timezone.utc).isoformat()
    actions = analysis.get("actions", [])
    updated = False
    for a in actions:
        if a.get("id") == action_id:
            a["completed"] = completed
            a["completed_at"] = now if completed else None
            updated = True
            break
    if not updated:
        raise HTTPException(status_code=404, detail="Action not found")

    await db.analyses.update_one(
        {"_id": analysis["_id"]},
        {"$set": {"actions": actions}}
    )
    return {"message": "Updated", "completed": completed}


@router.patch("/{meeting_id}/anonymise")
async def anonymise_transcript(
    meeting_id: str,
    data: AnonymiseRequest,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Replace a phrase in the stored transcript with the speaker's first initial."""
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can anonymise transcripts")

    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id), "org_id": current_user.get("org_id")})
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    transcript_id = meeting.get("transcript_id")
    if not transcript_id:
        raise HTTPException(status_code=404, detail="No transcript found for this meeting")

    transcript = await db.transcripts.find_one({"_id": ObjectId(transcript_id)})
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcript not found")

    phrase = data.phrase.strip()
    if not phrase:
        raise HTTPException(status_code=400, detail="Phrase cannot be empty")

    initial = phrase[0].upper() + "."
    original_text = transcript.get("text", "")
    updated_text = re.sub(re.escape(phrase), initial, original_text, flags=re.IGNORECASE)

    if updated_text == original_text:
        return {"message": "Phrase not found in transcript", "replaced": False}

    now = datetime.now(timezone.utc).isoformat()
    await db.transcripts.update_one(
        {"_id": ObjectId(transcript_id)},
        {"$set": {"text": updated_text, "updated_at": now}},
    )
    await db.review_edits.insert_one({
        "meeting_id": meeting_id,
        "editor_id": current_user["id"],
        "editor_name": current_user["name"],
        "edit_type": "transcript_anonymise",
        "content": f"Anonymised '{phrase}' → '{initial}'",
        "created_at": now,
    })
    return {"message": f"'{phrase}' replaced with '{initial}'", "replaced": True}


@router.post("/{meeting_id}/rescan-evidence")
async def rescan_evidence(
    meeting_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Re-run AI compliance mapping using the current (possibly edited) transcript.
    Only regenerates CQC/Care Cert/Custom evidence mappings — preserves summary, actions, and risks."""
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can re-scan evidence")

    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id), "org_id": current_user.get("org_id")})
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if not meeting.get("analysis_id"):
        raise HTTPException(status_code=400, detail="No analysis found — run initial processing first")

    transcript_id = meeting.get("transcript_id")
    if not transcript_id:
        raise HTTPException(status_code=404, detail="No transcript found for this meeting")

    transcript = await db.transcripts.find_one({"_id": ObjectId(transcript_id)})
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcript not found")

    # Use speaker_text (may contain manual text corrections) if available, else plain text
    transcript_text = transcript.get("speaker_text") or transcript.get("text", "")
    if not transcript_text.strip():
        raise HTTPException(status_code=400, detail="Transcript is empty")

    # Load standards (same as initial processing)
    cqc_standards = await db.standards_entries.find({"type": "cqc", "is_active": True}).to_list(50)
    care_cert_standards = await db.standards_entries.find({"type": "care_cert", "is_active": True}).to_list(20)

    custom_standards = []
    async for doc in db.standards_documents.find({"is_active": True, "parse_status": "parsed"}):
        doc["id"] = str(doc["_id"])
        custom_standards.append(doc)

    supervision_template = None
    tmpl_doc = await db.settings.find_one({"_id": "supervision_template"})
    if tmpl_doc and tmpl_doc.get("steps"):
        supervision_template = tmpl_doc

    paused_periods = meeting.get("paused_periods", [])

    from utils.ai import analyze_meeting as _analyze_meeting
    analysis_result = await _analyze_meeting(
        transcript_text, cqc_standards, care_cert_standards, paused_periods, custom_standards, supervision_template
    )

    # Enrich CQC mappings with key_questions from standards data
    cqc_kq_map = {s["reference"]: s.get("key_questions", []) for s in cqc_standards}
    for item in analysis_result.get("cqc_mappings", []):
        item.setdefault("status", "pending")
        item.setdefault("edited_evidence_summary", None)
        item.setdefault("notes", "")
        if not item.get("key_questions"):
            item["key_questions"] = cqc_kq_map.get(item.get("regulation_ref", ""), [])
    for item in analysis_result.get("care_cert_mappings", []):
        item.setdefault("status", "pending")
        item.setdefault("edited_evidence_summary", None)
        item.setdefault("notes", "")
    for item in analysis_result.get("custom_mappings", []):
        item.setdefault("status", "pending")
        item.setdefault("edited_evidence_summary", None)
        item.setdefault("notes", "")

    now = datetime.now(timezone.utc).isoformat()
    analysis_id = meeting["analysis_id"]

    # Only overwrite compliance mappings — summary, edited_summary, actions, risks are preserved
    await db.analyses.update_one(
        {"_id": ObjectId(analysis_id)},
        {"$set": {
            "cqc_mappings": analysis_result.get("cqc_mappings", []),
            "care_cert_mappings": analysis_result.get("care_cert_mappings", []),
            "custom_mappings": analysis_result.get("custom_mappings", []),
            "last_edited_at": now,
            "last_edited_by": current_user["id"],
            "rescanned_at": now,
            "rescanned_by_name": current_user["name"],
        }}
    )

    await db.review_edits.insert_one({
        "meeting_id": meeting_id,
        "editor_id": current_user["id"],
        "editor_name": current_user["name"],
        "edit_type": "evidence_rescan",
        "content": "Compliance evidence re-scanned from corrected transcript",
        "created_at": now,
    })

    updated = await db.analyses.find_one({"_id": ObjectId(analysis_id)})
    if updated:
        updated["id"] = str(updated["_id"])
        del updated["_id"]
    return {"message": "Compliance evidence re-scanned successfully", "analysis": updated}


@router.post("/{meeting_id}/share")
async def share_meeting(meeting_id: str, data: ShareRequest, db=Depends(get_db), current_user=Depends(get_current_user)):
    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id), "org_id": current_user.get("org_id")})
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
    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id), "org_id": current_user.get("org_id")})
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


@router.patch("/{meeting_id}/speaker-text")
async def update_speaker_text(
    meeting_id: str,
    data: SpeakerTextUpdateRequest,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Save corrected speaker turn labels back to the transcript document."""
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can edit speaker labels")

    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id), "org_id": current_user.get("org_id")})
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    transcript_id = meeting.get("transcript_id")
    if not transcript_id:
        raise HTTPException(status_code=404, detail="No transcript found for this meeting")

    now = datetime.now(timezone.utc).isoformat()
    await db.transcripts.update_one(
        {"_id": ObjectId(transcript_id)},
        {"$set": {
            "speaker_text": data.speaker_text,
            "speaker_text_edited_by_name": current_user.get("name", ""),
            "speaker_text_edited_at": now,
        }}
    )

    await db.audit_logs.insert_one({
        "meeting_id": meeting_id,
        "user_id": current_user["id"],
        "user_name": current_user.get("name", ""),
        "action": "speaker_correction",
        "edit_type": "speaker_correction",
        "timestamp": now,
    })

    return {
        "message": "Speaker labels updated",
        "speaker_text": data.speaker_text,
        "edited_by_name": current_user.get("name", ""),
        "edited_at": now,
    }


@router.get("/{meeting_id}/audit-trail")
async def get_audit_trail(meeting_id: str, db=Depends(get_db), current_user=Depends(get_current_user)):
    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id), "org_id": current_user.get("org_id")})
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
    # 2. Recording events — resolve user names from users collection
    rec_user_ids = list({ev.get("user_id") for ev in meeting.get("recording_events", []) if ev.get("user_id")})
    rec_users = {}
    for uid in rec_user_ids:
        try:
            u = await db.users.find_one({"_id": ObjectId(uid)})
            if u:
                rec_users[uid] = u.get("name", "Unknown")
        except Exception:
            pass

    label_map_rec = {
        "notice_acknowledged": "Recording notice acknowledged",
        "started": "Recording started",
        "paused": "Recording paused",
        "resumed": "Recording resumed",
        "stopped": "Recording stopped",
    }
    for ev in meeting.get("recording_events", []):
        ev_type = ev.get("type") or ev.get("event_type", "unknown")
        actor = rec_users.get(ev.get("user_id", ""), ev.get("user_name", "System"))
        events.append({
            "type": f"recording_{ev_type}",
            "label": label_map_rec.get(ev_type, f"Recording {ev_type}"),
            "actor": actor,
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
        "transcript_anonymise": "Transcript anonymised (manual)",
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
    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id), "org_id": current_user.get("org_id")})
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


@router.get("/{meeting_id}/export-pdf")
async def export_pdf(meeting_id: str, include_transcript: bool = False, db=Depends(get_db), current_user=Depends(get_current_user)):
    from fastapi.responses import Response
    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id), "org_id": current_user.get("org_id")})
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.get("status") != "signed_off":
        raise HTTPException(status_code=400, detail="PDF export is only available for signed-off meetings")

    # Gather analysis
    analysis = {}
    if meeting.get("analysis_id"):
        adoc = await db.analyses.find_one({"_id": ObjectId(meeting["analysis_id"])})
        if adoc:
            analysis = adoc

    transcript_text = ""
    speaker_text = ""
    if meeting.get("transcript_id"):
        tdoc = await db.transcripts.find_one({"_id": ObjectId(meeting["transcript_id"])})
        if tdoc:
            # Speaker turns are always included — they reflect manual corrections and are key evidence
            speaker_text = tdoc.get("speaker_text", "")
            # Full plain-text transcript only when explicitly requested
            if include_transcript:
                transcript_text = tdoc.get("text", "")

    pdf_bytes = _generate_pdf(meeting, analysis, transcript_text, speaker_text)
    safe_title = "".join(c for c in meeting.get("title", "report") if c.isalnum() or c in " _-")
    filename = f"supervision_{safe_title[:40].strip().replace(' ', '_')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _generate_pdf(meeting: dict, analysis: dict, transcript_text: str, speaker_text: str = "") -> bytes:
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)

    NAVY = colors.HexColor("#1E3A8A")
    PURPLE_BG = colors.HexColor("#EDE9FE")
    BLUE_BG = colors.HexColor("#EFF6FF")
    TEAL_BG = colors.HexColor("#F0FDF4")
    LIGHT_GRAY = colors.HexColor("#F8FAFC")
    MID_GRAY = colors.HexColor("#6B7280")
    CONFIDENCE_COLORS = {
        "likely_evidence": colors.HexColor("#059669"),
        "needs_review": colors.HexColor("#D97706"),
        "not_enough_evidence": colors.HexColor("#9CA3AF"),
    }

    title_style = ParagraphStyle("Title", fontName="Helvetica-Bold", fontSize=18, textColor=NAVY, spaceAfter=4)
    body_style = ParagraphStyle("Body", fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#374151"), spaceAfter=3, leading=13)
    small_style = ParagraphStyle("Small", fontName="Helvetica", fontSize=8, textColor=MID_GRAY, spaceAfter=2, leading=11)
    mono_style = ParagraphStyle("Mono", fontName="Courier", fontSize=8, textColor=colors.HexColor("#374151"), leading=12, spaceAfter=4)

    def section_header(title, bg=NAVY):
        data = [[Paragraph(f'<font color="white"><b>{title}</b></font>', ParagraphStyle("SH", fontName="Helvetica-Bold", fontSize=10, textColor=colors.white))]]
        t = Table(data, colWidths=[170*mm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
        return t

    def evidence_card(ref, name, badge_text, evidence_summary, excerpt, confidence, bg):
        conf_label = {"likely_evidence": "Likely Evidence", "needs_review": "Needs Review", "not_enough_evidence": "Not Enough Evidence"}.get(confidence, confidence)
        conf_color = CONFIDENCE_COLORS.get(confidence, MID_GRAY)
        rows = [[Paragraph(f'<b>{ref}</b> — {name}', body_style), Paragraph(f'<font color="{conf_color.hexval()}"><b>{conf_label}</b></font>', small_style)]]
        if badge_text:
            rows.append([Paragraph(f'<i>{badge_text}</i>', small_style), ""])
        if evidence_summary:
            rows.append([Paragraph(evidence_summary, small_style), ""])
        if excerpt:
            rows.append([Paragraph(f'<i>"{excerpt}"</i>', small_style), ""])
        t = Table(rows, colWidths=[130*mm, 40*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("SPAN", (0, 1), (1, 1)), ("SPAN", (0, 2), (1, 2)), ("SPAN", (0, 3), (1, 3)),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
        ]))
        return t

    story = []

    # ── Header ──────────────────────────────────────────────────────────
    story.append(Paragraph("Supervision 2.0", ParagraphStyle("App", fontName="Helvetica", fontSize=9, textColor=MID_GRAY)))
    story.append(Paragraph(meeting.get("title", "Meeting Report"), title_style))
    story.append(HRFlowable(width="100%", thickness=2, color=NAVY, spaceAfter=6))

    # Meeting metadata table
    sign_off = meeting.get("sign_off_record", {})
    meta_rows = [
        ["Date", meeting.get("date", "—"), "Status", meeting.get("status", "—").replace("_", " ").title()],
        ["Manager", meeting.get("sign_off_manager_name", "—"), "Signed off by", sign_off.get("signed_by_name", "—")],
        ["Attendees", ", ".join([a.get("name", "") for a in meeting.get("attendees", [])]), "Signed at", sign_off.get("signed_at", "—")[:16] if sign_off.get("signed_at") else "—"],
    ]
    meta_table = Table(meta_rows, colWidths=[28*mm, 57*mm, 28*mm, 57*mm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), MID_GRAY), ("TEXTCOLOR", (2, 0), (2, -1), MID_GRAY),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GRAY), ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
    ]))
    story.append(meta_table)

    # ── Summary ──────────────────────────────────────────────────────────
    story.append(Spacer(1, 6*mm))
    story.append(section_header("Meeting Summary"))
    summary = analysis.get("edited_summary") or analysis.get("summary", "No summary available.")
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(summary, body_style))

    # ── Actions ──────────────────────────────────────────────────────────
    actions = analysis.get("actions", [])
    if actions:
        story.append(Spacer(1, 4*mm))
        story.append(section_header("Action Items"))
        story.append(Spacer(1, 2*mm))
        action_rows = [["#", "Action", "Assigned To", "Due Date"]]
        for i, a in enumerate(actions, 1):
            action_rows.append([str(i), a.get("text", ""), a.get("assigned_to") or "—", a.get("due_date") or "—"])
        at = Table(action_rows, colWidths=[8*mm, 100*mm, 35*mm, 27*mm])
        at.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(at)

    # ── Risks ──────────────────────────────────────────────────────────
    risks = analysis.get("risks", [])
    if risks:
        story.append(Spacer(1, 4*mm))
        story.append(section_header("Risks & Concerns", bg=colors.HexColor("#7F1D1D")))
        story.append(Spacer(1, 2*mm))
        for r in risks:
            sev = r.get("severity", "").upper()
            sev_color = {"HIGH": "#DC2626", "MEDIUM": "#D97706", "LOW": "#6B7280"}.get(sev, "#6B7280")
            story.append(Paragraph(f'<font color="{sev_color}"><b>[{sev}]</b></font> {r.get("text", "")}', body_style))

    # ── CQC Evidence ──────────────────────────────────────────────────────
    cqc_maps = analysis.get("cqc_mappings", [])
    if cqc_maps:
        story.append(Spacer(1, 4*mm))
        story.append(section_header("CQC Regulatory Evidence", bg=colors.HexColor("#4C1D95")))
        story.append(Spacer(1, 2*mm))
        for m in cqc_maps:
            kq = ", ".join(m.get("key_questions", []))
            badge = f"Key Questions: {kq}" if kq else ""
            story.append(evidence_card(m.get("regulation_ref", ""), m.get("regulation_name", ""), badge, m.get("evidence_summary", ""), m.get("transcript_excerpt", ""), m.get("confidence", ""), PURPLE_BG))
            story.append(Spacer(1, 2*mm))

    # ── Care Certificate Evidence ─────────────────────────────────────────
    cc_maps = analysis.get("care_cert_mappings", [])
    if cc_maps:
        story.append(Spacer(1, 4*mm))
        story.append(section_header("Care Certificate Evidence", bg=colors.HexColor("#1E40AF")))
        story.append(Spacer(1, 2*mm))
        for m in cc_maps:
            badge = f"Outcome {m['outcome_ref']}: {m['outcome_name']}" if m.get("outcome_ref") else ""
            story.append(evidence_card(m.get("standard_ref", ""), m.get("standard_name", ""), badge, m.get("evidence_summary", ""), m.get("transcript_excerpt", ""), m.get("confidence", ""), BLUE_BG))
            story.append(Spacer(1, 2*mm))

    # ── Custom / Organisational Evidence ─────────────────────────────────
    custom_maps = analysis.get("custom_mappings", [])
    if custom_maps:
        story.append(Spacer(1, 4*mm))
        story.append(section_header("Organisational Standards Evidence", bg=colors.HexColor("#065F46")))
        story.append(Spacer(1, 2*mm))
        for m in custom_maps:
            badge = m.get("document_name", "")
            story.append(evidence_card(m.get("criterion_ref", ""), m.get("criterion_name", ""), badge, m.get("evidence_summary", ""), m.get("transcript_excerpt", ""), m.get("confidence", ""), TEAL_BG))
            story.append(Spacer(1, 2*mm))

    # ── Transcript (optional) ─────────────────────────────────────────────
    if transcript_text or speaker_text:
        import re as _re
        story.append(Spacer(1, 4*mm))
        story.append(section_header("Meeting Transcript (Anonymised)", bg=colors.HexColor("#374151")))
        story.append(Spacer(1, 2*mm))

        MGMT_NAVY = colors.HexColor("#1E3A8A")
        WORKER_GREEN = colors.HexColor("#065F46")
        label_text_style = ParagraphStyle("LabelTxt", fontName="Helvetica-Bold", fontSize=7, textColor=colors.white, leading=9)
        turn_text_style = ParagraphStyle("TurnTxt", fontName="Helvetica", fontSize=8, textColor=colors.HexColor("#374151"), leading=12)

        if speaker_text:
            story.append(Paragraph("Speaker turns identified by AI. Names replaced with initials where anonymised.", small_style))
            story.append(Spacer(1, 2*mm))

            manager_name = meeting.get("sign_off_manager_name", "")
            manager_words = [w.lower() for w in manager_name.split() if len(w) > 2] if manager_name else []

            # Parse "SPEAKER: text" lines
            turns = []
            for line in speaker_text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                m = _re.match(r'^([^:]{1,50}):\s*(.+)', line)
                if m:
                    turns.append([m.group(1).strip(), m.group(2).strip()])
                elif turns:
                    turns[-1][1] += " " + line
                else:
                    turns.append(["Speaker", line])

            for speaker, text in turns:
                sl = speaker.lower()
                is_manager = (sl in ("manager", "supervisor") or
                              any(w in sl for w in manager_words))
                label_color = MGMT_NAVY if is_manager else WORKER_GREEN
                row = [[Paragraph(speaker.upper(), label_text_style), Paragraph(text, turn_text_style)]]
                t = Table(row, colWidths=[22*mm, 148*mm])
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (0, 0), label_color),
                    ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#F9FAFB")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (0, 0), 4),
                    ("RIGHTPADDING", (0, 0), (0, 0), 4),
                    ("LEFTPADDING", (1, 0), (1, 0), 6),
                    ("RIGHTPADDING", (1, 0), (1, 0), 6),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
                ]))
                story.append(t)
                story.append(Spacer(1, 1*mm))
        else:
            story.append(Paragraph("Names in this transcript have been replaced with initials.", small_style))
            for chunk in transcript_text.split("\n"):
                if chunk.strip():
                    story.append(Paragraph(chunk.strip(), mono_style))

    # ── Footer note ───────────────────────────────────────────────────────
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MID_GRAY))
    from datetime import datetime as _dt
    story.append(Paragraph(f"Generated by Supervision 2.0 on {_dt.now().strftime('%d %b %Y %H:%M')} UTC. This document is confidential.", small_style))

    doc.build(story)
    return buf.getvalue()
