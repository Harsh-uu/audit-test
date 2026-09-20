"""GET /api/resources — curated downloads + course modules, global (not org-scoped).
Public — no auth. Anyone with the link can view the free course/downloads;
this is the ONLY page in the app that is intentionally public."""

from fastapi import APIRouter, HTTPException, Response
import database
from utils.supabase_storage import get_document

router = APIRouter()


@router.get("/")
async def list_resources():
    async with database.with_admin() as conn:
        rows = await conn.fetch(
            """SELECT id, category, title, description, url, source_label
               FROM resources WHERE is_active=TRUE ORDER BY category, sort_order, created_at"""
        )
    downloads = [dict(r) for r in rows if r["category"] == "download"]
    courses = [dict(r) for r in rows if r["category"] == "course"]
    return {"downloads": downloads, "courses": courses}


@router.get("/course/{resource_id}/file")
async def get_course_file(resource_id: str):
    """Serves a self-hosted course PDF straight from Supabase Storage — public, no auth."""
    async with database.with_admin() as conn:
        row = await conn.fetchrow(
            "SELECT title, storage_path, content_type FROM resources WHERE id=$1 AND category='course' AND is_active=TRUE",
            resource_id,
        )
    if not row or not row["storage_path"]:
        raise HTTPException(404, "Resource not found")
    try:
        file_data, _ = await get_document(row["storage_path"])
    except Exception:
        raise HTTPException(404, "File not found in storage")
    return Response(
        content=file_data,
        media_type=row["content_type"] or "application/pdf",
        headers={"Content-Disposition": f'inline; filename="{row["title"]}.pdf"'},
    )
