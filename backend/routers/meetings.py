import json
import uuid
import logging
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from pydantic import BaseModel, field_validator
from datetime import datetime, timezone
from typing import Optional, List
from deps import get_db, get_current_user, get_current_user_conn, get_manager_scope, get_scoped_staff_ids
from routers.org import get_structure_lite_data
import database
from utils.supabase_storage import delete_audio
from utils.backdate_check import detect_backdate_mismatch

logger = logging.getLogger(__name__)

router = APIRouter()

# Columns returned for the list view — heavy/report-only fields are excluded.
_LIST_COLS = (
    "id, org_id, title, date, location, meeting_type, "
    "created_by, created_by_name, sign_off_manager_id, sign_off_manager_name, "
    "attendees, team_id, setting_id, schedule_id, status, "
    "analysis_id, transcript_id, transcript_has_warnings, "
    "shared_with, total_paused_duration_seconds, "
    "audio_file_id, created_at, updated_at"
)

# Detail view (GET /{id}) needs the full report page — every column, spelled
# out explicitly (instead of SELECT *) so the query is self-documenting and
# immune to surprise columns from a future migration.
_DETAIL_COLS = (
    "id, org_id, title, date, location, meeting_type, meeting_type_id, "
    "created_by, created_by_name, sign_off_manager_id, sign_off_manager_name, "
    "attendees, team_id, setting_id, schedule_id, status, "
    "recording_events, paused_periods, total_paused_duration_seconds, recording_notice_shown_at, "
    "audio_file_id, transcript_id, analysis_id, sign_off_record, "
    "pii_redactions, pii_review_status, pii_reviewed_at, pii_reviewed_by, pii_reviewed_by_name, pii_skipped, "
    "shared_with, audio_deletion_status, audio_grace_period_started_at, audio_deleted_at, "
    "transcript_has_warnings, diarize_status, reopen_record, "
    "reopen_requested, reopen_requested_by, reopen_requested_by_name, reopen_requested_at, reopen_reason, "
    "reopen_approved_by, reopen_approved_by_name, reopen_approved_at, "
    "rescan_status, retranscribed_at, processing_error, notes, created_at, updated_at"
)

_TRANSCRIPT_DETAIL_COLS = (
    "id, meeting_id, org_id, text, speaker_text, safety_warnings, speaker_colors, "
    "speaker_text_backup, speaker_text_backup_at, speaker_text_backup_by, "
    "speaker_text_edited_by_name, speaker_text_edited_at, retranscribed_at, created_at, updated_at"
)

_ANALYSIS_DETAIL_COLS = (
    "id, meeting_id, org_id, summary, edited_summary, achievements, actions, learning_needs, risks, "
    "cqc_mappings, care_cert_mappings, custom_mappings, pii_redactions, "
    "last_edited_by, last_edited_at, rescanned_at, rescanned_by_name, created_at"
)


class CreateMeetingRequest(BaseModel):
    title: str
    date: str
    location: Optional[str] = None
    meeting_type: str = "Supervision"
    attendee_ids: List[str] = []
    sign_off_manager_id: Optional[str] = None
    schedule_id: Optional[str] = None

    @field_validator("date")
    @classmethod
    def _date_must_be_a_real_date(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v)
        except ValueError:
            raise ValueError("date must be a valid ISO-8601 date/datetime string")
        return v

    @field_validator("meeting_type")
    @classmethod
    def _meeting_type_not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("meeting_type must not be blank")
        if len(v) > 100:
            raise ValueError("meeting_type must be 100 characters or fewer")
        return v


class UpdateAttendeesRequest(BaseModel):
    attendee_ids: List[str]


class UpdateManagerRequest(BaseModel):
    manager_id: str


async def _resolve_attendees(conn, attendee_ids: List[str], org_id: str) -> list:
    if not attendee_ids:
        return []
    rows = await conn.fetch(
        "SELECT id, name, email, role FROM users WHERE id = ANY($1) AND org_id = $2",
        attendee_ids, org_id,
    )
    user_map = {r["id"]: dict(r) for r in rows}
    attendees = []
    for uid in attendee_ids:
        u = user_map.get(uid)
        if u:
            attendees.append({
                "user_id": u["id"], "name": u["name"], "email": u["email"],
                "role": u["role"], "present": True, "reviewed": False, "reviewed_at": None,
            })
    return attendees


def _ensure_list(val, field=""):
    """Return val as a Python list; json.loads if it's a string."""
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return val or []


def _ensure_dict(val):
    """Return val as a Python dict; json.loads if it's a string."""
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return val or {}


def _parse_meeting_row(m: dict) -> dict:
    """Normalize JSONB list/dict fields on a meeting row.
    Only touches keys already present — so list queries that omit heavy
    fields (recording_events, paused_periods, etc.) don't get them re-added.
    """
    for field in ("attendees", "recording_events", "paused_periods", "shared_with", "pii_redactions"):
        if field in m:
            m[field] = _ensure_list(m.get(field))
    for field in ("sign_off_record", "reopen_record"):
        if field in m:
            m[field] = _ensure_dict(m.get(field))
    return m


def _parse_analysis_row(a: dict) -> dict:
    """Normalize JSONB fields on an analysis row."""
    for field in ("actions", "risks", "cqc_mappings", "care_cert_mappings", "custom_mappings", "pii_redactions", "achievements", "learning_needs"):
        a[field] = _ensure_list(a.get(field))
    for field in ("speaker_colors",):
        a[field] = _ensure_dict(a.get(field))
    return a


@router.post("/")
async def create_meeting(data: CreateMeetingRequest, current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    now = datetime.now(timezone.utc).isoformat()
    meeting_id = str(uuid.uuid4())

    # Rate limit: 30 meetings per user / 60 min
    from utils.rate_limit import check_rate_limit
    async with database.with_admin() as _rl_conn:
        await check_rate_limit(
            _rl_conn,
            identifier=f"create_meeting:{current_user['id']}",
            max_attempts=30,
            window_minutes=60,
            error_detail="Meeting creation limit reached. A maximum of 30 meetings can be created per hour.",
        )

    async with database.with_org(org_id) as conn:
        attendees = await _resolve_attendees(conn, data.attendee_ids, org_id)

        # Auto-default the sign-off manager: if it wasn't explicitly chosen and
        # exactly one attendee is a manager/admin, use them. With 0 or 2+
        # managers among the attendees it's ambiguous, so leave it for manual
        # selection as before. This also fixes a downstream bug where a
        # never-selected sign_off_manager_id let a co-attending manager be
        # mistaken for a "shared supervisee" between two different meetings.
        sign_off_manager_id = data.sign_off_manager_id or None
        if not sign_off_manager_id:
            manager_attendees = [a for a in attendees if a.get("role") in ("manager", "admin")]
            if len(manager_attendees) == 1:
                sign_off_manager_id = manager_attendees[0]["user_id"]

        manager_name = None
        if sign_off_manager_id:
            mgr = await conn.fetchrow(
                "SELECT name FROM users WHERE id = $1 AND org_id = $2",
                sign_off_manager_id, org_id,
            )
            if mgr:
                manager_name = mgr["name"]

        await conn.execute(
            """INSERT INTO meetings
               (id, org_id, title, date, location, meeting_type, created_by, created_by_name,
                sign_off_manager_id, sign_off_manager_name, attendees, team_id, setting_id,
                schedule_id, status, recording_events, paused_periods,
                total_paused_duration_seconds, audio_deletion_status, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$20)""",
            meeting_id, org_id, data.title, data.date, data.location, data.meeting_type,
            current_user["id"], current_user.get("name", ""),
            sign_off_manager_id, manager_name,
            attendees,
            current_user.get("team_id"), current_user.get("setting_id"),
            data.schedule_id or None, "draft",
            [], [], 0, "none", now,
        )

    return {
        "id": meeting_id, "org_id": org_id, "title": data.title, "date": data.date,
        "location": data.location, "meeting_type": data.meeting_type,
        "created_by": current_user["id"], "created_by_name": current_user.get("name", ""),
        "sign_off_manager_id": sign_off_manager_id, "sign_off_manager_name": manager_name,
        "attendees": attendees, "status": "draft",
        "recording_events": [], "paused_periods": [], "total_paused_duration_seconds": 0,
        "audio_deletion_status": "none", "created_at": now, "updated_at": now,
    }


@router.get("/")
async def list_meetings(
    request: Request,
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None, ge=1, le=12),
    current_user=Depends(get_current_user_conn),
):
    # PERF: get_current_user_conn() already opened+authenticated a with_org()
    # connection for this exact org_id to fetch the user row above — reuse it
    # here instead of paying for a second, separate with_org() block (see
    # deps.py's docstring). Only safe when the org_id matches exactly; falls
    # back to a fresh block otherwise (_list_meetings_data's default).
    org_id = current_user.get("org_id", "")
    reusable_conn = request.state.db_conn if request.state.db_conn_org_id == org_id else None
    return await _list_meetings_data(current_user, limit=limit, offset=offset, year=year, month=month, reused_conn=reusable_conn)


def _month_bounds(year: int, month: int):
    import calendar as _cal
    start = f"{year:04d}-{month:02d}-01"
    last_day = _cal.monthrange(year, month)[1]
    end = f"{year:04d}-{month:02d}-{last_day:02d}T23:59:59"
    return start, end


async def _list_meetings_data(current_user: dict, limit: int = 500, offset: int = 0, year: int = None, month: int = None, reused_conn=None) -> list:
    """reused_conn: optional already-open with_org() connection for this
    exact org_id (PERF — see get_current_user_conn's docstring), reused ONLY
    in the admin/manager branch below where the caller already guaranteed
    it's scoped to the same org_id. Every other branch is untouched and
    always opens its own fresh block, exactly as before — dashboard.py's
    call site doesn't pass this at all, so it is 100% unaffected."""
    role = current_user["role"]
    if role == "super_admin":
        return []
    org_id = current_user.get("org_id", "")
    user_id = current_user["id"]
    scope = get_manager_scope(current_user)

    date_range = _month_bounds(year, month) if (year and month) else None

    # Attendees / shared_reviewers with no org_id (e.g. some invited users whose
    # org_id was not written during invite acceptance) — bypass RLS and query
    # directly by user_id so they can still see their meetings.
    if role not in ("admin", "manager") and not org_id:
        date_clause = " AND COALESCE(date, created_at) BETWEEN $4 AND $5" if date_range else ""
        async with database.with_admin() as conn:
            rows = await conn.fetch(
                f"""SELECT {_LIST_COLS} FROM meetings
                   WHERE (created_by=$1
                      OR EXISTS (
                          SELECT 1 FROM jsonb_array_elements(
                              CASE
                                  WHEN jsonb_typeof(COALESCE(attendees,'null'::jsonb))='array' THEN attendees
                                  WHEN jsonb_typeof(COALESCE(attendees,'null'::jsonb))='string' THEN (attendees #>> '{{}}')::jsonb
                                  WHEN jsonb_typeof(COALESCE(attendees,'null'::jsonb))='object' AND attendees != '{{}}'::jsonb THEN jsonb_build_array(attendees)
                                  ELSE '[]'::jsonb
                              END
                          ) a WHERE a->>'user_id' = $1::text
                      )
                      OR EXISTS (
                          SELECT 1 FROM jsonb_array_elements(
                              CASE
                                  WHEN jsonb_typeof(COALESCE(shared_with,'null'::jsonb))='array' THEN shared_with
                                  WHEN jsonb_typeof(COALESCE(shared_with,'null'::jsonb))='string' THEN (shared_with #>> '{{}}')::jsonb
                                  WHEN jsonb_typeof(COALESCE(shared_with,'null'::jsonb))='object' AND shared_with != '{{}}'::jsonb THEN jsonb_build_array(shared_with)
                                  ELSE '[]'::jsonb
                              END
                          ) s WHERE s->>'user_id' = $1::text
                      )){date_clause}
                   ORDER BY created_at DESC LIMIT $2 OFFSET $3""",
                user_id, limit, offset, *(date_range or []),
            )
        return [_parse_meeting_row(dict(r)) for r in rows]

    if not org_id:
        return []

    # ── Attendees / shared-reviewers — RLS-enforced, explicit ownership check ──
    # Security: user can only see meetings where their user_id appears in the
    # attendees or shared_with array OR they created the meeting.
    # org_id is guaranteed non-empty here (the null-org_id case is handled by
    # the with_admin() branch above), so with_org(org_id) enforces the exact
    # same org scope as the WHERE org_id=$2 filter below — RLS just adds
    # defence-in-depth on top of the explicit ownership check, it can't hide
    # any row this query would otherwise return.
    if role not in ("admin", "manager"):
        date_clause = " AND COALESCE(date, created_at) BETWEEN $5 AND $6" if date_range else ""
        async with database.with_org(org_id) as conn:
            rows = await conn.fetch(
                f"""SELECT {_LIST_COLS} FROM meetings
                   WHERE org_id = $2
                   AND (
                       created_by = $1
                       OR EXISTS (
                           SELECT 1 FROM jsonb_array_elements(
                               CASE
                                   WHEN jsonb_typeof(COALESCE(attendees,'null'::jsonb))='array' THEN attendees
                                   WHEN jsonb_typeof(COALESCE(attendees,'null'::jsonb))='string' THEN (attendees #>> '{{}}')::jsonb
                                   WHEN jsonb_typeof(COALESCE(attendees,'null'::jsonb))='object' AND attendees != '{{}}'::jsonb THEN jsonb_build_array(attendees)
                                   ELSE '[]'::jsonb
                               END
                           ) a WHERE a->>'user_id' = $1::text
                       )
                       OR EXISTS (
                           SELECT 1 FROM jsonb_array_elements(
                               CASE
                                   WHEN jsonb_typeof(COALESCE(shared_with,'null'::jsonb))='array' THEN shared_with
                                   WHEN jsonb_typeof(COALESCE(shared_with,'null'::jsonb))='string' THEN (shared_with #>> '{{}}')::jsonb
                                   WHEN jsonb_typeof(COALESCE(shared_with,'null'::jsonb))='object' AND shared_with != '{{}}'::jsonb THEN jsonb_build_array(shared_with)
                                   ELSE '[]'::jsonb
                               END
                           ) s WHERE s->>'user_id' = $1::text
                       )
                   ){date_clause}
                   ORDER BY created_at DESC LIMIT $3 OFFSET $4""",
                user_id, org_id, limit, offset, *(date_range or []),
            )
        return [_parse_meeting_row(dict(r)) for r in rows]

    # ── Admins and Managers — use RLS via with_org ────────────────────────────
    async def _run_admin_manager_query(conn):
        if role == "admin":
            date_where = "WHERE COALESCE(date, created_at) BETWEEN $3 AND $4" if date_range else ""
            rows = await conn.fetch(
                f"SELECT {_LIST_COLS} FROM meetings {date_where} ORDER BY created_at DESC LIMIT $1 OFFSET $2",
                limit, offset, *(date_range or []),
            )
            return [_parse_meeting_row(dict(r)) for r in rows]

        elif role == "manager":
            if scope["level"] == "org":
                # Org-level manager sees every meeting in the org
                date_where = "WHERE COALESCE(date, created_at) BETWEEN $3 AND $4" if date_range else ""
                rows = await conn.fetch(
                    f"SELECT {_LIST_COLS} FROM meetings {date_where} ORDER BY created_at DESC LIMIT $1 OFFSET $2",
                    limit, offset, *(date_range or []),
                )
                return [_parse_meeting_row(dict(r)) for r in rows]
            else:
                # Scoped manager — get current team/setting members
                scoped_staff_ids_list = await get_scoped_staff_ids(conn, org_id, scope)
                scoped_staff_ids = set(scoped_staff_ids_list or [])
                # Include the manager themselves so their personally-created meetings appear
                all_scoped = list(scoped_staff_ids | {user_id})

                # Convert UUIDs to strings so text = ANY(text[]) comparisons work
                all_scoped_str = [str(uid) for uid in all_scoped]

                date_clause = " AND COALESCE(date, created_at) BETWEEN $4 AND $5" if date_range else ""
                rows = await conn.fetch(
                    f"""SELECT {_LIST_COLS} FROM meetings
                       WHERE (created_by::text = ANY($1)
                          OR sign_off_manager_id::text = ANY($1)
                          OR EXISTS (
                              SELECT 1 FROM jsonb_array_elements(
                                  CASE
                                      WHEN jsonb_typeof(COALESCE(attendees,'null'::jsonb))='array' THEN attendees
                                      WHEN jsonb_typeof(COALESCE(attendees,'null'::jsonb))='string' THEN (attendees #>> '{{}}')::jsonb
                                      WHEN jsonb_typeof(COALESCE(attendees,'null'::jsonb))='object' AND attendees != '{{}}'::jsonb THEN jsonb_build_array(attendees)
                                      ELSE '[]'::jsonb
                                  END
                              ) a WHERE a->>'user_id' = ANY($1)
                          )){date_clause}
                       ORDER BY created_at DESC LIMIT $2 OFFSET $3""",
                    all_scoped_str, limit, offset, *(date_range or []),
                )
                result = []
                scoped_staff_ids_str = {str(uid) for uid in scoped_staff_ids}
                user_id_str = str(user_id)
                for row in rows:
                    m = _parse_meeting_row(dict(row))
                    attendee_ids = {str(a.get("user_id", "")) for a in m.get("attendees", [])}
                    # Staff attendees = everyone except the manager themselves
                    staff_attendees = attendee_ids - {user_id_str}
                    if staff_attendees:
                        # Historical if NONE of the staff attendees are still in scope
                        m["is_historical"] = len(staff_attendees & scoped_staff_ids_str) == 0
                    else:
                        m["is_historical"] = False
                    result.append(m)
                return result

        else:
            return []  # safety fallback; all non-admin/manager roles are handled above

    # PERF: reuse the caller-supplied connection (already open, same org_id,
    # via get_current_user_conn) when available instead of opening a second
    # with_org() block for the exact same org context — see reused_conn's
    # docstring above. Falls back to a fresh block exactly as before
    # whenever no reusable connection was supplied (e.g. dashboard.py).
    if reused_conn is not None:
        return await _run_admin_manager_query(reused_conn)
    async with database.with_org(org_id) as conn:
        return await _run_admin_manager_query(conn)


# Month names for the collapsed month-divider rows on the Meetings page.
_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


async def _month_summary_data(current_user: dict, reused_conn=None) -> list:
    """Shared logic behind GET /meetings/month-summary — extracted so the
    combined GET /meetings/page-data endpoint can call it directly, reusing
    the SAME already-open connection instead of opening a separate block.
    reused_conn: optional already-open with_org() connection for this exact
    org_id (only used in the admin/manager branch, same guarantee as
    _list_meetings_data's reused_conn — see get_current_user_conn's docstring)."""
    role = current_user["role"]
    if role == "super_admin":
        return []
    org_id = current_user.get("org_id", "")
    user_id = current_user["id"]
    scope = get_manager_scope(current_user)

    now = datetime.now(timezone.utc)
    current_month_key = f"{now.year:04d}-{now.month:02d}"
    month_expr = "to_char(date_trunc('month', COALESCE(date, created_at)), 'YYYY-MM')"

    if role not in ("admin", "manager") and not org_id:
        async with database.with_admin() as conn:
            rows = await conn.fetch(
                f"""SELECT {month_expr} AS month_key, status, COUNT(*) AS n FROM meetings
                   WHERE created_by=$1
                      OR EXISTS (SELECT 1 FROM jsonb_array_elements(
                          CASE WHEN jsonb_typeof(COALESCE(attendees,'null'::jsonb))='array' THEN attendees ELSE '[]'::jsonb END
                      ) a WHERE a->>'user_id' = $1::text)
                   GROUP BY month_key, status""",
                user_id,
            )
    elif not org_id:
        return []
    elif role not in ("admin", "manager"):
        async with database.with_org(org_id) as conn:
            rows = await conn.fetch(
                f"""SELECT {month_expr} AS month_key, status, COUNT(*) AS n FROM meetings
                   WHERE org_id = $2 AND (
                       created_by = $1
                       OR EXISTS (SELECT 1 FROM jsonb_array_elements(
                           CASE WHEN jsonb_typeof(COALESCE(attendees,'null'::jsonb))='array' THEN attendees ELSE '[]'::jsonb END
                       ) a WHERE a->>'user_id' = $1::text)
                   )
                   GROUP BY month_key, status""",
                user_id, org_id,
            )
    else:
        async def _run_admin_manager_month_summary(conn):
            if role == "admin" or scope["level"] == "org":
                return await conn.fetch(
                    f"SELECT {month_expr} AS month_key, status, COUNT(*) AS n FROM meetings GROUP BY month_key, status"
                )
            scoped_staff_ids_list = await get_scoped_staff_ids(conn, org_id, scope)
            all_scoped_str = [str(uid) for uid in (set(scoped_staff_ids_list or []) | {user_id})]
            return await conn.fetch(
                f"""SELECT {month_expr} AS month_key, status, COUNT(*) AS n FROM meetings
                   WHERE created_by::text = ANY($1)
                      OR sign_off_manager_id::text = ANY($1)
                      OR EXISTS (SELECT 1 FROM jsonb_array_elements(
                          CASE WHEN jsonb_typeof(COALESCE(attendees,'null'::jsonb))='array' THEN attendees ELSE '[]'::jsonb END
                      ) a WHERE a->>'user_id' = ANY($1))
                   GROUP BY month_key, status""",
                all_scoped_str,
            )

        # PERF: reuse the caller-supplied connection (already open, same
        # org_id) when available instead of opening a second with_org()
        # block — see get_current_user_conn's docstring. Falls back to a
        # fresh block otherwise, exactly as before.
        if reused_conn is not None:
            rows = await _run_admin_manager_month_summary(reused_conn)
        else:
            async with database.with_org(org_id) as conn:
                rows = await _run_admin_manager_month_summary(conn)

    months = {}
    for r in rows:
        mk = r["month_key"]
        if not mk or mk == current_month_key:
            continue
        months.setdefault(mk, {"count": 0, "status_counts": {}})
        months[mk]["count"] += r["n"]
        months[mk]["status_counts"][r["status"]] = months[mk]["status_counts"].get(r["status"], 0) + r["n"]

    result = []
    for mk, data in months.items():
        y, m = mk.split("-")
        result.append({
            "year": int(y), "month": int(m), "month_key": mk,
            "label": f"{_MONTH_NAMES[int(m)]} {y}",
            "count": data["count"], "status_counts": data["status_counts"],
        })
    result.sort(key=lambda x: x["month_key"], reverse=True)
    return result


@router.get("/month-summary")
async def get_month_summary(request: Request, current_user=Depends(get_current_user_conn)):
    """
    Cheap GROUP BY month+status count, used to render collapsed month-divider
    rows on the Meetings page without fetching full meeting rows for every
    past month. Excludes the current calendar month (fetched in full instead).
    """
    org_id = current_user.get("org_id", "")
    reused_conn = request.state.db_conn if request.state.db_conn_org_id == org_id else None
    return await _month_summary_data(current_user, reused_conn=reused_conn)


@router.get("/page-data")
async def get_meetings_page_data(
    request: Request,
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None, ge=1, le=12),
    current_user=Depends(get_current_user_conn),
):
    """PERF: combines the Meetings page's 3 initial-load calls — current
    month's meetings, the collapsed-month summary, and the Setting/Team
    filter dropdown data — into ONE request. Each sub-fetch below is the
    exact same helper/logic used by the standalone /meetings/,
    /meetings/month-summary and /org/structure-lite endpoints (all left in
    place, unchanged, for any other caller) — just run against the SAME
    already-open connection instead of each opening (and paying for) its
    own separate auth-check + transaction."""
    org_id = current_user.get("org_id", "")
    reused_conn = request.state.db_conn if request.state.db_conn_org_id == org_id else None

    meetings = await _list_meetings_data(current_user, limit=500, offset=0, year=year, month=month, reused_conn=reused_conn)
    month_summary = await _month_summary_data(current_user, reused_conn=reused_conn)
    org_structure = await get_structure_lite_data(current_user, reused_conn=reused_conn)

    return {"meetings": meetings, "month_summary": month_summary, "org_structure": org_structure}


@router.get("/{meeting_id}")
async def get_meeting(meeting_id: str, current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    user_id = current_user.get("id", "")

    async with database.with_org(org_id) as conn:
        row = await conn.fetchrow(f"SELECT {_DETAIL_COLS} FROM meetings WHERE id = $1", meeting_id)
        if not row:
            raise HTTPException(status_code=404, detail="Meeting not found")
        meeting = _parse_meeting_row(dict(row))

        # Access check: attendees and shared_with reviewers can read their own meetings.
        if current_user["role"] not in ["admin", "manager", "super_admin"]:
            attendee_ids = [a.get("user_id", "") for a in meeting["attendees"]]
            shared_with = meeting["shared_with"]
            is_shared_with_user = any(isinstance(s, dict) and s.get("user_id") == user_id for s in shared_with)
            if user_id not in attendee_ids and not is_shared_with_user and user_id != meeting.get("created_by", ""):
                raise HTTPException(status_code=404, detail="Meeting not found")

        # SEC-002: scoped managers (team/setting level) may only read meetings
        # where at least one participant is within their assigned scope.
        elif current_user["role"] == "manager":
            scope = get_manager_scope(current_user)
            if scope["level"] != "org":
                scoped_ids_list = await get_scoped_staff_ids(conn, org_id, scope)
                scoped_str = {str(sid) for sid in (scoped_ids_list or [])} | {str(user_id)}
                attendee_ids = {a.get("user_id", "") for a in meeting["attendees"]}
                creator = str(meeting.get("created_by", ""))
                if not (attendee_ids & scoped_str) and creator not in scoped_str:
                    raise HTTPException(status_code=404, detail="Meeting not found")

        # Attach transcript
        if meeting.get("transcript_id"):
            t_row = await conn.fetchrow(f"SELECT {_TRANSCRIPT_DETAIL_COLS} FROM transcripts WHERE id = $1", meeting["transcript_id"])
            if t_row:
                tr = dict(t_row)
                tr["safety_warnings"] = _ensure_list(tr.get("safety_warnings"))
                tr["speaker_colors"] = _ensure_dict(tr.get("speaker_colors"))
                # speaker_text is the diarised view; raw text is ~50 KB and
                # lazy-loaded on demand via GET /{id}/transcript-text.
                if tr.get("speaker_text"):
                    tr.pop("text", None)
                meeting["transcript"] = tr

        # Attach analysis
        if meeting.get("analysis_id"):
            a_row = await conn.fetchrow(f"SELECT {_ANALYSIS_DETAIL_COLS} FROM analyses WHERE id = $1", meeting["analysis_id"])
            if a_row:
                meeting["analysis"] = _parse_analysis_row(dict(a_row))

        # Attach comments
        c_rows = await conn.fetch(
            "SELECT id, user_id, user_name, role, text, created_at FROM reviewer_comments WHERE meeting_id = $1 ORDER BY created_at ASC",
            meeting_id,
        )
        meeting["comments"] = [dict(c) for c in c_rows]

    # Enrich attendee emails from live user accounts — single batch query (no N+1)
    if meeting.get("attendees"):
        async with database.with_admin() as conn:
            attendee_uids = [a.get("user_id") for a in meeting["attendees"] if a.get("user_id")]
            created_by_id = meeting.get("created_by")
            all_uids = list({uid for uid in attendee_uids + ([created_by_id] if created_by_id else [])})

            user_rows = await conn.fetch(
                "SELECT id, email, name FROM users WHERE id = ANY($1::uuid[])", all_uids
            ) if all_uids else []
            user_map = {str(r["id"]): r for r in user_rows}

            meeting["attendees"] = [
                {**a, "email": user_map[a["user_id"]]["email"]}
                if a.get("user_id") and a["user_id"] in user_map and user_map[a["user_id"]]["email"]
                else a
                for a in meeting["attendees"]
            ]

            if created_by_id and created_by_id in user_map:
                creator = user_map[created_by_id]
                meeting["created_by_email"] = creator["email"]
                meeting["created_by_name"] = meeting.get("created_by_name") or creator["name"]

    # Apply PII redactions
    from routers.review import _apply_redactions_to_text, _apply_redactions_deep, _has_privileged_access
    redactions = meeting.get("pii_redactions") or []
    if redactions and meeting.get("transcript"):
        t = meeting["transcript"]
        if t.get("speaker_text"):
            t["speaker_text"] = _apply_redactions_to_text(t["speaker_text"], redactions)
        if not _has_privileged_access(meeting, user_id) and t.get("text"):
            t["text"] = _apply_redactions_to_text(t["text"], redactions)
    if redactions:
        if not _has_privileged_access(meeting, user_id):
            meeting.pop("pii_redactions", None)
            meeting["pii_redactions_count"] = len(redactions)
    if meeting.get("analysis") and redactions:
        meeting["analysis"] = _apply_redactions_deep(meeting["analysis"], redactions)

    # Surface a mismatch between the declared meeting date and when it was
    # actually recorded (never blocks anything — see utils/backdate_check.py).
    # Purely derived from data already fetched above, no extra query.
    first_start_ts = next(
        (ev.get("timestamp") for ev in meeting.get("recording_events", []) if ev.get("type") == "started"),
        None,
    )
    date_mismatch = detect_backdate_mismatch(meeting.get("date"), first_start_ts)
    meeting["date_flagged"] = bool(date_mismatch)
    meeting["date_flag_detail"] = date_mismatch

    return meeting


@router.put("/{meeting_id}/attendees")
async def update_attendees(meeting_id: str, data: UpdateAttendeesRequest, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        attendees = await _resolve_attendees(conn, data.attendee_ids, org_id)
        result = await conn.execute(
            "UPDATE meetings SET attendees=$1, updated_at=$2 WHERE id=$3",
            attendees, datetime.now(timezone.utc).isoformat(), meeting_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Meeting not found")
    return {"message": "Attendees updated"}


@router.put("/{meeting_id}/manager")
async def update_manager(meeting_id: str, data: UpdateManagerRequest, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        mgr = await conn.fetchrow("SELECT name FROM users WHERE id = $1 AND org_id = $2", data.manager_id, org_id)
        if not mgr:
            raise HTTPException(status_code=404, detail="Manager not found")
        await conn.execute(
            """UPDATE meetings SET sign_off_manager_id=$1, sign_off_manager_name=$2, updated_at=$3
               WHERE id=$4""",
            data.manager_id, mgr["name"], datetime.now(timezone.utc).isoformat(), meeting_id,
        )
    return {"message": "Manager updated"}


@router.delete("/{meeting_id}")
async def delete_meeting(meeting_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        # Any audio must be deleted from storage too — fetch its path before the row
        # disappears. delete_audio() is idempotent on an already-removed path, so it's
        # safe to always attempt this rather than trust an is_deleted flag that could
        # be stale if an earlier purge silently failed.
        audio_paths = [
            r["storage_path"] for r in await conn.fetch(
                "SELECT storage_path FROM audio_files WHERE meeting_id=$1 AND storage_path IS NOT NULL",
                meeting_id,
            )
        ]
        result = await conn.execute("DELETE FROM meetings WHERE id = $1", meeting_id)
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="Meeting not found")
        # Cascade deletes — redundant with the FK ON DELETE CASCADE constraints now in
        # place, kept here as a defence-in-depth safety net matching existing convention.
        for table in ["transcripts", "analyses", "audio_files", "reviewer_comments", "review_edits", "audit_logs", "evidence_feedback", "jobs"]:
            await conn.execute(f"DELETE FROM {table} WHERE meeting_id = $1", meeting_id)
    for path in audio_paths:
        try:
            await delete_audio(path)
        except Exception as e:
            logger.error(f"Failed to delete audio from storage for meeting {meeting_id}: path={path} error={e}")
    return {"message": "Meeting deleted"}



@router.get("/{meeting_id}/transcript-text")
async def get_transcript_text(meeting_id: str, current_user=Depends(get_current_user)):
    """Lazy-load endpoint: returns only the raw transcript text for the Full Text view.
    The main GET /{id} strips this field when speaker_text is present to save ~50 KB."""
    org_id = current_user.get("org_id", "")
    user_id = current_user.get("id", "")

    async with database.with_org(org_id) as conn:
        row = await conn.fetchrow(
            "SELECT attendees, shared_with, created_by, transcript_id, pii_redactions FROM meetings WHERE id = $1",
            meeting_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        meeting = _parse_meeting_row(dict(row))

        # Access check (mirrors get_meeting)
        if current_user["role"] not in ["admin", "manager", "super_admin"]:
            attendee_ids = [a.get("user_id", "") for a in meeting["attendees"]]
            shared_with = meeting["shared_with"]
            is_shared = any(isinstance(s, dict) and s.get("user_id") == user_id for s in shared_with)
            if user_id not in attendee_ids and not is_shared and user_id != meeting.get("created_by", ""):
                raise HTTPException(status_code=404, detail="Not found")

        if not meeting.get("transcript_id"):
            raise HTTPException(status_code=404, detail="No transcript")

        t_row = await conn.fetchrow(
            "SELECT text FROM transcripts WHERE id = $1",
            meeting["transcript_id"],
        )

    if not t_row or not t_row["text"]:
        raise HTTPException(status_code=404, detail="Transcript text not available")

    text = t_row["text"]

    # Apply PII redactions for non-privileged users (same as main meeting endpoint)
    from routers.review import _apply_redactions_to_text, _has_privileged_access
    redactions = meeting.get("pii_redactions") or []
    if redactions and not _has_privileged_access(meeting, user_id):
        text = _apply_redactions_to_text(text, redactions)

    return {"text": text}
