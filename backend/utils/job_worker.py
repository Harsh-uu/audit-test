"""
MongoDB-backed persistent job queue.

Jobs survive server restarts because they live in Atlas.
On startup any job stuck in "processing" is automatically recovered.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
POLL_INTERVAL = 5          # seconds between polls
STUCK_TIMEOUT = 15         # minutes before a "processing" job is considered stuck


async def enqueue_job(db, meeting_id: str, audio_path: str) -> str:
    """Insert a pending job into MongoDB. Returns the job _id as a string."""
    now = datetime.now(timezone.utc)
    result = await db.jobs.insert_one({
        "job_type": "transcription",
        "meeting_id": meeting_id,
        "audio_path": audio_path,
        "status": "pending",
        "attempts": 0,
        "max_attempts": MAX_ATTEMPTS,
        "created_at": now,
        "started_at": None,
        "completed_at": None,
        "error": None,
    })
    logger.info(f"[queue] Job enqueued for meeting {meeting_id} → {result.inserted_id}")
    return str(result.inserted_id)


async def _recover_stuck_jobs(db):
    """
    Find jobs that were claimed but never finished (server crashed mid-processing).
    Reset them to pending so the worker picks them up again.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_TIMEOUT)
    result = await db.jobs.update_many(
        {
            "status": "processing",
            "started_at": {"$lt": cutoff},
            "attempts": {"$lt": MAX_ATTEMPTS},
        },
        {
            "$set": {"status": "pending", "started_at": None},
        }
    )
    if result.modified_count:
        logger.warning(f"[queue] Recovered {result.modified_count} stuck job(s) → reset to pending")


async def _claim_next_job(db):
    """
    Atomically grab the oldest pending job and mark it as processing.
    Returns the job document, or None if the queue is empty.
    """
    now = datetime.now(timezone.utc)
    return await db.jobs.find_one_and_update(
        {"status": "pending", "attempts": {"$lt": MAX_ATTEMPTS}},
        {
            "$set": {"status": "processing", "started_at": now},
            "$inc": {"attempts": 1},
        },
        sort=[("created_at", 1)],   # FIFO — oldest job first
        return_document=True,
    )


async def _process_job(job: dict, db):
    """Run one job and write the final status back to MongoDB."""
    job_id = job["_id"]
    meeting_id = job["meeting_id"]
    audio_path = job["audio_path"]
    attempt = job["attempts"]

    logger.info(f"[queue] Starting job {job_id} for meeting {meeting_id} (attempt {attempt}/{MAX_ATTEMPTS})")

    try:
        # Lazy import avoids circular dependency with routers.processing
        from routers.processing import run_transcription_and_analysis
        await run_transcription_and_analysis(meeting_id, audio_path, db)

        await db.jobs.update_one(
            {"_id": job_id},
            {"$set": {
                "status": "completed",
                "completed_at": datetime.now(timezone.utc),
                "error": None,
            }}
        )
        logger.info(f"[queue] Job {job_id} completed ✓")

    except Exception as e:
        error_msg = str(e)
        logger.error(f"[queue] Job {job_id} failed: {error_msg}")

        if attempt >= MAX_ATTEMPTS:
            await db.jobs.update_one(
                {"_id": job_id},
                {"$set": {
                    "status": "failed",
                    "error": error_msg,
                    "completed_at": datetime.now(timezone.utc),
                }}
            )
            logger.error(f"[queue] Job {job_id} permanently failed after {attempt} attempts — giving up")
        else:
            # Reset to pending so the next poll retries it
            await db.jobs.update_one(
                {"_id": job_id},
                {"$set": {"status": "pending", "error": error_msg}}
            )
            logger.info(f"[queue] Job {job_id} will retry (attempt {attempt}/{MAX_ATTEMPTS})")


async def start_worker(db):
    """
    Long-running coroutine — launched once at app startup via asyncio.create_task().
    Polls MongoDB every POLL_INTERVAL seconds for pending jobs.
    Recovers stuck jobs from crashed servers automatically.
    """
    logger.info(f"[queue] Worker started — polling every {POLL_INTERVAL}s, max {MAX_ATTEMPTS} attempts per job")

    # Recover any jobs left stuck from the previous server run
    await _recover_stuck_jobs(db)

    poll_count = 0
    while True:
        try:
            poll_count += 1

            # Re-check for stuck jobs every 5 minutes (~60 polls)
            if poll_count % 60 == 0:
                await _recover_stuck_jobs(db)

            job = await _claim_next_job(db)
            if job:
                # Process synchronously inside the loop so we don't pile up concurrent jobs.
                # Audio transcription is already I/O-bound (AssemblyAI) so this is safe.
                await _process_job(job, db)

        except Exception as e:
            logger.error(f"[queue] Worker loop error: {e}")

        await asyncio.sleep(POLL_INTERVAL)
