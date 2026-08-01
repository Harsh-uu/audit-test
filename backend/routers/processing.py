from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
from bson import ObjectId
from datetime import datetime, timezone
import asyncio
import uuid
import logging
import os
from deps import get_db, get_current_user
from utils.storage import put_object
from utils.ai import transcribe_audio, analyze_meeting, diarize_transcript, transcribe_with_assemblyai, map_speaker_numbers_to_names
from utils.job_worker import enqueue_job

router = APIRouter()
logger = logging.getLogger(__name__)


async def _get_rolled_actions(db, attendee_ids: list, current_meeting_id: str, manager_id: str = None, attendee_names: list = None) -> list:
    """Return incomplete actions from previous meetings that are relevant to these supervisees.

    Rules:
    1. Only match on SUPERVISEE user IDs — the manager (sign_off_manager_id) is excluded from
       the lookup so they don't accidentally link unrelated meetings together.
    2. An action is rolled over only if:
       - Its assigned_to name matches (case-insensitive) an attendee name in the new meeting, OR
       - It has no assigned_to (general meeting action) AND the source meeting's supervisees
         overlap with the new meeting's supervisees.
    3. Already-completed and already-rolled-over actions are skipped.
    """
    if not attendee_ids:
        return []

    # Exclude the manager from the match — only supervisee overlap drives rollover
    supervisee_ids = [uid for uid in attendee_ids if uid and uid != manager_id]
    if not supervisee_ids:
        return []

    # Attendee names for assigned_to matching (lowercase for case-insensitive compare)
    new_attendee_names_lower = {n.lower() for n in (attendee_names or []) if n}

    rolled = []
    seen_sources = set()

    prev_meetings_cursor = db.meetings.find(
        {
            "attendees.user_id": {"$in": supervisee_ids},
            "analysis_id": {"$exists": True, "$ne": None},
        },
        {"_id": 1, "attendees": 1, "analysis_id": 1, "title": 1, "sign_off_manager_id": 1}
    ).limit(50)

    async for prev_meeting in prev_meetings_cursor:
        if str(prev_meeting["_id"]) == current_meeting_id:
            continue
        analysis_id = prev_meeting.get("analysis_id")
        if not analysis_id:
            continue

        # Build supervisee IDs for the SOURCE meeting (exclude its own manager)
        source_manager_id = prev_meeting.get("sign_off_manager_id")
        source_supervisee_ids = {
            a.get("user_id")
            for a in prev_meeting.get("attendees", [])
            if a.get("user_id") and a.get("user_id") != source_manager_id
        }
        # Only proceed if at least one supervisee genuinely overlaps
        if not source_supervisee_ids.intersection(set(supervisee_ids)):
            continue

        analysis = await db.analyses.find_one(
            {"_id": ObjectId(analysis_id)},
            {"actions": 1}
        )
        if not analysis:
            continue

        for action in analysis.get("actions", []):
            if action.get("completed") or action.get("is_rolled_over"):
                continue
            key = (str(prev_meeting["_id"]), action.get("id", ""))
            if key in seen_sources:
                continue

            # Gate: if action is assigned to a specific person, they must be in the new meeting
            assigned = (action.get("assigned_to") or "").strip().lower()
            if assigned and new_attendee_names_lower and assigned not in new_attendee_names_lower:
                continue  # Action belongs to someone not in this meeting — skip it

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

        # Fetch meeting for attendee count (speaker hint) and metadata used later
        meeting_doc = await db.meetings.find_one({"_id": ObjectId(meeting_id)})
        attendee_count = len((meeting_doc or {}).get("attendees", [])) or None

        # Get audio from storage
        from utils.storage import get_object
        audio_data, _ = get_object(audio_path)

        # ── Transcription + diarization ─────────────────────────────────────
        # AssemblyAI medical (universal-3-pro + domain=medical-v1) is primary.
        # Falls back to Whisper only if AssemblyAI fails entirely.
        # Deepgram has been removed — unreliable on mono browser audio.
        logger.info(f"Starting transcription for meeting {meeting_id}")
        assemblyai_key = os.environ.get("ASSEMBLYAI_API_KEY")
        numbered_speaker_text = None
        transcript_warnings = []

        if assemblyai_key:
            try:
                logger.info("Attempting AssemblyAI medical transcription + diarization")
                transcript_text, numbered_speaker_text, transcript_warnings = await transcribe_with_assemblyai(
                    audio_data, speakers_expected=attendee_count
                )
            except Exception as aai_err:
                logger.warning(f"AssemblyAI failed ({aai_err}), falling back to Whisper")
                transcript_text = await transcribe_audio(audio_data)
                numbered_speaker_text = None
        else:
            logger.info("No ASSEMBLYAI_API_KEY — using Whisper")
            transcript_text = await transcribe_audio(audio_data)

        logger.info(f"Transcription complete for meeting {meeting_id}: {len(transcript_text)} chars")

        # Save transcript (include safety warnings for the review gate)
        now = datetime.now(timezone.utc).isoformat()
        transcript_doc = {
            "meeting_id": meeting_id,
            "text": transcript_text,
            "created_at": now,
            "safety_warnings": transcript_warnings,
        }
        t_result = await db.transcripts.insert_one(transcript_doc)
        transcript_id = str(t_result.inserted_id)

        await db.meetings.update_one(
            {"_id": ObjectId(meeting_id)},
            {"$set": {
                "transcript_id": transcript_id,
                "status": "analyzing",
                "updated_at": now,
                "transcript_has_warnings": len(transcript_warnings) > 0,
            }}
        )

        # Get meeting for context
        meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id)})
        paused_periods = meeting.get("paused_periods", [])
        meeting_org_id = meeting.get("org_id")

        # Load standards — system-wide plus this org's custom entries
        _std_filter = lambda t: {"type": t, "is_active": True, "$or": [{"is_system": True}, {"org_id": meeting_org_id}]}
        cqc_standards = await db.standards_entries.find(_std_filter("cqc")).to_list(50)
        care_cert_standards = await db.standards_entries.find(_std_filter("care_cert")).to_list(20)

        # Load active parsed library documents — scoped to this org only
        custom_standards = []
        std_doc_query = {"is_active": True, "parse_status": "parsed"}
        if meeting_org_id:
            std_doc_query["org_id"] = meeting_org_id
        async for doc in db.standards_documents.find(std_doc_query):
            doc["id"] = str(doc["_id"])
            custom_standards.append(doc)

        # Load supervision template — org-scoped, with fallback to legacy global record
        supervision_template = None
        meeting_org_id = meeting.get("org_id")
        tmpl_doc = await db.settings.find_one({"_id": f"supervision_template:{meeting_org_id}"}) if meeting_org_id else None
        if not tmpl_doc:
            tmpl_doc = await db.settings.find_one({"_id": "supervision_template"})
        if tmpl_doc and tmpl_doc.get("steps"):
            supervision_template = tmpl_doc

        # Fetch rolled-over outstanding actions from previous meetings for same supervisees
        attendee_ids = [a.get("user_id") for a in meeting.get("attendees", [])]
        attendee_names = [a.get("name") for a in meeting.get("attendees", [])]
        manager_id = meeting.get("sign_off_manager_id")
        rolled_actions = await _get_rolled_actions(db, attendee_ids, meeting_id, manager_id=manager_id, attendee_names=attendee_names)

        # Run analysis + speaker diarization in parallel
        manager_name = meeting.get("sign_off_manager_name") or "Manager"
        attendees = meeting.get("attendees", [])
        attendee_names = [a.get("name") for a in attendees if a.get("name")]
        meeting_type = (meeting.get("meeting_type") or "supervision").replace("_", " ").title()

        logger.info(f"Starting AI analysis + speaker labelling for meeting {meeting_id}")

        # Route diarization: if Deepgram found multiple speakers acoustically, GPT-4o
        # only needs to map Speaker 0/1/2 → real names (easier, more reliable).
        # Otherwise GPT-4o reads the full text and infers speaker turns itself.
        if numbered_speaker_text:
            diarize_coro = map_speaker_numbers_to_names(numbered_speaker_text, manager_name, attendee_names, meeting_type)
        else:
            diarize_coro = diarize_transcript(transcript_text, manager_name, attendee_names, meeting_type)

        results = await asyncio.gather(
            analyze_meeting(transcript_text, cqc_standards, care_cert_standards, paused_periods, custom_standards, supervision_template),
            diarize_coro,
            return_exceptions=True,
        )
        analysis_result = results[0]
        speaker_text = results[1]

        if isinstance(analysis_result, Exception):
            raise analysis_result
        if isinstance(speaker_text, Exception) or not speaker_text:
            logger.warning(f"Diarization non-fatal failure for meeting {meeting_id}: {speaker_text}")
            speaker_text = None
        else:
            await db.transcripts.update_one(
                {"_id": t_result.inserted_id},
                {"$set": {"speaker_text": speaker_text}}
            )
            logger.info(f"Speaker diarization saved for meeting {meeting_id}")

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

        # Add id + completed field to new actions + prepend rolled-over actions
        for item in analysis_result.get("actions", []):
            if not item.get("id"):
                item["id"] = f"action_{uuid.uuid4().hex[:12]}"
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

        # Phase 4: run prep coverage check if a prep agenda exists for this meeting
        try:
            prep_record = await db.meeting_prep.find_one({"meeting_id": meeting_id})
            if prep_record and prep_record.get("sections"):
                from utils.ai import check_prep_coverage
                # Collect all included questions across all sections
                all_questions = []
                for section in prep_record["sections"]:
                    for q in section.get("questions", []):
                        if q.get("included", True) and q.get("text"):
                            all_questions.append({"id": q["id"], "text": q["text"]})
                if all_questions:
                    coverage = await check_prep_coverage(transcript_text, all_questions)
                    await db.meeting_prep.update_one(
                        {"meeting_id": meeting_id},
                        {"$set": {"coverage_results": coverage.get("results", {}), "coverage_checked_at": coverage.get("checked_at")}}
                    )
                    logger.info(f"Prep coverage check saved for meeting {meeting_id}: {len(coverage.get('results', {}))} questions assessed")
        except Exception as cov_exc:
            logger.warning(f"Prep coverage check non-fatal failure for {meeting_id}: {cov_exc}")

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
    request: Request,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Validate meeting exists and belongs to this org
    try:
        meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id), "org_id": current_user.get("org_id")})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid meeting ID")
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    # Read raw audio bytes (sent as application/octet-stream)
    audio_data = await request.body()
    if not audio_data:
        raise HTTPException(status_code=400, detail="Empty audio body")

    content_type = request.headers.get("content-type", "audio/webm").split(";")[0].strip()
    file_ext = "webm"

    # Upload to object storage
    storage_path = f"{meeting_id}/audio_{uuid.uuid4()}.{file_ext}"
    try:
        result = put_object(storage_path, audio_data, content_type)
        actual_path = result.get("path", storage_path)
    except Exception as e:
        logger.error(f"Storage upload failed: {e}")
        actual_path = storage_path

    now = datetime.now(timezone.utc).isoformat()
    audio_doc = {
        "meeting_id": meeting_id,
        "storage_path": actual_path,
        "original_filename": "meeting.webm",
        "content_type": content_type,
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

    # Enqueue to persistent MongoDB job queue (survives server restarts, auto-retries)
    await enqueue_job(db, meeting_id, actual_path)

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
        meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id), "org_id": current_user.get("org_id")})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid meeting ID")
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.get("status") not in ("processing_failed", "processing", "in_review", "reviewed"):
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
    await enqueue_job(db, meeting_id, storage_path)

    return {"message": "Retry started. Processing will resume shortly."}


async def _run_diarization_background(meeting_id: str, transcript_id: str, transcript_text: str,
                                      manager_name: str, attendee_names: list, meeting_type: str, db):
    """Run GPT-4o speaker diarization in the background and persist the result."""
    try:
        speaker_text = await diarize_transcript(transcript_text, manager_name, attendee_names, meeting_type)
        if speaker_text:
            await db.transcripts.update_one(
                {"_id": ObjectId(transcript_id)},
                {"$set": {"speaker_text": speaker_text}}
            )
            await db.meetings.update_one(
                {"_id": ObjectId(meeting_id)},
                {"$set": {"diarize_status": "done"}}
            )
            logger.info(f"Background diarization complete for meeting {meeting_id}")
        else:
            await db.meetings.update_one(
                {"_id": ObjectId(meeting_id)},
                {"$set": {"diarize_status": "failed"}}
            )
    except Exception as e:
        logger.error(f"Background diarization failed for meeting {meeting_id}: {e}")
        await db.meetings.update_one(
            {"_id": ObjectId(meeting_id)},
            {"$set": {"diarize_status": "failed"}}
        )


@router.post("/{meeting_id}/diarize")
async def diarize_meeting_transcript(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Start speaker identification as a background task — returns immediately."""
    try:
        meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id), "org_id": current_user.get("org_id")})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid meeting ID")
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    transcript_id = meeting.get("transcript_id")
    if not transcript_id:
        raise HTTPException(status_code=400, detail="No transcript found for this meeting")

    transcript = await db.transcripts.find_one({"_id": ObjectId(transcript_id)})
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcript not found")

    transcript_text = transcript.get("text", "")
    if not transcript_text:
        raise HTTPException(status_code=400, detail="Transcript text is empty")

    manager_name = meeting.get("sign_off_manager_name") or "Manager"
    attendees = meeting.get("attendees", [])
    attendee_names = [a.get("name") for a in attendees if a.get("name")]
    meeting_type = (meeting.get("meeting_type") or "supervision").replace("_", " ").title()

    # Mark as processing immediately so the frontend can start polling
    await db.meetings.update_one(
        {"_id": ObjectId(meeting_id)},
        {"$set": {"diarize_status": "processing"}}
    )

    background_tasks.add_task(
        _run_diarization_background,
        meeting_id, transcript_id, transcript_text,
        manager_name, attendee_names, meeting_type, db
    )

    return {"status": "processing", "message": "Speaker identification started — this may take 1–2 minutes for long transcripts"}


@router.get("/{meeting_id}/status")
async def get_processing_status(meeting_id: str, db=Depends(get_db), current_user=Depends(get_current_user)):
    try:
        meeting = await db.meetings.find_one(
            {"_id": ObjectId(meeting_id), "org_id": current_user.get("org_id")},
            {"status": 1, "audio_file_id": 1, "transcript_id": 1, "analysis_id": 1, "audio_deletion_status": 1, "diarize_status": 1}
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid meeting ID")
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    return {
        "status": meeting.get("status"),
        "diarize_status": meeting.get("diarize_status"),
        "has_audio": bool(meeting.get("audio_file_id")),
        "has_transcript": bool(meeting.get("transcript_id")),
        "has_analysis": bool(meeting.get("analysis_id")),
        "audio_deletion_status": meeting.get("audio_deletion_status", "none"),
    }


@router.post("/{meeting_id}/retranscribe")
async def retranscribe_meeting(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Re-submit audio to AssemblyAI with speakers_expected hint.
    Only updates the speaker/transcript track — does NOT touch meeting status, analysis, or sign-off.
    Manager/admin only. Requires the original audio to still be in storage.
    """
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Manager or admin required")

    try:
        meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id), "org_id": current_user.get("org_id")})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid meeting ID")
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    audio_file_id = meeting.get("audio_file_id")
    if not audio_file_id:
        raise HTTPException(status_code=400, detail="No audio file associated with this meeting — cannot retranscribe")

    audio_file = await db.audio_files.find_one({"_id": ObjectId(audio_file_id)})
    if not audio_file or not audio_file.get("storage_path"):
        raise HTTPException(status_code=404, detail="Audio file record not found")

    transcript_id = meeting.get("transcript_id")
    if not transcript_id:
        raise HTTPException(status_code=400, detail="No transcript record found — use retry instead")

    await db.meetings.update_one(
        {"_id": ObjectId(meeting_id)},
        {"$set": {"diarize_status": "processing"}}
    )

    background_tasks.add_task(
        _run_retranscribe_background,
        meeting_id, transcript_id, audio_file["storage_path"], meeting, db
    )

    return {"status": "processing", "message": "Re-scanning audio with AssemblyAI — this takes 1–3 minutes. Refresh the transcript tab when done."}


async def _run_retranscribe_background(meeting_id: str, transcript_id: str, storage_path: str, meeting: dict, db):
    """Re-submit audio to AssemblyAI with speakers_expected, then remap names. Leaves all other meeting data unchanged."""
    from utils.storage import get_object
    try:
        audio_data, _ = get_object(storage_path)
    except Exception as e:
        logger.error(f"Retranscribe: could not load audio for {meeting_id}: {e}")
        await db.meetings.update_one({"_id": ObjectId(meeting_id)}, {"$set": {"diarize_status": "failed"}})
        return

    assemblyai_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not assemblyai_key:
        logger.error("Retranscribe: ASSEMBLYAI_API_KEY not set")
        await db.meetings.update_one({"_id": ObjectId(meeting_id)}, {"$set": {"diarize_status": "failed"}})
        return

    attendee_count = len(meeting.get("attendees", [])) or None
    try:
        plain_text, numbered_speaker_text, _ = await transcribe_with_assemblyai(audio_data, speakers_expected=attendee_count)
    except Exception as e:
        logger.error(f"Retranscribe: AssemblyAI failed for {meeting_id}: {e}")
        await db.meetings.update_one({"_id": ObjectId(meeting_id)}, {"$set": {"diarize_status": "failed"}})
        return

    manager_name   = meeting.get("sign_off_manager_name") or "Manager"
    attendees      = meeting.get("attendees", [])
    attendee_names = [a.get("name") for a in attendees if a.get("name")]
    meeting_type   = (meeting.get("meeting_type") or "supervision").replace("_", " ").title()

    if numbered_speaker_text:
        speaker_text = await map_speaker_numbers_to_names(numbered_speaker_text, manager_name, attendee_names, meeting_type)
    else:
        speaker_text = await diarize_transcript(plain_text, manager_name, attendee_names, meeting_type)

    if not speaker_text:
        logger.warning(f"Retranscribe: diarization returned nothing for {meeting_id}")
        await db.meetings.update_one({"_id": ObjectId(meeting_id)}, {"$set": {"diarize_status": "failed"}})
        return

    now = datetime.now(timezone.utc).isoformat()
    await db.transcripts.update_one(
        {"_id": ObjectId(transcript_id)},
        {"$set": {"text": plain_text, "speaker_text": speaker_text, "retranscribed_at": now}}
    )
    await db.meetings.update_one(
        {"_id": ObjectId(meeting_id)},
        {"$set": {"diarize_status": "done", "retranscribed_at": now}}
    )
    logger.info(f"Retranscribe complete for meeting {meeting_id} — speakers_expected={attendee_count}")
