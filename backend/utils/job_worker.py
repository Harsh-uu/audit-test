"""
PostgreSQL-backed persistent job queue.
Jobs survive server restarts. Atomic claim via UPDATE...RETURNING.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta

import database

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
POLL_INTERVAL = 5
STUCK_TIMEOUT = 15  # minutes


async def enqueue_job(meeting_id: str, audio_path: str) -> str:
    """Insert a pending job. Returns the new job id."""
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    async with database.with_admin() as conn:
        await conn.execute(
            """INSERT INTO jobs (id, meeting_id, audio_path, status, attempts, created_at, updated_at)
               VALUES ($1,$2,$3,'pending',0,$4,$4)""",
            job_id, meeting_id, audio_path, now,
        )
    logger.info(f"[queue] Job enqueued for meeting {meeting_id} → {job_id}")
    return job_id


async def _recover_stuck_jobs():
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=STUCK_TIMEOUT)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    async with database.with_admin() as conn:
        # Permanently fail stuck jobs that have exhausted all retry attempts
        fail_result = await conn.execute(
            """UPDATE jobs
               SET status='failed',
                   error='Timed out in processing state — all retry attempts exhausted',
                   updated_at=$1
               WHERE status='processing'
                 AND updated_at < $2
                 AND attempts >= $3""",
            now, cutoff, MAX_ATTEMPTS,
        )
        fail_count = int(fail_result.split()[-1])

        # Re-queue stuck jobs that still have retries remaining
        retry_result = await conn.execute(
            """UPDATE jobs
               SET status='pending',
                   error='Recovered from stuck processing state — will retry',
                   updated_at=$1
               WHERE status='processing'
                 AND updated_at < $2
                 AND attempts < $3""",
            now, cutoff, MAX_ATTEMPTS,
        )
        retry_count = int(retry_result.split()[-1])

    if fail_count:
        logger.error(f"[queue] Permanently failed {fail_count} stuck job(s) — max attempts exhausted")
    if retry_count:
        logger.warning(f"[queue] Re-queued {retry_count} stuck job(s) for retry")


async def _claim_next_job() -> dict | None:
    """Atomically grab the oldest pending job and mark it as processing.

    Fresh jobs (attempts=0) are claimed immediately.  Retried jobs observe a
    linear backoff of attempts × 30 seconds so a flapping external API is not
    hammered on every poll cycle.
    """
    now = datetime.now(timezone.utc).isoformat()
    async with database.with_admin() as conn:
        row = await conn.fetchrow(
            """UPDATE jobs SET status='processing', attempts=attempts+1, updated_at=$1
               WHERE id = (
                   SELECT id FROM jobs
                   WHERE status='pending' AND attempts < $2
                     AND (
                       attempts = 0
                       OR updated_at < (CURRENT_TIMESTAMP - (attempts * interval '30 seconds'))
                     )
                   ORDER BY created_at ASC
                   LIMIT 1
                   FOR UPDATE SKIP LOCKED
               )
               RETURNING *""",
            now, MAX_ATTEMPTS,
        )
    return dict(row) if row else None


async def _process_job(job: dict):
    job_id = job["id"]
    meeting_id = job["meeting_id"]
    audio_path = job["audio_path"]
    attempt = job["attempts"]

    logger.info(f"[queue] Starting job {job_id} meeting {meeting_id} (attempt {attempt}/{MAX_ATTEMPTS})")

    try:
        from routers.processing import run_transcription_and_analysis
        await run_transcription_and_analysis(meeting_id, audio_path)

        async with database.with_admin() as conn:
            await conn.execute(
                "UPDATE jobs SET status='completed', updated_at=$1, error=NULL WHERE id=$2",
                datetime.now(timezone.utc).isoformat(), job_id,
            )
        logger.info(f"[queue] Job {job_id} completed ✓")

    except Exception as e:
        error_msg = str(e)
        logger.error(f"[queue] Job {job_id} failed: {error_msg}")
        now = datetime.now(timezone.utc).isoformat()
        async with database.with_admin() as conn:
            if attempt >= MAX_ATTEMPTS:
                await conn.execute(
                    "UPDATE jobs SET status='failed', error=$1, updated_at=$2 WHERE id=$3",
                    error_msg, now, job_id,
                )
                logger.error(f"[queue] Job {job_id} permanently failed after {attempt} attempts")
            else:
                await conn.execute(
                    "UPDATE jobs SET status='pending', error=$1, updated_at=$2 WHERE id=$3",
                    error_msg, now, job_id,
                )
                logger.info(f"[queue] Job {job_id} will retry (attempt {attempt}/{MAX_ATTEMPTS})")


async def _sweep_audio_deletions():
    """
    Recovery sweep: delete audio for meetings whose grace period has expired but
    whose background task was lost (e.g. process restarted during the 5-min window).
    Safe to run repeatedly — only targets rows still in 'grace_period'.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat()
    async with database.with_admin() as conn:
        rows = await conn.fetch(
            """SELECT id, audio_file_id FROM meetings
               WHERE audio_deletion_status = 'grace_period'
                 AND audio_grace_period_started_at < $1
                 AND status = 'signed_off'""",
            cutoff,
        )
    if not rows:
        return
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        meeting_id = row["id"]
        audio_file_id = row["audio_file_id"]
        try:
            if audio_file_id:
                async with database.with_admin() as conn:
                    await conn.execute(
                        "UPDATE audio_files SET is_deleted=TRUE, deletion_status='deleted', deleted_at=$1 WHERE id=$2",
                        now, audio_file_id,
                    )
            async with database.with_admin() as conn:
                await conn.execute(
                    "UPDATE meetings SET audio_deletion_status='deleted', audio_deleted_at=$1, updated_at=$1 WHERE id=$2",
                    now, meeting_id,
                )
            logger.info("[queue] Audio sweep: deleted audio for meeting %s", meeting_id)
        except Exception as e:
            logger.error("[queue] Audio sweep: deletion failed for meeting %s: %s", meeting_id, e)


async def start_worker():
    logger.info(f"[queue] Worker started — polling every {POLL_INTERVAL}s")
    await _recover_stuck_jobs()
    await _sweep_audio_deletions()   # recover any deletions lost across restarts
    poll_count = 0
    while True:
        try:
            poll_count += 1
            if poll_count % 60 == 0:
                await _recover_stuck_jobs()
            if poll_count % 12 == 0:          # every ~60 s — belt-and-suspenders
                await _sweep_audio_deletions()
            job = await _claim_next_job()
            if job:
                await _process_job(job)
        except Exception as e:
            logger.error(f"[queue] Worker loop error: {e}")
        await asyncio.sleep(POLL_INTERVAL)
