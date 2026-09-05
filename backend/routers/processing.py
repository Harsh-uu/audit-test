from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
from datetime import datetime, timezone
import uuid
import logging
import os
from deps import get_current_user
from utils.supabase_storage import put_audio, get_audio
from utils.ai import diarize_transcript, transcribe_with_assemblyai, map_speaker_numbers_to_names
from utils.job_worker import enqueue_job
import database

router = APIRouter()
logger = logging.getLogger(__name__)


from utils.transcription_pipeline import _jlist


def _assert_meeting_actor(meeting: dict, user_id: str, role: str) -> None:
    """Raise 403 if caller is not an attendee, creator, or manager/admin of the meeting."""
    if role in ("admin", "manager"):
        return
    if str(meeting.get("created_by", "")) == str(user_id):
        return
    if any(str(a.get("user_id", "")) == str(user_id) for a in _jlist(meeting.get("attendees"))):
        return
    raise HTTPException(status_code=403, detail="You are not a participant in this meeting")


@router.post("/{meeting_id}/upload")
async def upload_audio(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user=Depends(get_current_user),
):
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        meeting_row = await conn.fetchrow(
            "SELECT id, status, created_by, attendees FROM meetings WHERE id=$1", meeting_id
        )
    if not meeting_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    _assert_meeting_actor(dict(meeting_row), current_user["id"], current_user.get("role", ""))

    # Early Content-Length guard — rejects oversized uploads at the HTTP layer
    # before streaming the body into memory. Content-Length may be absent for
    # chunked transfers; the post-read check below still applies in that case.
    _cl_header = request.headers.get("content-length")
    if _cl_header:
        try:
            if int(_cl_header) > 350 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="Recording too large (max 350 MB)")
        except ValueError:
            pass

    audio_data = await request.body()
    if not audio_data:
        raise HTTPException(status_code=400, detail="Empty audio body")
    if len(audio_data) > 350 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Recording too large (max 350 MB)")

    _size_mb = len(audio_data) / (1024 * 1024)
    if _size_mb > 300:
        logger.warning(
            "Large audio upload: meeting=%s org=%s size=%.1f MB — approaching 350 MB bucket limit",
            meeting_id, org_id, _size_mb,
        )

    # Normalise to audio/webm regardless of what the browser sends (browsers often
    # send application/octet-stream or video/webm for MediaRecorder blobs).
    _raw_ct = request.headers.get("content-type", "audio/webm").split(";")[0].strip().lower()
    _AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-m4a"}
    content_type = _raw_ct if _raw_ct in _AUDIO_TYPES else "audio/webm"
    file_ext = "webm"

    storage_path = f"{meeting_id}/audio_{uuid.uuid4()}.{file_ext}"
    try:
        result = await put_audio(storage_path, audio_data, content_type)
        actual_path = result.get("path", storage_path)
    except Exception as e:
        logger.error(f"Storage upload failed for meeting {meeting_id}: {e}")
        raise HTTPException(
            status_code=502,
            detail="Audio storage unavailable — please try again. Your recording has not been lost; re-upload when ready.",
        )

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
        meeting_row = await conn.fetchrow(
            "SELECT status, audio_file_id, created_by, attendees FROM meetings WHERE id=$1", meeting_id,
        )
    if not meeting_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = dict(meeting_row)
    _assert_meeting_actor(meeting, current_user["id"], current_user.get("role", ""))
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
    # Rate limit: 10 diarize calls per org per hour
    from utils.rate_limit import check_rate_limit
    import database
    async with database.with_admin() as rl_conn:
        await check_rate_limit(
            rl_conn,
            identifier=f"ai_diarize:{current_user.get('org_id','')}",
            max_attempts=10,
            window_minutes=60,
            error_detail="Too many re-diarize requests. Please wait before trying again.",
        )
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        meeting_row = await conn.fetchrow(
            "SELECT created_by, attendees, transcript_id, sign_off_manager_name, created_by_name, meeting_type "
            "FROM meetings WHERE id=$1", meeting_id,
        )
    if not meeting_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = dict(meeting_row)
    _assert_meeting_actor(meeting, current_user["id"], current_user.get("role", ""))

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

    # Rate limit: 10 retranscribe calls per org per hour
    from utils.rate_limit import check_rate_limit
    import database
    async with database.with_admin() as rl_conn:
        await check_rate_limit(
            rl_conn,
            identifier=f"ai_retranscribe:{current_user.get('org_id','')}",
            max_attempts=10,
            window_minutes=60,
            error_detail="Too many retranscription requests. Please wait before trying again.",
        )
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        meeting_row = await conn.fetchrow(
            "SELECT audio_file_id, transcript_id, attendees, sign_off_manager_name, created_by_name, meeting_type "
            "FROM meetings WHERE id=$1", meeting_id,
        )
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
