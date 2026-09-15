"""
Supabase Storage for sensitive files — audio recordings and custom documents.
Data stays in the EU (Supabase project region) and never touches Emergent infra.
"""
import asyncio
import logging
import mimetypes
import os
from functools import partial

logger = logging.getLogger(__name__)

AUDIO_BUCKET = "audio-recordings"
DOCS_BUCKET  = "supervision-documents"

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    client = create_client(url, key)
    _ensure_buckets(client)
    _client = client          # only cache after buckets confirmed
    return _client


def _ensure_buckets(client):
    """Create required buckets if they don't exist.

    Raises on unexpected errors so the caller sees the real problem in Loki
    rather than a silent swallow followed by a confusing 'bucket not found'.
    """
    try:
        existing = {b.name for b in client.storage.list_buckets()}
    except Exception as exc:
        # Can't list buckets — likely wrong key type (anon vs service_role).
        # Log the full error and re-raise so _get_client never caches a broken client.
        logger.error(
            "Supabase storage: failed to list buckets. "
            "Ensure SUPABASE_SERVICE_KEY is the service_role key, not the anon key. "
            "Error: %s", exc, exc_info=True
        )
        raise

    for bucket in [AUDIO_BUCKET, DOCS_BUCKET]:
        if bucket not in existing:
            try:
                client.storage.create_bucket(bucket, options={"public": False})
                logger.info("Supabase storage: created bucket '%s'", bucket)
            except Exception as exc:
                msg = str(exc).lower()
                # "already exists" is fine (race between two workers); anything else is real
                if "already" not in msg and "exist" not in msg:
                    logger.error(
                        "Supabase storage: failed to create bucket '%s': %s", bucket, exc, exc_info=True
                    )
                    raise


def _sync_put(bucket: str, path: str, data: bytes, content_type: str) -> dict:
    client = _get_client()
    try:
        client.storage.from_(bucket).upload(
            path,
            data,
            file_options={"content-type": content_type, "upsert": "true", "cache-control": "no-store"},
        )
    except Exception as exc:
        logger.error(
            "Supabase storage: upload failed — bucket=%s path=%s error=%s",
            bucket, path, exc, exc_info=True,
        )
        raise
    return {"path": path}


def _sync_get(bucket: str, path: str):
    client = _get_client()
    data = client.storage.from_(bucket).download(path)
    content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return data, content_type


def _sync_remove(bucket: str, path: str):
    client = _get_client()
    client.storage.from_(bucket).remove([path])


def _sync_remove_many(bucket: str, paths: list):
    client = _get_client()
    client.storage.from_(bucket).remove(paths)


async def put_audio(path: str, data: bytes, content_type: str) -> dict:
    """Upload a meeting audio recording to Supabase (EU)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, partial(_sync_put, AUDIO_BUCKET, path, data, content_type)
    )


async def get_audio(path: str):
    """Fetch a meeting audio recording from Supabase."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, partial(_sync_get, AUDIO_BUCKET, path)
    )


async def delete_audio(path: str):
    """Permanently delete a meeting audio recording from Supabase (GDPR)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, partial(_sync_remove, AUDIO_BUCKET, path)
    )


async def delete_audio_batch(paths: list):
    """Permanently delete multiple meeting audio recordings in one Supabase call (GDPR)."""
    if not paths:
        return
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, partial(_sync_remove_many, AUDIO_BUCKET, paths)
    )


async def put_document(path: str, data: bytes, content_type: str) -> dict:
    """Upload a custom standards document to Supabase (EU)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, partial(_sync_put, DOCS_BUCKET, path, data, content_type)
    )


async def get_document(path: str):
    """Fetch a custom standards document from Supabase."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, partial(_sync_get, DOCS_BUCKET, path)
    )


async def delete_document(path: str):
    """Permanently delete a custom standards document from Supabase."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, partial(_sync_remove, DOCS_BUCKET, path)
    )

