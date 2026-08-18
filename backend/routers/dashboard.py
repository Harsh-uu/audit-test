"""
GET /api/dashboard — combined endpoint for the manager dashboard.

Runs four DB queries concurrently (asyncio.gather) and returns a single JSON
response so the frontend makes ONE network round-trip instead of four.

Queries run in parallel:
  1. meetings list (first 50, newest first)
  2. due-this-month schedules  (admin/manager only)
  3. outstanding/overdue action counts  (admin/manager only)
  4. org structure for filter dropdowns  (admin/manager only)
"""

import asyncio
from datetime import datetime, timezone, date
import calendar
from fastapi import APIRouter, Depends
from deps import get_current_user, get_manager_scope, get_scoped_staff_ids
import database
from routers.meetings import _list_meetings_data
from routers.schedules import _enriched_schedules
from routers.admin import _jlist

router = APIRouter()

_DASHBOARD_LIMIT = 50  # initial meetings batch; frontend shows "Load all" if count == 50


@router.get("/")
async def get_dashboard(current_user=Depends(get_current_user)):
    role = current_user["role"]
    is_manager_admin = role in ("admin", "manager")

    async def fetch_due():
        if not is_manager_admin:
            return []
        org_id = current_user.get("org_id", "")
        if not org_id:
            return []
        scope = get_manager_scope(current_user)
        async with database.with_org(org_id) as conn:
            staff_ids = await get_scoped_staff_ids(conn, org_id, scope)
            all_s = await _enriched_schedules(conn, org_id, staff_ids)
        today = date.today()
        last_day = calendar.monthrange(today.year, today.month)[1]
        month_end = date(today.year, today.month, last_day).isoformat()
        due = [s for s in all_s if s["next_due"] <= month_end]
        due.sort(key=lambda s: s["next_due"])
        return due

    async def fetch_action_stats():
        if not is_manager_admin:
            return None
        org_id = current_user.get("org_id", "")
        if not org_id:
            return None
        today = datetime.now(timezone.utc).date().isoformat()
        async with database.with_org(org_id) as conn:
            rows = await conn.fetch(
                """SELECT a.actions
                   FROM meetings m
                   JOIN analyses a ON a.id = m.analysis_id
                   WHERE m.status IN ('in_review','reviewed','signed_off','shared')
                   AND m.analysis_id IS NOT NULL"""
            )
        outstanding, overdue = 0, 0
        for row in rows:
            for action in _jlist(dict(row).get("actions")):
                if isinstance(action, dict) and not action.get("completed", False):
                    outstanding += 1
                    if action.get("due_date") and str(action["due_date"]) < today:
                        overdue += 1
        return {"outstanding": outstanding, "overdue": overdue}

    async def fetch_structure():
        """Lightweight settings+teams list for dashboard filter dropdowns.
        Omits member detail (no N+1) — full structure is loaded only on the
        Organisation page which needs it.
        """
        if not is_manager_admin:
            return None
        org_id = current_user.get("org_id", "")
        if not org_id:
            return None
        scope = get_manager_scope(current_user)
        async with database.with_org(org_id) as conn:
            if scope["level"] == "org":
                s_rows = await conn.fetch(
                    "SELECT id, name FROM org_settings ORDER BY name ASC"
                )
            else:
                s_rows = await conn.fetch(
                    "SELECT id, name FROM org_settings WHERE id=$1", scope["setting_id"]
                )
            settings = []
            for s_row in s_rows:
                s = dict(s_row)
                if scope["level"] == "team":
                    t_rows = await conn.fetch(
                        "SELECT id, name FROM teams WHERE setting_id=$1 AND id=$2 ORDER BY name ASC",
                        s["id"], scope["team_id"],
                    )
                else:
                    t_rows = await conn.fetch(
                        "SELECT id, name FROM teams WHERE setting_id=$1 ORDER BY name ASC", s["id"]
                    )
                s["teams"] = [dict(t) for t in t_rows]
                settings.append(s)
        return {"settings": settings, "unassigned_users": []}

    meetings, due, action_stats, org_structure = await asyncio.gather(
        _list_meetings_data(current_user, limit=_DASHBOARD_LIMIT, offset=0),
        fetch_due(),
        fetch_action_stats(),
        fetch_structure(),
    )

    return {
        "meetings": meetings,
        "has_more_meetings": len(meetings) == _DASHBOARD_LIMIT,
        "due_schedules": due,
        "action_stats": action_stats,
        "org_structure": org_structure,
    }
