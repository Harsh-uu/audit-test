from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, BackgroundTasks
from bson import ObjectId
from datetime import datetime, timezone
import uuid
import logging
from deps import get_db, get_current_user
from utils.storage import put_object
from utils.ai import transcribe_audio, analyze_meeting

router = APIRouter()
logger = logging.getLogger(__name__)


async def _get_rolled_actions(db, attendee_ids: list, current_meeting_id: str) -> list:
    """Return incomplete actions from previous meetings for these attendees, de-duped."""
    rolled = []
    seen_sources = set()  # (source_meeting_id, action_id) to avoid duplicates
    async for analysis in db.analyses.find({}):
        aid = str(analysis["_id"])
        prev_meeting = await db.meetings.find_one({"analysis_id": aid})
        if not prev_meeting or str(prev_meeting["_id"]) == current_meeting_id:
            continue
        # Attendee overlap check
        prev_attendees = [a.get("user_id") for a in prev_meeting.get("attendees", [])]
        if not any(uid in attendee_ids for uid in prev_attendees):
            continue
        for action in analysis.get("actions", []):
            if action.get("completed") or action.get("is_rolled_over"):
                continue
            key = (str(prev_meeting["_id"]), action.get("id", ""))
            if key in seen_sources:
                continue
            seen_sources.add(key)
            rolled.append({
                **action,
                "id": f"rolled_{str(prev_meeting['_id'])[:6]}_{action.get('id', uuid.uuid4().hex[:6])}",
                "is_rolled_over": True,
                "completed": False,
                "completed_at": None,
                "source_meeting_id": str(prev_meeting["_id"]),
                "source_meeting_title": prev_meeting.get("title", "Previous Meeting"),
            })
    return rolled


async def run_transcription_and_analysis(meeting_id: str, audio_path: str, db):
    """Background task: transcribe audio then run AI analysis"""
    try:
        # Update status
        await db.meetings.update_one(
            {"_id": ObjectId(meeting_id)},
            {"$set": {"status": "transcribing", "updated_at": datetime.now(timezone.utc).isoformat()}}
        )

        # Get audio from storage
        from utils.storage import get_object
        audio_data, _ = get_object(audio_path)

        # Transcribe
        logger.info(f"Starting transcription for meeting {meeting_id}")
        transcript_text = await transcribe_audio(audio_data)
        logger.info(f"Transcription complete for meeting {meeting_id}: {len(transcript_text)} chars")

        # Save transcript
        now = datetime.now(timezone.utc).isoformat()
        transcript_doc = {
            "meeting_id": meeting_id,
            "text": transcript_text,
            "created_at": now,
        }
        t_result = await db.transcripts.insert_one(transcript_doc)
        transcript_id = str(t_result.inserted_id)

        await db.meetings.update_one(
            {"_id": ObjectId(meeting_id)},
            {"$set": {"transcript_id": transcript_id, "status": "analyzing", "updated_at": now}}
        )

        # Get meeting for context
        meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id)})
        paused_periods = meeting.get("paused_periods", [])

        # Load standards
        cqc_standards = await db.standards_entries.find({"type": "cqc", "is_active": True}).to_list(50)
        care_cert_standards = await db.standards_entries.find({"type": "care_cert", "is_active": True}).to_list(20)

        # Load active parsed library documents
        custom_standards = []
        async for doc in db.standards_documents.find({"is_active": True, "parse_status": "parsed"}):
            doc["id"] = str(doc["_id"])
            custom_standards.append(doc)

        # Load supervision template
        supervision_template = None
        tmpl_doc = await db.settings.find_one({"_id": "supervision_template"})
        if tmpl_doc and tmpl_doc.get("steps"):
            supervision_template = tmpl_doc

        # Fetch rolled-over outstanding actions from previous meetings for same attendees
        attendee_ids = [a.get("user_id") for a in meeting.get("attendees", [])]
        rolled_actions = await _get_rolled_actions(db, attendee_ids, meeting_id)

        # Analyze
        logger.info(f"Starting AI analysis for meeting {meeting_id} with {len(custom_standards)} custom docs")
        analysis_result = await analyze_meeting(transcript_text, cqc_standards, care_cert_standards, paused_periods, custom_standards, supervision_template)  # noqa: E501

        # Add status/defaults to each mapping and enrich CQC with key_questions
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

        # Add completed field to new actions + prepend rolled-over actions
        for item in analysis_result.get("actions", []):
            item.setdefault("completed", False)
            item.setdefault("completed_at", None)
            item.setdefault("is_rolled_over", False)
        analysis_result["actions"] = rolled_actions + analysis_result.get("actions", [])

        analysis_doc = {
            "meeting_id": meeting_id,
            **analysis_result,
            "edited_summary": None,
            "created_at": now,
            "last_edited_at": now,
        }
        a_result = await db.analyses.insert_one(analysis_doc)
        analysis_id = str(a_result.inserted_id)

        await db.meetings.update_one(
            {"_id": ObjectId(meeting_id)},
            {"$set": {
                "analysis_id": analysis_id,
                "status": "in_review",
                "updated_at": datetime.now(timezone.utc).isoformat()
            }}
        )
        logger.info(f"Analysis complete for meeting {meeting_id}")

    except Exception as e:
        logger.error(f"Processing failed for meeting {meeting_id}: {e}")
        await db.meetings.update_one(
            {"_id": ObjectId(meeting_id)},
            {"$set": {"status": "processing_failed", "updated_at": datetime.now(timezone.utc).isoformat()}}
        )


@router.post("/{meeting_id}/upload")
async def upload_audio(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Validate meeting exists
    try:
        meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid meeting ID")
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    # Read audio data
    audio_data = await audio.read()
    if len(audio_data) == 0:
        raise HTTPException(status_code=400, detail="Empty audio file")

    file_ext = "webm"
    if audio.filename and "." in audio.filename:
        file_ext = audio.filename.split(".")[-1]

    # Upload to object storage
    storage_path = f"{meeting_id}/audio_{uuid.uuid4()}.{file_ext}"
    try:
        result = put_object(storage_path, audio_data, audio.content_type or "audio/webm")
        actual_path = result.get("path", storage_path)
    except Exception as e:
        logger.error(f"Storage upload failed: {e}")
        # Continue with local path reference
        actual_path = storage_path

    now = datetime.now(timezone.utc).isoformat()
    audio_doc = {
        "meeting_id": meeting_id,
        "storage_path": actual_path,
        "original_filename": audio.filename or "meeting.webm",
        "content_type": audio.content_type or "audio/webm",
        "size_bytes": len(audio_data),
        "upload_status": "uploaded",
        "processing_status": "pending",
        "deletion_status": "active",
        "created_at": now,
        "is_deleted": False,
    }
    af_result = await db.audio_files.insert_one(audio_doc)
    audio_file_id = str(af_result.inserted_id)

    await db.meetings.update_one(
        {"_id": ObjectId(meeting_id)},
        {"$set": {
            "audio_file_id": audio_file_id,
            "status": "processing",
            "updated_at": now,
        }}
    )

    # Start background processing
    background_tasks.add_task(run_transcription_and_analysis, meeting_id, actual_path, db)

    return {
        "message": "Audio uploaded. Processing started.",
        "audio_file_id": audio_file_id,
        "size_bytes": len(audio_data),
    }


@router.post("/{meeting_id}/retry")
async def retry_processing(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Re-trigger transcription + analysis for a processing_failed meeting using stored audio."""
    try:
        meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid meeting ID")
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.get("status") not in ("processing_failed", "processing"):
        raise HTTPException(status_code=400, detail="Only processing_failed meetings can be retried")

    audio_file_id = meeting.get("audio_file_id")
    if not audio_file_id:
        raise HTTPException(status_code=400, detail="No audio file found for this meeting — please re-upload the recording")

    audio_file = await db.audio_files.find_one({"_id": ObjectId(audio_file_id)})
    if not audio_file:
        raise HTTPException(status_code=404, detail="Audio file record not found")

    storage_path = audio_file.get("storage_path")
    if not storage_path:
        raise HTTPException(status_code=400, detail="Audio storage path missing")

    now = datetime.now(timezone.utc).isoformat()
    await db.meetings.update_one(
        {"_id": ObjectId(meeting_id)},
        {"$set": {"status": "processing", "updated_at": now}}
    )
    background_tasks.add_task(run_transcription_and_analysis, meeting_id, storage_path, db)

    return {"message": "Retry started. Processing will resume shortly."}


@router.get("/{meeting_id}/status")
async def get_processing_status(meeting_id: str, db=Depends(get_db), current_user=Depends(get_current_user)):
    try:
        meeting = await db.meetings.find_one(
            {"_id": ObjectId(meeting_id)},
            {"status": 1, "audio_file_id": 1, "transcript_id": 1, "analysis_id": 1, "audio_deletion_status": 1}
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid meeting ID")
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    return {
        "status": meeting.get("status"),
        "has_audio": bool(meeting.get("audio_file_id")),
        "has_transcript": bool(meeting.get("transcript_id")),
        "has_analysis": bool(meeting.get("analysis_id")),
        "audio_deletion_status": meeting.get("audio_deletion_status", "none"),
    }
