from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
from datetime import datetime, timezone
import asyncio
import json
import uuid
import logging
import os
from deps import get_current_user
from utils.supabase_storage import put_audio, get_audio
from utils.ai import analyze_meeting, diarize_transcript, transcribe_with_assemblyai, map_speaker_numbers_to_names
from utils.job_worker import enqueue_job
import database

router = APIRouter()
logger = logging.getLogger(__name__)


def _jlist(val):
    """Parse a JSONB value that asyncpg may return as a raw string when RLS role is active."""
    if isinstance(val, list): return val
    if isinstance(val, str):
        try: return json.loads(val)
        except Exception: return []
    return val or []


def _parse_std_row(r) -> dict:
    """Normalize standards_entries JSONB columns (sub_outcomes, key_questions, keywords)."""
    s = dict(r)
    for f in ("sub_outcomes", "key_questions", "keywords"):
        s[f] = _jlist(s.get(f))
    return s


def _jdict(val):
    """Parse a JSONB value that asyncpg may return as a raw string; returns a dict."""
    if isinstance(val, dict): return val
    if isinstance(val, str):
        try: return json.loads(val)
        except Exception: return {}
    return val or {}


async def _get_rolled_actions(conn, supervisee_ids: list, current_meeting_id: str, manager_id: str = None, attendee_names: list = None) -> list:
    """Return incomplete actions from previous meetings relevant to these supervisees."""
    if not supervisee_ids:
        return []
    supervisee_ids = [uid for uid in supervisee_ids if uid and uid != manager_id]
    if not supervisee_ids:
        return []

    new_attendee_names_lower = {n.lower() for n in (attendee_names or []) if n}
    rolled = []
    seen_sources = set()

    prev_rows = await conn.fetch(
        """SELECT id, attendees, analysis_id, title, sign_off_manager_id
           FROM meetings
           WHERE analysis_id IS NOT NULL
             AND id != $1
             AND EXISTS (
                 SELECT 1 FROM jsonb_array_elements(attendees) elem
                 WHERE elem->>'user_id' = ANY($2::text[])
             )
           LIMIT 50""",
        current_meeting_id, supervisee_ids,
    )

    for prev in prev_rows:
        prev = dict(prev)
        source_manager_id = prev.get("sign_off_manager_id")
        source_supervisee_ids = {
            a.get("user_id")
            for a in _jlist(prev.get("attendees"))
            if a.get("user_id") and a.get("user_id") != source_manager_id
        }
        if not source_supervisee_ids.intersection(set(supervisee_ids)):
            continue

        analysis_row = await conn.fetchrow(
            "SELECT actions FROM analyses WHERE id = $1",
            prev["analysis_id"],
        )
        if not analysis_row:
            continue

        for action in _jlist(analysis_row["actions"]):
            if action.get("completed") or action.get("is_rolled_over"):
                continue
            key = (prev["id"], action.get("id", ""))
            if key in seen_sources:
                continue

            assigned = (action.get("assigned_to") or "").strip().lower()
            if assigned and new_attendee_names_lower and assigned not in new_attendee_names_lower:
                continue

            seen_sources.add(key)
            rolled.append({
                **action,
                "id": f"rolled_{prev['id'][:6]}_{action.get('id', uuid.uuid4().hex[:6])}",
                "is_rolled_over": True,
                "completed": False,
                "completed_at": None,
                "source_meeting_id": prev["id"],
                "source_meeting_title": prev.get("title", "Previous Meeting"),
                "source_action_id": action.get("id"),
            })
    return rolled


async def run_transcription_and_analysis(meeting_id: str, audio_path: str):
    """Background task: transcribe audio then run AI analysis."""
    try:
        async with database.with_admin() as conn:
            await conn.execute(
                "UPDATE meetings SET status='transcribing', updated_at=$1 WHERE id=$2",
                datetime.now(timezone.utc).isoformat(), meeting_id,
            )
            meeting_row = await conn.fetchrow("SELECT * FROM meetings WHERE id = $1", meeting_id)

        meeting = dict(meeting_row) if meeting_row else {}
        attendee_count = len(_jlist(meeting.get("attendees"))) or None
        meeting_org_id = meeting.get("org_id")

        audio_data, _ = await get_audio(audio_path)

        logger.info(f"Starting transcription for meeting {meeting_id}")
        assemblyai_key = os.environ.get("ASSEMBLYAI_API_KEY")
        numbered_speaker_text = None
        transcript_warnings = []

        if assemblyai_key:
            try:
                transcript_text, numbered_speaker_text, timestamped_plain, transcript_warnings = await transcribe_with_assemblyai(
                    audio_data, speakers_expected=attendee_count
                )
            except Exception as aai_err:
                logger.error(f"AssemblyAI transcription failed for meeting {meeting_id}: {aai_err}")
                raise
        else:
            raise ValueError("ASSEMBLYAI_API_KEY not configured — transcription requires AssemblyAI")

        logger.info(f"Transcription complete for meeting {meeting_id}: {len(transcript_text)} chars")

        now = datetime.now(timezone.utc).isoformat()
        transcript_id = str(uuid.uuid4())

        async with database.with_admin() as conn:
            await conn.execute(
                """INSERT INTO transcripts (id, meeting_id, org_id, text, safety_warnings, created_at)
                   VALUES ($1,$2,$3,$4,$5::jsonb,$6)""",
                transcript_id, meeting_id, meeting_org_id,
                transcript_text, json.dumps(transcript_warnings), now,
            )
            await conn.execute(
                """UPDATE meetings SET transcript_id=$1, status='analyzing', updated_at=$2,
                   transcript_has_warnings=$3 WHERE id=$4""",
                transcript_id, now, len(transcript_warnings) > 0, meeting_id,
            )

        # Load standards — filtered by org's jurisdiction
        async with database.with_admin() as conn:
            org_row = await conn.fetchrow(
                "SELECT jurisdiction, service_type FROM organisations WHERE id=$1", meeting_org_id
            )
            org_jurisdiction = (org_row["jurisdiction"] if org_row else None) or "england"
            org_service_type = (org_row["service_type"] if org_row else None)

            if org_jurisdiction == "wales":
                cqc_rows = await conn.fetch(
                    "SELECT * FROM standards_entries WHERE type='ciw' AND is_active=TRUE AND jurisdiction='wales'",
                )
                care_cert_rows = await conn.fetch(
                    "SELECT * FROM standards_entries WHERE type IN ('awif','scw') AND is_active=TRUE AND jurisdiction='wales' ORDER BY type, reference",
                )
            elif org_jurisdiction == "scotland":
                cqc_rows = await conn.fetch(
                    "SELECT * FROM standards_entries WHERE type='ci' AND is_active=TRUE AND jurisdiction='scotland' ORDER BY reference",
                )
                care_cert_rows = await conn.fetch(
                    "SELECT * FROM standards_entries WHERE type='sssc' AND is_active=TRUE AND jurisdiction='scotland' ORDER BY reference",
                )
            elif org_jurisdiction == "northern_ireland":
                rqia_type = "rqia_dom" if org_service_type == "domiciliary" else "rqia_res"
                cqc_rows = await conn.fetch(
                    "SELECT * FROM standards_entries WHERE type=$1 AND is_active=TRUE AND jurisdiction='northern_ireland' ORDER BY reference",
                    rqia_type,
                )
                care_cert_rows = await conn.fetch(
                    "SELECT * FROM standards_entries WHERE type IN ('niscc_code','niscc_induction') AND is_active=TRUE AND jurisdiction='northern_ireland' ORDER BY type, reference",
                )
            else:
                cqc_rows = await conn.fetch(
                    "SELECT * FROM standards_entries WHERE type='cqc' AND is_active=TRUE AND (is_system=TRUE OR org_id=$1)",
                    meeting_org_id,
                )
                care_cert_rows = await conn.fetch(
                    "SELECT * FROM standards_entries WHERE type='care_cert' AND is_active=TRUE AND (is_system=TRUE OR org_id=$1)",
                    meeting_org_id,
                )
        cqc_standards = [_parse_std_row(r) for r in cqc_rows]
        care_cert_standards = [_parse_std_row(r) for r in care_cert_rows]

        if meeting_org_id:
            async with database.with_org(meeting_org_id) as conn:
                custom_rows = await conn.fetch(
                    "SELECT * FROM standards_documents WHERE org_id=$1 AND is_active=TRUE AND parse_status='parsed'",
                    meeting_org_id,
                )
            custom_standards = [dict(r) for r in custom_rows]
        else:
            custom_standards = []

        # Load supervision template
        supervision_template = None
        async with database.with_admin() as conn:
            tmpl_row = await conn.fetchrow(
                "SELECT data FROM settings WHERE id=$1",
                f"supervision_template:{meeting_org_id}",
            ) if meeting_org_id else None
            if not tmpl_row:
                tmpl_row = await conn.fetchrow(
                    "SELECT data FROM settings WHERE id='supervision_template'"
                )
        if tmpl_row and _jdict(tmpl_row["data"]).get("steps"):
            supervision_template = _jdict(tmpl_row["data"])

        # Fetch rolled-over actions
        attendees = _jlist(meeting.get("attendees"))
        attendee_ids = [a.get("user_id") for a in attendees]
        attendee_names = [a.get("name") for a in attendees]
        manager_name = meeting.get("sign_off_manager_name") or meeting.get("created_by_name") or "Manager"
        manager_id = meeting.get("sign_off_manager_id")

        async with database.with_admin() as conn:
            rolled_actions = await _get_rolled_actions(
                conn, attendee_ids, meeting_id, manager_id=manager_id, attendee_names=attendee_names
            )

        meeting_type = (meeting.get("meeting_type") or "supervision").replace("_", " ").title()
        supervisee_names = [a.get("name") for a in attendees if a.get("name")]

        if numbered_speaker_text:
            diarize_coro = map_speaker_numbers_to_names(numbered_speaker_text, manager_name, supervisee_names, meeting_type)
        else:
            diarize_coro = diarize_transcript(transcript_text, manager_name, supervisee_names, meeting_type)

        paused_periods = meeting.get("paused_periods") or []
        # Build effective jurisdiction string (NI needs service_type suffix for AI prompt routing)
        effective_jurisdiction = org_jurisdiction
        if org_jurisdiction == "northern_ireland":
            effective_jurisdiction = f"northern_ireland_{org_service_type or 'domiciliary'}"

        results = await asyncio.gather(
            analyze_meeting(timestamped_plain, cqc_standards, care_cert_standards, paused_periods, custom_standards, supervision_template, jurisdiction=effective_jurisdiction),
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
            async with database.with_admin() as conn:
                await conn.execute(
                    "UPDATE transcripts SET speaker_text=$1 WHERE id=$2",
                    speaker_text, transcript_id,
                )

        cqc_kq_map = {s["reference"]: s.get("key_questions") or [] for s in cqc_standards}
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

        for item in analysis_result.get("actions", []):
            if not item.get("id"):
                item["id"] = f"action_{uuid.uuid4().hex[:12]}"
            item.setdefault("completed", False)
            item.setdefault("completed_at", None)
            item.setdefault("is_rolled_over", False)
        analysis_result["actions"] = rolled_actions + analysis_result.get("actions", [])

        analysis_id = str(uuid.uuid4())
        async with database.with_admin() as conn:
            # Core INSERT — only columns guaranteed to exist in any schema version
            await conn.execute(
                """INSERT INTO analyses
                   (id, meeting_id, org_id, summary, actions, risks,
                    cqc_mappings, care_cert_mappings, created_at)
                   VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7::jsonb,$8::jsonb,$9)""",
                analysis_id, meeting_id, meeting_org_id,
                analysis_result.get("summary", ""),
                json.dumps(analysis_result.get("actions", [])),
                json.dumps(analysis_result.get("risks", [])),
                json.dumps(analysis_result.get("cqc_mappings", [])),
                json.dumps(analysis_result.get("care_cert_mappings", [])),
                now,
            )
            # Optional UPDATE for columns added after initial schema — safe to fail
            try:
                await conn.execute(
                    "UPDATE analyses SET custom_mappings=$1::jsonb WHERE id=$2",
                    json.dumps(analysis_result.get("custom_mappings", [])), analysis_id,
                )
            except Exception as _col_err:
                logger.warning(f"custom_mappings update skipped (column may not exist yet): {_col_err}")
            try:
                await conn.execute(
                    "UPDATE analyses SET achievements=$1::jsonb WHERE id=$2",
                    json.dumps(analysis_result.get("achievements", [])), analysis_id,
                )
            except Exception as _col_err:
                logger.warning(f"achievements update skipped (column may not exist yet): {_col_err}")
            await conn.execute(
                "UPDATE meetings SET analysis_id=$1, status='in_review', processing_error=NULL, updated_at=$2 WHERE id=$3",
                analysis_id, datetime.now(timezone.utc).isoformat(), meeting_id,
            )
        logger.info(f"Analysis complete for meeting {meeting_id}")

        # Phase 4: prep coverage check
        try:
            async with database.with_admin() as conn:
                prep_row = await conn.fetchrow(
                    "SELECT * FROM meeting_prep WHERE meeting_id=$1", meeting_id
                )
            if prep_row and _jlist(prep_row.get("sections")):
                from utils.ai import check_prep_coverage
                all_questions = []
                for section in _jlist(prep_row.get("sections")):
                    for q in section.get("questions", []):
                        if q.get("included", True) and q.get("text"):
                            all_questions.append({"id": q["id"], "text": q["text"]})
                if all_questions:
                    coverage = await check_prep_coverage(transcript_text, all_questions)
                    async with database.with_admin() as conn:
                        await conn.execute(
                            "UPDATE meeting_prep SET coverage_results=$1::jsonb, coverage_checked_at=$2 WHERE meeting_id=$3",
                            json.dumps(coverage.get("results", {})),
                            coverage.get("checked_at"),
                            meeting_id,
                        )
        except Exception as cov_exc:
            logger.warning(f"Prep coverage check non-fatal failure for {meeting_id}: {cov_exc}")

    except Exception as e:
        err_msg = str(e)[:500]
        logger.error(f"Processing failed for meeting {meeting_id}: {err_msg}")
        async with database.with_admin() as conn:
            await conn.execute(
                "UPDATE meetings SET status='processing_failed', processing_error=$1, updated_at=$2 WHERE id=$3",
                err_msg, datetime.now(timezone.utc).isoformat(), meeting_id,
            )


@router.post("/{meeting_id}/upload")
async def upload_audio(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user=Depends(get_current_user),
):
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        meeting_row = await conn.fetchrow("SELECT id, status FROM meetings WHERE id=$1", meeting_id)
    if not meeting_row:
        raise HTTPException(status_code=404, detail="Meeting not found")

    audio_data = await request.body()
    if not audio_data:
        raise HTTPException(status_code=400, detail="Empty audio body")

    content_type = request.headers.get("content-type", "audio/webm").split(";")[0].strip()
    file_ext = "webm"

    storage_path = f"{meeting_id}/audio_{uuid.uuid4()}.{file_ext}"
    try:
        result = await put_audio(storage_path, audio_data, content_type)
        actual_path = result.get("path", storage_path)
    except Exception as e:
        logger.error(f"Storage upload failed: {e}")
        actual_path = storage_path

    now = datetime.now(timezone.utc).isoformat()
    audio_file_id = str(uuid.uuid4())

    async with database.with_org(org_id) as conn:
        await conn.execute(
            """INSERT INTO audio_files
               (id, meeting_id, org_id, storage_path, original_filename, content_type, size_bytes,
                upload_status, processing_status, deletion_status, is_deleted, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
            audio_file_id, meeting_id, org_id, actual_path, "meeting.webm",
            content_type, len(audio_data),
            "uploaded", "pending", "active", False, now,
        )
        await conn.execute(
            "UPDATE meetings SET audio_file_id=$1, status='processing', updated_at=$2 WHERE id=$3",
            audio_file_id, now, meeting_id,
        )

    await enqueue_job(meeting_id, actual_path)

    return {
        "message": "Audio uploaded. Processing started.",
        "audio_file_id": audio_file_id,
        "size_bytes": len(audio_data),
    }


@router.post("/{meeting_id}/retry")
async def retry_processing(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
):
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        meeting_row = await conn.fetchrow("SELECT * FROM meetings WHERE id=$1", meeting_id)
    if not meeting_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = dict(meeting_row)
    if meeting.get("status") not in ("processing_failed", "processing", "in_review", "reviewed"):
        raise HTTPException(status_code=400, detail="Only processing_failed meetings can be retried")

    audio_file_id = meeting.get("audio_file_id")
    if not audio_file_id:
        raise HTTPException(status_code=400, detail="No audio file found — please re-upload the recording")

    async with database.with_org(org_id) as conn:
        audio_row = await conn.fetchrow("SELECT storage_path FROM audio_files WHERE id=$1", audio_file_id)
    if not audio_row:
        raise HTTPException(status_code=404, detail="Audio file record not found")

    storage_path = audio_row["storage_path"]
    if not storage_path:
        raise HTTPException(status_code=400, detail="Audio storage path missing")

    now = datetime.now(timezone.utc).isoformat()
    async with database.with_org(org_id) as conn:
        await conn.execute(
            "UPDATE meetings SET status='processing', updated_at=$1 WHERE id=$2",
            now, meeting_id,
        )
    await enqueue_job(meeting_id, storage_path)
    return {"message": "Retry started. Processing will resume shortly."}


async def _run_diarization_background(meeting_id: str, transcript_id: str, transcript_text: str,
                                      manager_name: str, attendee_names: list, meeting_type: str, org_id: str):
    try:
        speaker_text = await diarize_transcript(transcript_text, manager_name, attendee_names, meeting_type)
        if speaker_text:
            async with database.with_org(org_id) as conn:
                await conn.execute(
                    "UPDATE transcripts SET speaker_text=$1 WHERE id=$2",
                    speaker_text, transcript_id,
                )
                await conn.execute(
                    "UPDATE meetings SET diarize_status='done' WHERE id=$1",
                    meeting_id,
                )
        else:
            async with database.with_org(org_id) as conn:
                await conn.execute(
                    "UPDATE meetings SET diarize_status='failed' WHERE id=$1", meeting_id,
                )
    except Exception as e:
        logger.error(f"Background diarization failed for meeting {meeting_id}: {e}")
        try:
            async with database.with_org(org_id) as conn:
                await conn.execute(
                    "UPDATE meetings SET diarize_status='failed' WHERE id=$1", meeting_id,
                )
        except Exception:
            pass


@router.post("/{meeting_id}/diarize")
async def diarize_meeting_transcript(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
):
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        meeting_row = await conn.fetchrow("SELECT * FROM meetings WHERE id=$1", meeting_id)
    if not meeting_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = dict(meeting_row)

    transcript_id = meeting.get("transcript_id")
    if not transcript_id:
        raise HTTPException(status_code=400, detail="No transcript found for this meeting")

    async with database.with_org(org_id) as conn:
        t_row = await conn.fetchrow("SELECT text FROM transcripts WHERE id=$1", transcript_id)
    if not t_row:
        raise HTTPException(status_code=404, detail="Transcript not found")

    transcript_text = t_row["text"] or ""
    if not transcript_text:
        raise HTTPException(status_code=400, detail="Transcript text is empty")

    manager_name = meeting.get("sign_off_manager_name") or meeting.get("created_by_name") or "Manager"
    attendees = _jlist(meeting.get("attendees"))
    attendee_names = [a.get("name") for a in attendees if a.get("name")]
    meeting_type = (meeting.get("meeting_type") or "supervision").replace("_", " ").title()

    async with database.with_org(org_id) as conn:
        await conn.execute("UPDATE meetings SET diarize_status='processing' WHERE id=$1", meeting_id)

    background_tasks.add_task(
        _run_diarization_background,
        meeting_id, transcript_id, transcript_text,
        manager_name, attendee_names, meeting_type, org_id,
    )
    return {"status": "processing", "message": "Speaker identification started — this may take 1–2 minutes"}


@router.get("/{meeting_id}/status")
async def get_processing_status(meeting_id: str, current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        row = await conn.fetchrow(
            "SELECT status, diarize_status, audio_file_id, transcript_id, analysis_id, audio_deletion_status "
            "FROM meetings WHERE id=$1",
            meeting_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return {
        "status": row["status"],
        "diarize_status": row["diarize_status"],
        "has_audio": bool(row["audio_file_id"]),
        "has_transcript": bool(row["transcript_id"]),
        "has_analysis": bool(row["analysis_id"]),
        "audio_deletion_status": row["audio_deletion_status"] or "none",
    }


@router.post("/{meeting_id}/retranscribe")
async def retranscribe_meeting(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Manager or admin required")

    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        meeting_row = await conn.fetchrow("SELECT * FROM meetings WHERE id=$1", meeting_id)
    if not meeting_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = dict(meeting_row)

    audio_file_id = meeting.get("audio_file_id")
    if not audio_file_id:
        raise HTTPException(status_code=400, detail="No audio file associated with this meeting")

    async with database.with_org(org_id) as conn:
        audio_row = await conn.fetchrow("SELECT storage_path FROM audio_files WHERE id=$1", audio_file_id)
    if not audio_row or not audio_row["storage_path"]:
        raise HTTPException(status_code=404, detail="Audio file record not found")

    transcript_id = meeting.get("transcript_id")
    if not transcript_id:
        raise HTTPException(status_code=400, detail="No transcript record found — use retry instead")

    async with database.with_org(org_id) as conn:
        await conn.execute("UPDATE meetings SET diarize_status='processing' WHERE id=$1", meeting_id)

    background_tasks.add_task(
        _run_retranscribe_background,
        meeting_id, transcript_id, audio_row["storage_path"], meeting, org_id,
    )
    return {"status": "processing", "message": "Re-scanning audio — this takes 1–3 minutes. Refresh the transcript tab when done."}


async def _run_retranscribe_background(meeting_id: str, transcript_id: str, storage_path: str, meeting: dict, org_id: str):
    try:
        audio_data, _ = await get_audio(storage_path)
    except Exception as e:
        logger.error(f"Retranscribe: could not load audio for {meeting_id}: {e}")
        async with database.with_org(org_id) as conn:
            await conn.execute("UPDATE meetings SET diarize_status='failed' WHERE id=$1", meeting_id)
        return

    assemblyai_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not assemblyai_key:
        logger.error("Retranscribe: ASSEMBLYAI_API_KEY not set")
        async with database.with_org(org_id) as conn:
            await conn.execute("UPDATE meetings SET diarize_status='failed' WHERE id=$1", meeting_id)
        return

    attendee_count = len(_jlist(meeting.get("attendees"))) or None
    try:
        plain_text, numbered_speaker_text, _, _ = await transcribe_with_assemblyai(audio_data, speakers_expected=attendee_count)
    except Exception as e:
        logger.error(f"Retranscribe: AssemblyAI failed for {meeting_id}: {e}")
        async with database.with_org(org_id) as conn:
            await conn.execute("UPDATE meetings SET diarize_status='failed' WHERE id=$1", meeting_id)
        return

    manager_name = meeting.get("sign_off_manager_name") or meeting.get("created_by_name") or "Manager"
    attendees = _jlist(meeting.get("attendees"))
    attendee_names = [a.get("name") for a in attendees if a.get("name")]
    meeting_type = (meeting.get("meeting_type") or "supervision").replace("_", " ").title()

    if numbered_speaker_text:
        speaker_text = await map_speaker_numbers_to_names(numbered_speaker_text, manager_name, attendee_names, meeting_type)
    else:
        speaker_text = await diarize_transcript(plain_text, manager_name, attendee_names, meeting_type)

    if not speaker_text:
        logger.warning(f"Retranscribe: diarization returned nothing for {meeting_id}")
        async with database.with_org(org_id) as conn:
            await conn.execute("UPDATE meetings SET diarize_status='failed' WHERE id=$1", meeting_id)
        return

    now = datetime.now(timezone.utc).isoformat()
    async with database.with_org(org_id) as conn:
        await conn.execute(
            "UPDATE transcripts SET text=$1, speaker_text=$2, retranscribed_at=$3 WHERE id=$4",
            plain_text, speaker_text, now, transcript_id,
        )
        await conn.execute(
            "UPDATE meetings SET diarize_status='done', retranscribed_at=$1 WHERE id=$2",
            now, meeting_id,
        )
    logger.info(f"Retranscribe complete for meeting {meeting_id}")
