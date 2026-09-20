"""GET /api/resources — curated downloads + course modules, global (not org-scoped).
Public — no auth. Anyone with the link can view the free course/downloads;
this is the ONLY page in the app that is intentionally public."""

from fastapi import APIRouter
import database

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
