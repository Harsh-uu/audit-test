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
DOCS_BUCKET = "supervision-documents"

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    _client = create_client(url, key)
    _ensure_buckets(_client)
    return _client


def _ensure_buckets(client):
    try:
        existing = {b.name for b in client.storage.list_buckets()}
        for bucket in [AUDIO_BUCKET, DOCS_BUCKET]:
            if bucket not in existing:
                client.storage.create_bucket(bucket, options={"public": False})
                logger.info("Created Supabase bucket: %s", bucket)
    except Exception as exc:
        logger.warning("Supabase bucket init warning: %s", exc)


def _sync_put(bucket: str, path: str, data: bytes, content_type: str) -> dict:
    client = _get_client()
    client.storage.from_(bucket).upload(
        path, data,
        file_options={"content-type": content_type, "upsert": "false"},
    )
    return {"path": path}


def _sync_get(bucket: str, path: str):
    client = _get_client()
    data = client.storage.from_(bucket).download(path)
    content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return data, content_type


async def put_audio(path: str, data: bytes, content_type: str) -> dict:
    """Upload a meeting audio recording to Supabase (EU)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_sync_put, AUDIO_BUCKET, path, data, content_type))


async def get_audio(path: str):
    """Fetch a meeting audio recording from Supabase."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_sync_get, AUDIO_BUCKET, path))


async def put_document(path: str, data: bytes, content_type: str) -> dict:
    """Upload a custom standards document to Supabase (EU)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_sync_put, DOCS_BUCKET, path, data, content_type))
