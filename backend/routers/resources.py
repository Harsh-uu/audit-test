"""GET /api/resources — curated downloads + course modules, global (not org-scoped)."""

from fastapi import APIRouter, Depends
from deps import get_current_user
import database

router = APIRouter()


@router.get("/")
async def list_resources(current_user=Depends(get_current_user)):
    async with database.with_admin() as conn:
        rows = await conn.fetch(
            """SELECT id, category, title, description, url, source_label
               FROM resources WHERE is_active=TRUE ORDER BY category, sort_order, created_at"""
        )
    downloads = [dict(r) for r in rows if r["category"] == "download"]
    courses = [dict(r) for r in rows if r["category"] == "course"]
    return {"downloads": downloads, "courses": courses}
