import json
import os
import uuid
import re as _re
import logging
import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, BackgroundTasks, Form, Request
from pydantic import BaseModel, EmailStr
from fastapi.responses import Response as _Response
from deps import get_db, get_current_user, get_manager_scope, get_scoped_staff_ids
from utils.supabase_storage import put_document, get_document as _storage_get_document, delete_document as _storage_delete_document, delete_audio as _storage_delete_audio
from utils.redaction import apply_redactions_deep as _apply_redactions_deep
from utils.redaction import apply_redactions_to_text as _apply_redactions_to_text
import database

# ── Admin stats cache ─────────────────────────────────────────────────────────
# 5 COUNT(*) queries per org — cached for 60 s. Keyed by org_id.
_stats_cache: dict[str, tuple[float, dict]] = {}
_STATS_TTL = 60  # seconds

async def _audit(conn, meeting_id: str, org_id: str, action: str, user_id: str, user_name: str, detail: str = ""):
    """Write one audit log entry (works with both org and admin connections)."""
    await conn.execute(
        "INSERT INTO audit_logs (id, meeting_id, org_id, action, user_id, user_name, detail, timestamp) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
        str(uuid.uuid4()), meeting_id, org_id, action, user_id, user_name, detail,
        datetime.now(timezone.utc),
    )


router = APIRouter()
logger = logging.getLogger(__name__)


def _jlist(val):
    """Parse a JSONB value that asyncpg may return as a raw string when RLS role is active."""
    if isinstance(val, list): return val
    if isinstance(val, str):
        try: return json.loads(val)
        except Exception: return []
    return val or []


def _jdict(val):
    """Parse a JSONB value (dict-typed) that asyncpg may stringify under RLS."""
    if isinstance(val, dict): return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, dict) else {}
        except Exception: return {}
    return val if isinstance(val, dict) else {}


def _ref_nums(ref: str):
    return [int(n) for n in _re.findall(r'\d+', ref)] or [0]


# ── User management ───────────────────────────────────────────────────────────

class CreateUserRequest(BaseModel):
    email: EmailStr
    name: str
    role: str
    password: str


class UpdateUserRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    mfa_enabled: Optional[bool] = None


class ResetPasswordRequest(BaseModel):
    new_password: str


@router.get("/users")
async def list_users(ignore_scope: bool = False, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user.get("org_id", "")

    # Scope is always derived server-side from the caller's team/setting assignment.
    # ignore_scope is honoured only for admins — never for team/setting-scoped managers
    # (prevents SEC-001: scope-bypass via ?ignore_scope=true URL flag).
    base_scope = get_manager_scope(current_user)
    if ignore_scope and current_user["role"] == "admin":
        scope = {"level": "org"}
    else:
        scope = base_scope

    _cols = "SELECT id, org_id, email, name, role, is_active, mfa_enabled, team_id, setting_id, created_at FROM users"
    async with database.with_org(org_id) as conn:
        if scope["level"] == "team":
            rows = await conn.fetch(
                f"{_cols} WHERE org_id=$1 AND team_id=$2 ORDER BY name ASC",
                org_id, scope["team_id"],
            )
        elif scope["level"] == "setting":
            rows = await conn.fetch(
                f"{_cols} WHERE org_id=$1 AND setting_id=$2 ORDER BY name ASC",
                org_id, scope["setting_id"],
            )
        else:
            rows = await conn.fetch(
                f"{_cols} WHERE org_id=$1 ORDER BY name ASC", org_id,
            )
    return [dict(r) for r in rows]


@router.post("/users")
async def create_user(data: CreateUserRequest, current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    from routers.auth import hash_password
    from utils import supabase_auth
    role = data.role if data.role in ["admin", "manager", "attendee", "shared_reviewer"] else "attendee"
    user_id = str(uuid.uuid4())
    org_id = current_user.get("org_id", "")
    now = datetime.now(timezone.utc)
    async with database.with_admin() as conn:
        existing = await conn.fetchrow("SELECT id FROM users WHERE email = $1", data.email.lower())
        if existing:
            raise HTTPException(400, "Email already exists")
        await conn.execute(
            "INSERT INTO users (id, email, password_hash, name, role, org_id, is_active, must_change_password, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)",
            user_id, data.email.lower(), await hash_password(data.password), data.name, role, org_id, True, True, now,
        )
        try:
            await supabase_auth.create_user(user_id, data.email.lower())
            await supabase_auth.set_password(user_id, data.password)
            await conn.execute("UPDATE users SET supabase_migrated=TRUE, supabase_password_set=TRUE WHERE id=$1", user_id)
        except Exception as exc:
            # Non-fatal: user can still log in via the bcrypt fallback until
            # this is retried (see routers/auth.py login's supabase_password_set check).
            logger.error("Supabase Auth provisioning failed for new user %s: %s", data.email, exc)
    return {"id": user_id, "email": data.email.lower(), "name": data.name, "role": role}


@router.put("/users/{user_id}")
async def update_user(user_id: str, data: UpdateUserRequest, current_user=Depends(get_current_user)):
    if current_user["role"] not in ("admin", "manager"):
        raise HTTPException(403, "Admin/Manager only")
    org_id = current_user.get("org_id", "")

    # SEC-003: Fetch target user's role before applying any changes
    async with database.with_org(org_id) as conn:
        target = await conn.fetchrow("SELECT id, role FROM users WHERE id = $1 AND org_id = $2", user_id, org_id)
    if not target:
        raise HTTPException(404, "User not found")

    target_role = target["role"] or ""

    # Managers cannot edit admin or super_admin users at all
    if current_user["role"] == "manager" and target_role in ("admin", "super_admin"):
        raise HTTPException(403, "Managers cannot modify admin accounts")

    # Admins cannot modify super_admin accounts
    if current_user["role"] == "admin" and target_role == "super_admin":
        raise HTTPException(403, "Cannot modify a super admin account")

    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(400, "No update data provided")
    if "email" in update_data:
        update_data["email"] = update_data["email"].lower().strip()
    # Managers cannot promote/demote roles or change email
    if current_user["role"] == "manager":
        update_data.pop("role", None)
        update_data.pop("email", None)   # SEC-003: prevent email hijack via manager
    # SEC-001: admins may only assign org-level roles — never super_admin, and
    # never to themselves (prevents privilege-escalation via a crafted role value)
    if "role" in update_data and current_user["role"] == "admin":
        if update_data["role"] not in ("admin", "manager", "attendee", "shared_reviewer"):
            raise HTTPException(403, "Cannot assign that role")
        if user_id == current_user["id"]:
            raise HTTPException(403, "Cannot change your own role")

    set_parts = [f"{k}=${i+2}" for i, k in enumerate(update_data.keys())]
    async with database.with_admin() as conn:
        # Email-uniqueness check is genuinely global (must see all orgs) — stays with_admin()
        if "email" in update_data:
            clash = await conn.fetchrow("SELECT id FROM users WHERE email = $1 AND id <> $2", update_data["email"], user_id)
            if clash:
                raise HTTPException(400, "Email address already in use")
        # Hardening: org_id filter added for defense-in-depth even though target
        # was already confirmed to belong to org_id above
        await conn.execute(
            f"UPDATE users SET {', '.join(set_parts)} WHERE id=$1 AND org_id=${len(update_data) + 2}",
            user_id, *list(update_data.values()), org_id,
        )
    return {"message": "User updated"}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, current_user=Depends(get_current_user)):
    """Revoke a pending invite (must_change_password=true) or deactivate user.
    Admin + manager (within their own team/setting scope, never admins)."""
    if current_user["role"] not in ("admin", "manager"):
        raise HTTPException(403, "Admin or manager only")
    if user_id == current_user["id"]:
        raise HTTPException(400, "You cannot deactivate your own account")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        u = await conn.fetchrow(
            "SELECT id, name, email, role, team_id, setting_id, must_change_password FROM users WHERE id=$1 AND org_id=$2",
            user_id, org_id,
        )
        if not u:
            raise HTTPException(404, "User not found")
        if current_user["role"] == "manager":
            if u["role"] == "admin":
                raise HTTPException(403, "Outside your management scope")
            scope = get_manager_scope(current_user)
            if scope["level"] == "team" and u["team_id"] != scope["team_id"]:
                raise HTTPException(403, "Outside your management scope")
            if scope["level"] == "setting" and u["setting_id"] != scope["setting_id"]:
                raise HTTPException(403, "Outside your management scope")
        if u["must_change_password"]:
            # Pending invite — safe to delete entirely
            await conn.execute("DELETE FROM invitations WHERE user_id=$1", user_id)
            await conn.execute("DELETE FROM users WHERE id=$1", user_id)
            await _audit(conn, None, org_id, "invite_revoked", current_user["id"], current_user.get("name", ""),
                         f"Revoked pending invite for {u['name']} ({u['email']})")
        else:
            # Active user — just deactivate
            await conn.execute("UPDATE users SET is_active=FALSE WHERE id=$1", user_id)
            await _audit(conn, None, org_id, "user_deactivated", current_user["id"], current_user.get("name", ""),
                         f"Deactivated {u['name']} ({u['email']})")
    return {"message": "User removed"}


@router.delete("/users/{user_id}/hard-delete")
async def hard_delete_user(user_id: str, current_user=Depends(get_current_user)):
    """GDPR-style permanent erasure. Admin only, irreversible. Deletes the
    account plus everything that's THEIRS: meetings where they were the
    supervision subject (transcript/audio/analysis/comments/etc, mirroring
    delete_meeting()'s cascade), their own uploaded documents, their schedule,
    their invitation row, and the underlying storage files. Meetings where
    they merely conducted/reviewed supervision for a DIFFERENT, still-active
    person are deliberately left alone — those belong to that other person's
    record, not this one; the existing ON DELETE SET NULL FKs on
    created_by/sign_off_manager_id/manager_user_id/supervisor_user_id clear
    just this user's reference on those (their frozen "_name" snapshot, if
    any, is untouched).
    Requires the account to already be deactivated (is_active=FALSE) — per the
    org's process, admins deactivate first, export/download anything needed,
    THEN hard-delete; you cannot skip straight from active to permanently gone."""
    if current_user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    if user_id == current_user["id"]:
        raise HTTPException(400, "You cannot delete your own account")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        target = await conn.fetchrow("SELECT id, name, email, is_active FROM users WHERE id=$1 AND org_id=$2", user_id, org_id)
        if not target:
            raise HTTPException(404, "User not found")
        if target["is_active"]:
            raise HTTPException(400, "Deactivate this user first, then permanently delete them once you've exported anything you need to keep")

        meeting_ids = [r["id"] for r in await conn.fetch(
            "SELECT id FROM meetings WHERE attendees @> $1::jsonb",
            [{"user_id": user_id, "role": "attendee"}],
        )]
        audio_paths = []
        if meeting_ids:
            audio_paths = [
                r["storage_path"] for r in await conn.fetch(
                    "SELECT storage_path FROM audio_files WHERE meeting_id = ANY($1::uuid[]) AND storage_path IS NOT NULL",
                    meeting_ids,
                )
            ]
            await conn.execute("DELETE FROM meetings WHERE id = ANY($1::uuid[])", meeting_ids)
            # Redundant with FK ON DELETE CASCADE, kept as a defence-in-depth
            # safety net matching delete_meeting()'s existing convention.
            # All of these meeting_id columns are native UUID (verified live
            # via information_schema.columns — a prior comment here claiming
            # they were TEXT was wrong for this database, which silently
            # made every one of these DELETEs a no-op: uuid = text has no
            # operator in Postgres, so each statement would raise, except it
            # was never even reached because meeting_ids was always empty —
            # see the json.dumps() fix above).
            for table in ["transcripts", "analyses", "audio_files", "reviewer_comments", "review_edits",
                          "audit_logs", "evidence_feedback", "jobs", "meeting_prep", "need_review_signals"]:
                await conn.execute(f"DELETE FROM {table} WHERE meeting_id = ANY($1::uuid[])", meeting_ids)

        upload_paths = [
            r["storage_path"] for r in await conn.fetch(
                "SELECT storage_path FROM supervision_uploads WHERE (staff_id=$1 OR uploader_id=$1) AND storage_path IS NOT NULL",
                user_id,
            )
        ]
        await conn.execute("DELETE FROM supervision_uploads WHERE staff_id=$1 OR uploader_id=$1", user_id)
        await conn.execute("DELETE FROM schedules WHERE staff_user_id=$1", user_id)
        await conn.execute("DELETE FROM invitations WHERE user_id=$1", user_id)
        await conn.execute("DELETE FROM users WHERE id=$1", user_id)
        await _audit(conn, None, org_id, "user_hard_deleted", current_user["id"], current_user.get("name", ""),
                     f"Permanently deleted {target['name']} ({target['email']}) — {len(meeting_ids)} meeting(s) removed")

    for path in audio_paths:
        try:
            await _storage_delete_audio(path)
        except Exception as e:
            logger.error(f"Failed to delete audio from storage during hard-delete of user {user_id}: path={path} error={e}")
    for path in upload_paths:
        try:
            await _storage_delete_document(path)
        except Exception as e:
            logger.error(f"Failed to delete document from storage during hard-delete of user {user_id}: path={path} error={e}")

    return {"message": "User permanently deleted", "meetings_deleted": len(meeting_ids)}


@router.get("/activity-log")
async def get_activity_log(current_user=Depends(get_current_user)):
    """Org-wide staff lifecycle activity (Deactivate/Hard Delete/invite revocations).
    Admin only. Distinct from the per-meeting Audit Trail tab — these events aren't
    tied to a single meeting, so they're stored with meeting_id=NULL and surfaced
    on their own 'Activity Log' tab in Organisation Settings instead."""
    if current_user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        rows = await conn.fetch(
            """SELECT id, action, user_name, detail, timestamp FROM audit_logs
               WHERE org_id=$1 AND meeting_id IS NULL
               ORDER BY timestamp DESC LIMIT 200""",
            org_id,
        )
    return [
        {"id": r["id"], "action": r["action"], "actor_name": r["user_name"],
         "detail": r["detail"], "timestamp": str(r["timestamp"] or "")}
        for r in rows
    ]



@router.post("/users/{user_id}/reset-password")
async def reset_user_password(user_id: str, data: ResetPasswordRequest, current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    from routers.auth import hash_password, validate_password_strength
    validate_password_strength(data.new_password)
    org_id = current_user.get("org_id", "")
    now = datetime.now(timezone.utc)
    async with database.with_org(org_id) as conn:
        u = await conn.fetchrow("SELECT id, email, supabase_password_set FROM users WHERE id = $1 AND org_id = $2", user_id, org_id)
        if not u:
            raise HTTPException(404, "User not found")

        from utils import supabase_auth
        try:
            await supabase_auth.create_user(str(u["id"]), u["email"])  # no-op if already provisioned
            await supabase_auth.set_password(str(u["id"]), data.new_password)
            supabase_ok = True
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("Supabase Auth password set failed for %s: %s", u["email"], exc)
            supabase_ok = False

        if u["supabase_password_set"] and not supabase_ok:
            # Login checks Supabase first for this user — silently updating only
            # bcrypt would strand them on their OLD Supabase password. Fail loudly.
            raise HTTPException(status_code=503, detail="Unable to reset this user's password right now. Please try again shortly.")

        await conn.execute(
            """UPDATE users SET password_hash=$1, must_change_password=TRUE, password_changed_at=$2,
               supabase_migrated=(supabase_migrated OR $4), supabase_password_set=(supabase_password_set OR $4)
               WHERE id=$3""",
            await hash_password(data.new_password), now, user_id, supabase_ok,
        )
    return {"message": "Password reset successfully"}


# ── Standards ─────────────────────────────────────────────────────────────────

class CreateStandardRequest(BaseModel):
    type: str
    reference: str
    name: str
    description: str
    keywords: list = []
    source: Optional[str] = None


@router.get("/standards")
async def list_standards(type: Optional[str] = None, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Admin/Manager only")
    org_id = current_user.get("org_id", "")

    async with database.with_org(org_id) as conn:
        # Get org jurisdiction and service_type to filter system standards correctly
        org_row = await conn.fetchrow("SELECT jurisdiction, service_type FROM organisations WHERE id=$1", org_id)
        jurisdiction = (org_row["jurisdiction"] if org_row else None) or "england"
        org_service_type = (org_row["service_type"] if org_row else None)

        if jurisdiction == "northern_ireland":
            # NI: RQIA standards filtered by service_type, NISCC (service_type=NULL) always shown
            if type:
                rows = await conn.fetch(
                    """SELECT id, type, reference, name, description, sub_outcomes FROM standards_entries
                       WHERE type=$1 AND is_active=TRUE
                       AND ((is_system=TRUE AND jurisdiction='northern_ireland'
                             AND (service_type IS NULL OR service_type=$2))
                            OR org_id=$3)
                       ORDER BY type, reference""",
                    type, org_service_type, org_id,
                )
            else:
                rows = await conn.fetch(
                    """SELECT id, type, reference, name, description, sub_outcomes FROM standards_entries
                       WHERE is_active=TRUE
                       AND ((is_system=TRUE AND jurisdiction='northern_ireland'
                             AND (service_type IS NULL OR service_type=$1))
                            OR org_id=$2)
                       ORDER BY type, reference""",
                    org_service_type, org_id,
                )
        elif jurisdiction == "ofsted":
            # Ofsted: every system entry has a service_type (early_years/childrens_home/school) — exact match
            if type:
                rows = await conn.fetch(
                    """SELECT id, type, reference, name, description, sub_outcomes FROM standards_entries
                       WHERE type=$1 AND is_active=TRUE
                       AND ((is_system=TRUE AND jurisdiction='ofsted' AND service_type=$2) OR org_id=$3)
                       ORDER BY type, reference""",
                    type, org_service_type, org_id,
                )
            else:
                rows = await conn.fetch(
                    """SELECT id, type, reference, name, description, sub_outcomes FROM standards_entries
                       WHERE is_active=TRUE
                       AND ((is_system=TRUE AND jurisdiction='ofsted' AND service_type=$1) OR org_id=$2)
                       ORDER BY type, reference""",
                    org_service_type, org_id,
                )
        elif type:
            rows = await conn.fetch(
                """SELECT id, type, reference, name, description, sub_outcomes FROM standards_entries
                   WHERE type=$1 AND is_active=TRUE
                   AND ((is_system=TRUE AND jurisdiction=$2) OR org_id=$3)
                   ORDER BY type, reference""",
                type, jurisdiction, org_id,
            )
        else:
            rows = await conn.fetch(
                """SELECT id, type, reference, name, description, sub_outcomes FROM standards_entries
                   WHERE is_active=TRUE
                   AND ((is_system=TRUE AND jurisdiction=$1) OR org_id=$2)
                   ORDER BY type, reference""",
                jurisdiction, org_id,
            )
    return [dict(r) for r in rows]


@router.post("/standards")
async def create_standard(data: CreateStandardRequest, current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    std_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        await conn.execute(
            """INSERT INTO standards_entries (id, type, reference, name, description, keywords, source,
               is_active, is_system, org_id, created_at, created_by)
               VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9,$10,$11,$12)""",
            std_id, data.type, data.reference, data.name, data.description,
            data.keywords, data.source or "", True, False, org_id, now, current_user["id"],
        )
    return {"id": std_id, "type": data.type, "reference": data.reference, "name": data.name,
            "description": data.description, "org_id": org_id}


@router.delete("/standards/{standard_id}")
async def delete_standard(standard_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    org_id = current_user.get("org_id", "")
    # SEC-001: with_org() so RLS (org_id=current_org) rejects other orgs' standards
    async with database.with_org(org_id) as conn:
        entry = await conn.fetchrow("SELECT id, is_system FROM standards_entries WHERE id = $1", standard_id)
        if not entry:
            raise HTTPException(404, "Standard not found")
        if entry["is_system"]:
            raise HTTPException(403, "System standards cannot be deleted")
        await conn.execute("UPDATE standards_entries SET is_active=FALSE WHERE id=$1", standard_id)
    return {"message": "Standard deactivated"}


# ── Standards documents ───────────────────────────────────────────────────────

@router.get("/standards/documents")
async def list_documents(current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Admin/Manager only")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        rows = await conn.fetch(
            "SELECT id, label, filename, size_bytes, created_at, document_summary, parse_status, "
            "extracted_criteria, is_active FROM standards_documents ORDER BY created_at DESC"
        )
    return [dict(r) for r in rows]


@router.post("/standards/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    label: str = Form(""),
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Admin/Manager only")
    file_data = await file.read()
    if len(file_data) == 0:
        raise HTTPException(400, "Empty file")
    if len(file_data) > 25 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 25 MB)")
    allowed_ext = {"pdf", "docx", "txt", "md", "csv"}
    file_ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "txt"
    if file_ext not in allowed_ext:
        raise HTTPException(400, f"Unsupported file type: .{file_ext}")
    # Validate actual file content — reject extension-spoofed executables/scripts
    from utils.file_security import validate_upload, guard_zip_bomb
    try:
        canonical_mime = validate_upload(file_data, file_ext)
        if file_ext in ("docx", "xlsx", "pptx"):
            guard_zip_bomb(file_data)
    except ValueError as e:
        raise HTTPException(400, str(e))

    storage_path = f"standards/docs/{uuid.uuid4()}.{file_ext}"
    try:
        result = await put_document(storage_path, file_data, canonical_mime)
        actual_path = result.get("path", storage_path)
    except Exception as e:
        logger.error(f"Document storage failed: {e}")
        actual_path = storage_path

    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        await conn.execute(
            """INSERT INTO standards_documents (id, filename, label, storage_path, content_type, size_bytes,
               parse_status, is_active, org_id, uploaded_by, uploaded_by_name, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
            doc_id, file.filename, label or file.filename, actual_path,
            canonical_mime, len(file_data),
            "parsing", True, org_id, current_user["id"], current_user.get("name", ""), now,
        )
    background_tasks.add_task(parse_document_background, doc_id, file_data, file.filename, label or file.filename, org_id)
    return {"id": doc_id, "filename": file.filename, "label": label or file.filename, "parse_status": "parsing", "org_id": org_id}


async def parse_document_background(doc_id: str, file_data: bytes, filename: str, label: str, org_id: str):
    try:
        from utils.document_parser import extract_text
        from utils.ai import extract_document_criteria
        text = extract_text(file_data, filename)
        if not text.strip():
            async with database.with_org(org_id) as conn:
                await conn.execute("UPDATE standards_documents SET parse_status='failed', parse_error='No text could be extracted' WHERE id=$1", doc_id)
            return
        criteria_result = await extract_document_criteria(text, label)
        criteria = criteria_result.get("criteria", [])
        doc_summary = criteria_result.get("document_summary", "")
        async with database.with_org(org_id) as conn:
            await conn.execute(
                """UPDATE standards_documents SET parse_status='parsed', extracted_text=$1,
                   document_summary=$2, extracted_criteria=$3::jsonb, criteria_count=$4, parsed_at=$5 WHERE id=$6""",
                text[:5000], doc_summary, criteria, len(criteria),
                datetime.now(timezone.utc), doc_id,
            )
        logger.info(f"Document {doc_id} parsed: {len(criteria)} criteria extracted")
        await rescan_meetings_background(doc_id, org_id)
    except Exception as e:
        logger.error(f"Document parse failed for {doc_id}: {e}")
        async with database.with_org(org_id) as conn:
            await conn.execute("UPDATE standards_documents SET parse_status='failed', parse_error=$1 WHERE id=$2", str(e), doc_id)


@router.patch("/standards/documents/{doc_id}")
async def update_document(doc_id: str, request: Request, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Admin/Manager only")
    data = await request.json()
    allowed = {"is_active", "label"}
    update = {k: v for k, v in data.items() if k in allowed}
    if not update:
        raise HTTPException(400, "No valid fields to update")
    org_id = current_user.get("org_id", "")
    set_parts = [f"{k}=${i+2}" for i, k in enumerate(update.keys())]
    async with database.with_org(org_id) as conn:
        await conn.execute(f"UPDATE standards_documents SET {', '.join(set_parts)} WHERE id=$1", doc_id, *list(update.values()))
    from utils.standards_cache import invalidate_org
    invalidate_org(org_id)
    return {"message": "Updated"}


@router.get("/standards/documents/{doc_id}/download")
async def download_document(doc_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Admin/Manager only")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        row = await conn.fetchrow(
            "SELECT filename, storage_path, content_type FROM standards_documents WHERE id=$1",
            doc_id,
        )
    if not row or not row["storage_path"]:
        raise HTTPException(404, "Document not found")
    try:
        file_data, _ = await _storage_get_document(row["storage_path"])
    except Exception as e:
        logger.error(f"Document download failed for {doc_id}: {e}")
        raise HTTPException(404, "File not found in storage")
    filename = row["filename"] or "document"
    return _Response(
        content=file_data,
        media_type=row["content_type"] or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/standards/documents/{doc_id}")
async def delete_document(doc_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Admin/Manager only")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        row = await conn.fetchrow("SELECT storage_path FROM standards_documents WHERE id=$1", doc_id)
        await conn.execute("DELETE FROM standards_documents WHERE id=$1", doc_id)
        from utils.standards_cache import invalidate_org
        invalidate_org(org_id)
    if row and row["storage_path"]:
        try:
            await _storage_delete_document(row["storage_path"])
        except Exception as e:
            logger.error(f"Failed to delete document from storage for {doc_id}: path={row['storage_path']} error={e}")
    return {"message": "Deleted"}


async def rescan_meetings_background(doc_id: str, org_id: str):
    from utils.ai import analyze_custom_only
    try:
        async with database.with_org(org_id) as conn:
            doc_row = await conn.fetchrow(
                "SELECT id, label, filename, extracted_criteria FROM standards_documents WHERE id=$1 AND parse_status='parsed'",
                doc_id,
            )
            if not doc_row:
                return
            doc = dict(doc_row)
            # Single JOIN: fetch all analyses + their meeting transcript in one query (no N+1)
            scan_rows = await conn.fetch(
                """SELECT a.id AS analysis_id, a.custom_mappings,
                          t.text AS transcript_text
                   FROM analyses a
                   JOIN meetings m ON m.analysis_id = a.id
                   JOIN transcripts t ON t.id = m.transcript_id
                   WHERE m.org_id = $1 AND t.text IS NOT NULL""",
                org_id,
            )

        updated = 0
        for row in scan_rows:
            custom_mappings = _jlist(row["custom_mappings"]) if row["custom_mappings"] else []
            if any(m.get("document_id") == doc_id for m in custom_mappings):
                continue
            new_mappings = await analyze_custom_only(row["transcript_text"], doc)
            if new_mappings:
                async with database.with_org(org_id) as conn:
                    await conn.execute(
                        "UPDATE analyses SET custom_mappings=$1::jsonb WHERE id=$2",
                        custom_mappings + new_mappings, row["analysis_id"],
                    )
                updated += 1
        logger.info(f"Auto-rescan complete: {updated} meeting(s) updated for doc '{doc.get('label', doc_id)}'")
    except Exception as e:
        logger.error(f"Auto-rescan failed for doc {doc_id}: {e}")


# ── Template ──────────────────────────────────────────────────────────────────

@router.get("/template")
async def get_template(current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    key = f"supervision_template:{org_id}"
    async with database.with_admin() as conn:
        row = await conn.fetchrow("SELECT data FROM settings WHERE id=$1", key)
        if not row:
            row = await conn.fetchrow("SELECT data FROM settings WHERE id=$1", "supervision_template")
    if not row:
        return {"steps": [], "name": "Supervision Template", "description": ""}
    d = _jdict(row["data"])
    return {"steps": d.get("steps", []), "name": d.get("name", "Supervision Template"), "description": d.get("description", "")}


@router.put("/template")
async def save_template(request: Request, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Admin/Manager only")
    data = await request.json()
    org_id = current_user.get("org_id", "")
    key = f"supervision_template:{org_id}" if org_id else "supervision_template"
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "steps": data.get("steps", []),
        "name": data.get("name", "Supervision Template"),
        "description": data.get("description", ""),
        "updated_at": now,
        "updated_by_name": current_user.get("name", ""),
    }
    async with database.with_org(org_id) as conn:
        await conn.execute(
            """INSERT INTO settings (id, org_id, data) VALUES ($1,$2,$3::jsonb)
               ON CONFLICT (id) DO UPDATE SET data=$3::jsonb""",
            key, org_id, payload,
        )
    return {"message": "Template saved", "steps": data.get("steps", [])}


# ── Team Insights ─────────────────────────────────────────────────────────────

async def _ti_resolve_staff(conn, org_id: str, current_user: dict, team_id: Optional[str], setting_id: Optional[str]) -> list:
    """Resolve the staff list in scope for this Team Insights request."""
    if team_id:
        rows = await conn.fetch(
            "SELECT id, name, role FROM users WHERE org_id=$1 AND role IN ('attendee','manager') AND is_active=TRUE AND team_id=$2",
            org_id, team_id,
        )
    elif setting_id:
        rows = await conn.fetch(
            "SELECT id, name, role FROM users WHERE org_id=$1 AND role IN ('attendee','manager') AND is_active=TRUE AND setting_id=$2",
            org_id, setting_id,
        )
    elif current_user["role"] == "manager":
        mgr_scope = get_manager_scope(current_user)
        if mgr_scope["level"] == "team":
            rows = await conn.fetch(
                "SELECT id, name, role FROM users WHERE org_id=$1 AND role IN ('attendee','manager') AND is_active=TRUE AND team_id=$2",
                org_id, mgr_scope["team_id"],
            )
        elif mgr_scope["level"] == "setting":
            rows = await conn.fetch(
                "SELECT id, name, role FROM users WHERE org_id=$1 AND role IN ('attendee','manager') AND is_active=TRUE AND setting_id=$2",
                org_id, mgr_scope["setting_id"],
            )
        else:
            rows = await conn.fetch(
                "SELECT id, name, role FROM users WHERE org_id=$1 AND role IN ('attendee','manager') AND is_active=TRUE",
                org_id,
            )
    else:
        rows = await conn.fetch(
            "SELECT id, name, role FROM users WHERE org_id=$1 AND role IN ('attendee','manager') AND is_active=TRUE",
            org_id,
        )
    return [dict(r) for r in rows]


async def _ti_load_standards(conn, org_id: str, org_jurisdiction: str, org_service_type: Optional[str]):
    """Load jurisdiction-aware standards and split into CQC-type vs Care-Cert-type buckets."""
    REG_TYPES = {"cqc", "ciw", "ci", "rqia_dom", "rqia_res", "eif", "eyfs_safeguarding", "chqs"}
    if org_jurisdiction == "wales":
        std_rows = await conn.fetch(
            "SELECT type, reference, name, sub_outcomes FROM standards_entries WHERE is_active=TRUE AND is_system=TRUE AND jurisdiction='wales' ORDER BY type, reference",
        )
    elif org_jurisdiction == "scotland":
        std_rows = await conn.fetch(
            "SELECT type, reference, name, sub_outcomes FROM standards_entries WHERE is_active=TRUE AND is_system=TRUE AND jurisdiction='scotland' ORDER BY type, reference",
        )
    elif org_jurisdiction == "northern_ireland":
        std_rows = await conn.fetch(
            """SELECT type, reference, name, sub_outcomes FROM standards_entries
               WHERE is_active=TRUE AND jurisdiction='northern_ireland'
               AND (service_type IS NULL OR service_type=$1)
               ORDER BY type, reference""",
            org_service_type,
        )
    elif org_jurisdiction == "ofsted":
        std_rows = await conn.fetch(
            """SELECT type, reference, name, sub_outcomes FROM standards_entries
               WHERE is_active=TRUE AND is_system=TRUE AND jurisdiction='ofsted' AND service_type=$1
               ORDER BY type, reference""",
            org_service_type,
        )
    else:
        std_rows = await conn.fetch(
            "SELECT type, reference, name, sub_outcomes FROM standards_entries WHERE is_active=TRUE AND type IN ('cqc','care_cert') AND (is_system=TRUE OR org_id=$1) ORDER BY type, reference",
            org_id,
        )

    cqc_stds, cc_stds, cc_sub_outcomes = [], [], {}
    for s in std_rows:
        s = dict(s)
        if s["type"] in REG_TYPES:
            cqc_stds.append({"ref": s["reference"], "name": s["name"]})
        else:
            cc_stds.append({"ref": s["reference"], "name": s["name"]})
            _raw_subs = s.get("sub_outcomes")
            subs = (json.loads(_raw_subs) if isinstance(_raw_subs, str) else _raw_subs) or []
            if subs:
                cc_sub_outcomes[s["reference"]] = [so["ref"] for so in subs]

    cqc_stds.sort(key=lambda x: _ref_nums(x["ref"]))
    cc_stds.sort(key=lambda x: _ref_nums(x["ref"]))
    return cqc_stds, cc_stds, cc_sub_outcomes


async def _ti_load_meetings_and_uploads(conn, date_from: Optional[str], date_to: Optional[str]):
    """Fetch in-scope meetings+analyses (single JOIN) plus accepted upload evidence."""
    date_conds = ["m.status IN ('in_review','reviewed','signed_off','shared')", "m.analysis_id IS NOT NULL"]
    date_params: list = []
    if date_from:
        date_params.append(date_from)
        date_conds.append(f"m.date >= ${len(date_params)}")
    if date_to:
        date_params.append(date_to + "T23:59:59")
        date_conds.append(f"m.date <= ${len(date_params)}")
    joined_rows = await conn.fetch(
        f"""SELECT m.*, a.cqc_mappings, a.care_cert_mappings, a.custom_mappings,
                   a.actions, a.risks, a.learning_needs, a.achievements
            FROM meetings m
            JOIN analyses a ON a.id = m.analysis_id
            WHERE {' AND '.join(date_conds)}""",
        *date_params,
    )
    all_items = [
        {"meeting": dict(r), "analysis": {
            "cqc_mappings": r["cqc_mappings"],
            "care_cert_mappings": r["care_cert_mappings"],
            "custom_mappings": r["custom_mappings"],
            "actions": r["actions"],
            "risks": r["risks"],
            "learning_needs": r["learning_needs"],
            "achievements": r["achievements"],
        }}
        for r in joined_rows
    ]

    upload_rows = []
    try:
        upload_date_conds = ["status='done'", "staff_id IS NOT NULL"]
        upload_date_params: list = []
        if date_from:
            upload_date_params.append(date_from)
            upload_date_conds.append(f"created_at >= ${len(upload_date_params)}")
        if date_to:
            upload_date_params.append(date_to + "T23:59:59")
            upload_date_conds.append(f"created_at <= ${len(upload_date_params)}")
        upload_rows = await conn.fetch(
            f"SELECT staff_id, created_at, cqc_mappings, care_cert_mappings, custom_mappings FROM supervision_uploads WHERE {' AND '.join(upload_date_conds)}",
            *upload_date_params,
        )
    except Exception as e:
        logger.warning("Could not fetch upload evidence for team insights: %s", e)

    return all_items, upload_rows


def _ti_jlist(val):
    """Ensure a JSONB field is a list — guards against raw strings when asyncpg
    prepared-statement cache is reset by SET LOCAL ROLE."""
    if val is None:
        return []
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return val if isinstance(val, list) else []


def _ti_empty_cqc(): return {"likely": 0, "review": 0, "total": 0, "last_date": "", "latest_excerpt": "", "source_meeting_id": ""}
def _ti_empty_cc(): return {"likely": 0, "review": 0, "total": 0, "last_date": "", "latest_excerpt": "", "source_meeting_id": "", "covered_refs": set()}


def _ti_accumulate_from_meetings(all_items: list, staff_ids: set, cqc_ev: dict, cc_ev: dict, cust_ev: dict, cust_names: dict, all_risks: list, all_outstanding: list):
    """Walk each meeting's analysis mappings/risks/actions into the evidence accumulators (in place)."""
    for item in all_items:
        mtg, ana = item["meeting"], item["analysis"]
        date = mtg.get("date", "")
        sign_off_mgr_id = str(mtg.get("sign_off_manager_id") or "")
        for attendee in _ti_jlist(mtg.get("attendees")):
            uid = attendee.get("user_id", "") if isinstance(attendee, dict) else ""
            if uid not in staff_ids or (sign_off_mgr_id and uid == sign_off_mgr_id):
                continue
            for m in _ti_jlist(ana.get("cqc_mappings")):
                if not isinstance(m, dict): continue
                if m.get("status") == "rejected": continue
                ref = m.get("regulation_ref", "")
                if not ref: continue
                if ref not in cqc_ev[uid]: cqc_ev[uid][ref] = _ti_empty_cqc()
                c = cqc_ev[uid][ref]
                c["total"] += 1
                if m.get("confidence") == "likely_evidence": c["likely"] += 1
                elif m.get("confidence") in ("needs_review", "possible_evidence", "not_enough_evidence"): c["review"] += 1
                if date > c["last_date"]:
                    c["last_date"] = date
                    if m.get("transcript_excerpt"):
                        c["latest_excerpt"] = m["transcript_excerpt"][:200]
                        c["source_meeting_id"] = str(mtg.get("id", ""))
            for m in _ti_jlist(ana.get("care_cert_mappings")):
                if not isinstance(m, dict): continue
                if m.get("status") == "rejected": continue
                std_ref = m.get("standard_ref", "")
                if not std_ref: continue
                if std_ref not in cc_ev[uid]: cc_ev[uid][std_ref] = _ti_empty_cc()
                c = cc_ev[uid][std_ref]
                c["total"] += 1
                if m.get("confidence") == "likely_evidence": c["likely"] += 1
                elif m.get("confidence") in ("needs_review", "possible_evidence", "not_enough_evidence"): c["review"] += 1
                if date > c["last_date"]:
                    c["last_date"] = date
                    if m.get("transcript_excerpt"):
                        c["latest_excerpt"] = m["transcript_excerpt"][:200]
                        c["source_meeting_id"] = str(mtg.get("id", ""))
                or_ref = m.get("outcome_ref", "")
                if or_ref: c["covered_refs"].add(or_ref)
            for m in _ti_jlist(ana.get("custom_mappings")):
                if not isinstance(m, dict): continue
                if m.get("status") == "rejected": continue
                ref = m.get("criterion_ref", "") or m.get("document_name", "")
                if not ref: continue
                cust_names.setdefault(ref, m.get("criterion_name", ref))
                if ref not in cust_ev[uid]: cust_ev[uid][ref] = _ti_empty_cqc()
                c = cust_ev[uid][ref]
                c["total"] += 1
                if m.get("confidence") == "likely_evidence": c["likely"] += 1
                elif m.get("confidence") in ("needs_review", "possible_evidence", "not_enough_evidence"): c["review"] += 1
                if date > c["last_date"]:
                    c["last_date"] = date
                    if m.get("transcript_excerpt"):
                        c["latest_excerpt"] = m["transcript_excerpt"][:200]
                        c["source_meeting_id"] = str(mtg.get("id", ""))
        for risk in _ti_jlist(ana.get("risks")):
            text = risk if isinstance(risk, str) else (risk.get("text", "") if isinstance(risk, dict) else "")
            if text.strip(): all_risks.append(text.strip())
        for action in _ti_jlist(ana.get("actions")):
            if isinstance(action, dict) and not action.get("completed", False):
                t = action.get("text", "").strip()
                if t: all_outstanding.append(t)


def _ti_accumulate_from_uploads(upload_rows: list, staff: list, cqc_ev: dict, cc_ev: dict, cust_ev: dict, cust_names: dict):
    """Merge accepted evidence from supervision_uploads into the same accumulators (in place)."""
    staff_id_str = {str(s["id"]): s["id"] for s in staff}

    def _parse(val):
        if isinstance(val, str):
            try: return json.loads(val)
            except Exception: return []
        return val or []

    for urow in upload_rows:
        uid_str = str(urow["staff_id"] or "")
        if uid_str not in staff_id_str:
            continue
        uid = staff_id_str[uid_str]   # use the original UUID key for the accumulators
        date = str(urow["created_at"] or "")[:10]

        for m in _parse(urow["cqc_mappings"]):
            if m.get("status") not in ("accepted", "needs_followup"): continue
            ref = m.get("regulation_ref", "")
            if not ref: continue
            if ref not in cqc_ev[uid]: cqc_ev[uid][ref] = _ti_empty_cqc()
            c = cqc_ev[uid][ref]
            c["total"] += 1
            if m.get("status") == "accepted": c["likely"] += 1
            else: c["review"] += 1
            if date > c["last_date"]: c["last_date"] = date

        for m in _parse(urow["care_cert_mappings"]):
            if m.get("status") not in ("accepted", "needs_followup"): continue
            std_ref = m.get("standard_ref", "")
            if not std_ref: continue
            if std_ref not in cc_ev[uid]: cc_ev[uid][std_ref] = _ti_empty_cc()
            c = cc_ev[uid][std_ref]
            c["total"] += 1
            if m.get("status") == "accepted": c["likely"] += 1
            else: c["review"] += 1
            if date > c["last_date"]: c["last_date"] = date
            or_ref = m.get("outcome_ref", "")
            if or_ref: c["covered_refs"].add(or_ref)

        for m in _parse(urow["custom_mappings"]):
            if m.get("status") not in ("accepted", "needs_followup"): continue
            ref = m.get("criterion_ref", "") or m.get("document_name", "")
            if not ref: continue
            cust_names.setdefault(ref, m.get("criterion_name", ref))
            if ref not in cust_ev[uid]: cust_ev[uid][ref] = _ti_empty_cqc()
            c = cust_ev[uid][ref]
            c["total"] += 1
            if m.get("status") == "accepted": c["likely"] += 1
            else: c["review"] += 1
            if date > c["last_date"]: c["last_date"] = date


def _ti_build_simple_matrix(staff: list, stds: list, ev_map: dict) -> dict:
    """Shared builder for the CQC and custom-standards matrices (identical gap/evidenced/needs_review logic)."""
    rows = []
    for s in staff:
        cells = {}
        for std in stds:
            ref = std["ref"]
            cell = ev_map[s["id"]].get(ref)
            if cell and cell["total"] > 0:
                cells[ref] = {**cell, "status": "evidenced" if cell["likely"] > 0 else "needs_review"}
            else:
                cells[ref] = {"status": "gap", "total": 0, "likely": 0, "review": 0, "last_date": ""}
        rows.append({"staff_id": s["id"], "staff_name": s["name"], "staff_role": s["role"], "cells": cells})
    return {"standards": stds, "rows": rows}


def _ti_build_cc_matrix(staff: list, stds: list, ev_map: dict, cc_sub_outcomes: dict) -> dict:
    """Care Cert matrix builder — tracks partial coverage via sub-outcome refs, unlike the simple matrices."""
    rows = []
    for s in staff:
        cells = {}
        for std in stds:
            ref = std["ref"]
            all_subs = set(cc_sub_outcomes.get(ref, []))
            total_subs = len(all_subs)
            ev = ev_map[s["id"]].get(ref, {})
            covered_refs = ev.get("covered_refs", set())
            if total_subs > 0:
                covered_count = len(covered_refs & all_subs)
                pct = round((covered_count / total_subs) * 100)
            else:
                covered_count = 1 if ev.get("total", 0) > 0 else 0
                total_subs = 1
                pct = 100 if covered_count else 0
            if covered_count == total_subs and total_subs > 0:
                status = "evidenced"
            elif covered_count > 0:
                status = "partial"
            else:
                status = "gap"
            cells[ref] = {
                "status": status, "total": ev.get("total", 0), "likely": ev.get("likely", 0),
                "review": ev.get("review", 0), "last_date": ev.get("last_date", ""),
                "covered_sub": covered_count, "total_sub": total_subs, "pct": pct,
                "evidenced_refs": sorted(list(covered_refs & all_subs)),
                "latest_excerpt": ev.get("latest_excerpt", ""),
                "source_meeting_id": ev.get("source_meeting_id", ""),
            }
        rows.append({"staff_id": s["id"], "staff_name": s["name"], "staff_role": s["role"], "cells": cells})
    return {"standards": stds, "rows": rows}


def _ti_compute_coverage_gaps(staff: list, cqc_stds: list, cc_stds: list, cust_stds: list, cqc_ev: dict, cc_ev: dict, cust_ev: dict, cc_sub_outcomes: dict) -> list:
    """Build the sorted coverage-gaps theme list across all three standard types."""
    gaps = []
    for std in cqc_stds:
        ref = std["ref"]
        covered = sum(1 for s in staff if cqc_ev[s["id"]].get(ref, {}).get("total", 0) > 0)
        gaps.append({"ref": ref, "name": std["name"], "type": "cqc", "covered": covered, "total": len(staff)})
    for std in cc_stds:
        ref = std["ref"]
        all_subs = set(cc_sub_outcomes.get(ref, []))
        total_subs = len(all_subs)
        if total_subs > 0:
            fully_covered = sum(1 for s in staff if len(cc_ev[s["id"]].get(ref, {}).get("covered_refs", set()) & all_subs) == total_subs)
            all_covered = set()
            for s in staff: all_covered |= cc_ev[s["id"]].get(ref, {}).get("covered_refs", set())
            union_covered = len(all_covered & all_subs)
        else:
            fully_covered = sum(1 for s in staff if cc_ev[s["id"]].get(ref, {}).get("total", 0) > 0)
            union_covered = 0
        gaps.append({"ref": ref, "name": std["name"], "type": "care_cert", "covered": fully_covered, "total": len(staff), "covered_sub": union_covered, "total_sub": total_subs})
    for std in cust_stds:
        ref = std["ref"]
        covered = sum(1 for s in staff if cust_ev[s["id"]].get(ref, {}).get("total", 0) > 0)
        gaps.append({"ref": ref, "name": std["name"], "type": "custom", "covered": covered, "total": len(staff)})
    _to = {"cqc": 0, "care_cert": 1, "custom": 2}
    gaps.sort(key=lambda x: (_to.get(x["type"], 9), _ref_nums(x["ref"])))
    return gaps


def _ti_agg_top(items: list, top: int = 10) -> list:
    """Dedupe similar free-text items (by 60-char lowercase prefix) and rank by frequency."""
    counts: dict = {}
    for text in items:
        key = text[:60].lower()
        if key not in counts: counts[key] = {"text": text, "count": 0}
        counts[key]["count"] += 1
    return sorted(counts.values(), key=lambda x: -x["count"])[:top]


@router.get("/team-insights")
async def get_team_insights(
    team_id: Optional[str] = None,
    setting_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user.get("org_id", "")

    async with database.with_org(org_id) as conn:
        staff = await _ti_resolve_staff(conn, org_id, current_user, team_id, setting_id)
        if not staff:
            return {
                "staff_count": 0, "meeting_count": 0,
                "matrix": {"cqc": {"standards": [], "rows": []}, "care_cert": {"standards": [], "rows": []}, "custom": {"standards": [], "rows": []}},
                "themes": {"coverage_gaps": [], "common_risks": [], "outstanding_actions": []},
            }

    # Get org jurisdiction to load the correct framework standards
    async with database.with_org(org_id) as conn:
        org_info = await conn.fetchrow("SELECT jurisdiction, service_type FROM organisations WHERE id=$1", org_id)
    org_jurisdiction = (org_info["jurisdiction"] if org_info else None) or "england"
    org_service_type = (org_info["service_type"] if org_info else None)

    async with database.with_org(org_id) as conn:
        cqc_stds, cc_stds, cc_sub_outcomes = await _ti_load_standards(conn, org_id, org_jurisdiction, org_service_type)
        all_items, upload_rows = await _ti_load_meetings_and_uploads(conn, date_from, date_to)

    staff_ids = {s["id"] for s in staff}
    cqc_ev = {s["id"]: {} for s in staff}
    cc_ev = {s["id"]: {} for s in staff}
    cust_ev = {s["id"]: {} for s in staff}
    cust_names: dict = {}
    all_risks, all_outstanding = [], []

    _ti_accumulate_from_meetings(all_items, staff_ids, cqc_ev, cc_ev, cust_ev, cust_names, all_risks, all_outstanding)
    _ti_accumulate_from_uploads(upload_rows, staff, cqc_ev, cc_ev, cust_ev, cust_names)

    cust_stds = [{"ref": r, "name": cust_names.get(r, r)} for r in sorted(cust_names)]
    gaps = _ti_compute_coverage_gaps(staff, cqc_stds, cc_stds, cust_stds, cqc_ev, cc_ev, cust_ev, cc_sub_outcomes)

    return {
        "staff_count": len(staff), "meeting_count": len(all_items),
        "org_jurisdiction": org_jurisdiction,
        "org_service_type": org_service_type or "",
        "matrix": {
            "cqc": _ti_build_simple_matrix(staff, cqc_stds, cqc_ev),
            "care_cert": _ti_build_cc_matrix(staff, cc_stds, cc_ev, cc_sub_outcomes),
            "custom": _ti_build_simple_matrix(staff, cust_stds, cust_ev),
        },
        "themes": {"coverage_gaps": gaps, "common_risks": _ti_agg_top(all_risks), "outstanding_actions": _ti_agg_top(all_outstanding)},
    }


# ── People Stats (usage dashboard) ──────────────────────────────────────────

@router.get("/people-stats")
async def get_people_stats(current_user=Depends(get_current_user)):
    """Per-user meeting count, last active date, 8-week activity sparkline, and pending-invite flag."""
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user.get("org_id", "")

    async with database.with_org(org_id) as conn:
        user_rows = await conn.fetch(
            """SELECT id, name, email, role, team_id, setting_id,
                      is_active, mfa_enabled, must_change_password, created_at
               FROM users WHERE org_id=$1 ORDER BY name""",
            org_id,
        )
        # Meetings with attendees and dates for the org
        mtg_rows = await conn.fetch(
            """SELECT id, date, attendees
               FROM meetings
               WHERE status IN ('in_review','reviewed','signed_off','shared')
               ORDER BY date DESC"""
        )
        # Team/setting name lookup
        team_rows   = await conn.fetch("SELECT id, name FROM teams WHERE org_id=$1", org_id)
        setting_rows = await conn.fetch("SELECT id, name FROM org_settings WHERE org_id=$1", org_id)

    team_map    = {str(r["id"]): r["name"] for r in team_rows}
    setting_map = {str(r["id"]): r["name"] for r in setting_rows}

    # Build per-user meeting date list
    from collections import defaultdict
    user_meetings: dict = defaultdict(list)
    for mtg in mtg_rows:
        m = dict(mtg)
        raw_date = str(m.get("date", "") or "")[:10]
        for att in _jlist(m.get("attendees")):
            if isinstance(att, dict):
                uid = str(att.get("user_id", ""))
                if uid and raw_date:
                    user_meetings[uid].append(raw_date)

    # 8-week buckets (Mon of each week, newest = index 7)
    today = datetime.now(timezone.utc).date()
    week_starts = [(today - timedelta(days=today.weekday() + 7 * (7 - i))).isoformat() for i in range(8)]
    week_ends   = [(today - timedelta(days=today.weekday() + 7 * (7 - i) - 6)).isoformat() for i in range(8)]

    result = []
    for u in user_rows:
        uid = str(u["id"])
        dates = sorted(user_meetings.get(uid, []), reverse=True)
        meeting_count = len(dates)
        last_meeting_date = dates[0] if dates else None

        # 8-week sparkline
        weekly = []
        for ws, we in zip(week_starts, week_ends):
            weekly.append(sum(1 for d in dates if ws <= d <= we))

        result.append({
            "user_id": uid,
            "name": u["name"],
            "email": u["email"],
            "role": u["role"],
            "team_id": str(u["team_id"]) if u["team_id"] else None,
            "team_name": team_map.get(str(u["team_id"] or ""), ""),
            "setting_id": str(u["setting_id"]) if u["setting_id"] else None,
            "setting_name": setting_map.get(str(u["setting_id"] or ""), ""),
            "is_active": u["is_active"],
            "mfa_enabled": bool(u["mfa_enabled"]),
            "pending_invite": bool(u["must_change_password"]),
            "created_at": str(u["created_at"] or "")[:10],
            "meeting_count": meeting_count,
            "last_meeting_date": last_meeting_date,
            "weekly_activity": weekly,
        })

    return result


# ── Team Insights Registers ───────────────────────────────────────────────────

@router.get("/team-insights/action-stats")
async def get_action_stats(current_user=Depends(get_current_user)):
    """Lightweight overdue/outstanding action counts for the dashboard banner."""
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user.get("org_id", "")
    today = datetime.now(timezone.utc).date().isoformat()

    async with database.with_org(org_id) as conn:
        rows = await conn.fetch(
            """SELECT a.actions
               FROM meetings m
               JOIN analyses a ON a.id = m.analysis_id
               WHERE m.status IN ('in_review','reviewed','signed_off','shared')
               AND m.analysis_id IS NOT NULL"""
        )

    outstanding = 0
    overdue = 0
    for row in rows:
        for action in _jlist(dict(row).get("actions")):
            if isinstance(action, dict) and not action.get("completed", False):
                outstanding += 1
                if action.get("due_date") and str(action["due_date"]) < today:
                    overdue += 1

    return {"outstanding": outstanding, "overdue": overdue}


# ── Evidence Feedback (AI Accuracy) ───────────────────────────────────────────
# Read-only view over evidence_feedback — written by review.py's evidence
# accept/reject/bulk-action handlers on every manager decision, but had no
# consumer anywhere in the app. Surfaces it as an AI-accuracy report without
# changing what/when review.py writes.

@router.get("/evidence-feedback/stats")
async def get_evidence_feedback_stats(current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user.get("org_id", "")

    async with database.with_org(org_id) as conn:
        rows = await conn.fetch(
            "SELECT evidence_type, ai_confidence, manager_action, standard_ref, standard_name "
            "FROM evidence_feedback WHERE org_id=$1",
            org_id,
        )

    by_action: dict = {}
    by_type: dict = {}
    by_confidence: dict = {}
    rejected_by_standard: dict = {}

    for r in rows:
        action = r["manager_action"] or "pending"
        confidence = r["ai_confidence"] or "unknown"
        etype = r["evidence_type"] or "unknown"

        by_action[action] = by_action.get(action, 0) + 1
        by_type[etype] = by_type.get(etype, 0) + 1
        conf_bucket = by_confidence.setdefault(confidence, {})
        conf_bucket[action] = conf_bucket.get(action, 0) + 1

        if action == "rejected":
            key = (r["standard_ref"] or "", r["standard_name"] or "")
            rejected_by_standard[key] = rejected_by_standard.get(key, 0) + 1

    accepted = by_action.get("accepted", 0)
    rejected = by_action.get("rejected", 0)
    decided = accepted + rejected
    acceptance_rate = round((accepted / decided) * 100, 1) if decided else None

    top_rejected = sorted(
        [{"standard_ref": k[0], "standard_name": k[1], "count": v} for k, v in rejected_by_standard.items()],
        key=lambda x: x["count"], reverse=True,
    )[:10]

    return {
        "total": len(rows),
        "by_action": by_action,
        "by_type": by_type,
        "by_confidence": by_confidence,
        "acceptance_rate": acceptance_rate,
        "top_rejected_standards": top_rejected,
    }


@router.get("/evidence-feedback")
async def list_evidence_feedback(
    limit: int = 200,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user.get("org_id", "")
    limit = max(1, min(limit, 1000))

    conds = ["ef.org_id=$1"]
    params: list = [org_id]
    if date_from:
        params.append(date_from)
        conds.append(f"ef.timestamp >= ${len(params)}")
    if date_to:
        params.append(date_to + "T23:59:59")
        conds.append(f"ef.timestamp <= ${len(params)}")
    params.append(limit)

    async with database.with_org(org_id) as conn:
        rows = await conn.fetch(
            f"""SELECT ef.id, ef.meeting_id, m.title AS meeting_title, m.attendees, ef.user_name,
                       ef.evidence_type, ef.standard_ref, ef.standard_name,
                       ef.ai_confidence, ef.manager_action, ef.timestamp
                FROM evidence_feedback ef
                LEFT JOIN meetings m ON m.id = ef.meeting_id
                WHERE {' AND '.join(conds)}
                ORDER BY ef.timestamp DESC
                LIMIT ${len(params)}""",
            *params,
        )

    result = []
    for r in rows:
        d = dict(r)
        attendees = d.pop("attendees", None) or []
        d["attendee_name"] = ", ".join(a.get("name", "") for a in attendees if a.get("name")) or None
        result.append(d)
    return result


async def _reg_resolve_staff(conn, org_id: str, current_user: dict, team_id: Optional[str], setting_id: Optional[str]) -> list:
    """Resolve the staff list in scope for this Registers request (mirrors Team Insights scoping)."""
    if team_id:
        rows = await conn.fetch(
            "SELECT id, name FROM users WHERE org_id=$1 AND role IN ('attendee','manager') AND is_active=TRUE AND team_id=$2",
            org_id, team_id,
        )
    elif setting_id:
        rows = await conn.fetch(
            "SELECT id, name FROM users WHERE org_id=$1 AND role IN ('attendee','manager') AND is_active=TRUE AND setting_id=$2",
            org_id, setting_id,
        )
    elif current_user["role"] == "manager":
        mgr_scope = get_manager_scope(current_user)
        if mgr_scope["level"] == "team":
            rows = await conn.fetch(
                "SELECT id, name FROM users WHERE org_id=$1 AND role IN ('attendee','manager') AND is_active=TRUE AND team_id=$2",
                org_id, mgr_scope["team_id"],
            )
        elif mgr_scope["level"] == "setting":
            rows = await conn.fetch(
                "SELECT id, name FROM users WHERE org_id=$1 AND role IN ('attendee','manager') AND is_active=TRUE AND setting_id=$2",
                org_id, mgr_scope["setting_id"],
            )
        else:
            rows = await conn.fetch(
                "SELECT id, name FROM users WHERE org_id=$1 AND role IN ('attendee','manager') AND is_active=TRUE",
                org_id,
            )
    else:
        rows = await conn.fetch(
            "SELECT id, name FROM users WHERE org_id=$1 AND role IN ('attendee','manager') AND is_active=TRUE",
            org_id,
        )
    return [dict(r) for r in rows]


async def _reg_load_meetings(conn, date_from: Optional[str], date_to: Optional[str]):
    """Fetch in-scope meetings+analyses (single JOIN) for the Registers breakdown."""
    date_conds = [
        "m.status IN ('in_review','reviewed','signed_off','shared')",
        "m.analysis_id IS NOT NULL",
    ]
    date_params: list = []
    if date_from:
        date_params.append(date_from)
        date_conds.append(f"m.date >= ${len(date_params)}")
    if date_to:
        date_params.append(date_to + "T23:59:59")
        date_conds.append(f"m.date <= ${len(date_params)}")

    return await conn.fetch(
        f"""SELECT m.id, m.title, m.date, m.attendees, m.sign_off_manager_id,
                   a.actions, a.risks, a.learning_needs, a.achievements
            FROM meetings m
            JOIN analyses a ON a.id = m.analysis_id
            WHERE {' AND '.join(date_conds)}
            ORDER BY m.date DESC""",
        *date_params,
    )


def _reg_extract_registers(rows: list, staff_id_to_name: dict, staff_id_set: set):
    """Walk each meeting's row into flat per-item Actions/Risks/Learning-Needs/Achievements lists."""
    actions_out, risks_out, lns_out, achs_out = [], [], [], []

    for row in rows:
        r = dict(row)
        mtg_id = str(r["id"])
        mtg_title = r.get("title", "")
        mtg_date = str(r.get("date", ""))[:10]
        sign_off_mgr_id = str(r.get("sign_off_manager_id") or "")

        # Identify non-manager staff in this meeting.
        # staff_in_meeting: all attendees (used for actions/risks/LNs which
        #   can be assigned to any participant).
        # supervisee_staff: only role='attendee' entries (used for achievements
        #   which apply exclusively to the supervisee, not the conducting manager).
        staff_in_meeting = []
        supervisee_staff = []
        for att in _jlist(r.get("attendees")):
            if not isinstance(att, dict):
                continue
            uid = str(att.get("user_id", ""))
            if uid not in staff_id_set or uid == sign_off_mgr_id:
                continue
            person = {
                "id": uid,
                "name": staff_id_to_name.get(uid, att.get("name", "Unknown")),
            }
            staff_in_meeting.append(person)
            if att.get("role") == "attendee":
                supervisee_staff.append(person)

        if not staff_in_meeting:
            continue

        staff_names = ", ".join(s["name"] for s in staff_in_meeting)
        staff_ids_list = [s["id"] for s in staff_in_meeting]

        # For achievements: use only supervisees; fall back to full staff list
        # only if no pure-attendee is found (edge case: attendee-only meetings).
        ach_staff = supervisee_staff if supervisee_staff else staff_in_meeting
        ach_names = ", ".join(s["name"] for s in ach_staff)
        ach_ids = [s["id"] for s in ach_staff]

        for action in _jlist(r.get("actions")):
            if not isinstance(action, dict):
                continue
            actions_out.append({
                "id": action.get("id", ""),
                "text": action.get("text", ""),
                "completed": action.get("completed", False),
                "completed_at": action.get("completed_at"),
                "action_type": action.get("action_type") or "task",
                "assigned_to": action.get("assigned_to") or "",
                "due_date": action.get("due_date") or "",
                "trigger": action.get("trigger") or "",
                "is_rolled_over": action.get("is_rolled_over", False),
                "staff_names": staff_names,
                "staff_ids": staff_ids_list,
                "meeting_title": mtg_title,
                "meeting_date": mtg_date,
                "meeting_id": mtg_id,
            })

        for risk in _jlist(r.get("risks")):
            if not isinstance(risk, dict):
                continue
            text = risk.get("text") or risk.get("risk") or risk.get("description") or ""
            if not text:
                continue
            risks_out.append({
                "id": risk.get("id", ""),
                "text": text,
                "severity": (risk.get("severity") or "low").lower(),
                "is_resolved": risk.get("is_resolved", False),
                "resolved_by": risk.get("resolved_by") or "",
                "staff_names": staff_names,
                "staff_ids": staff_ids_list,
                "meeting_title": mtg_title,
                "meeting_date": mtg_date,
                "meeting_id": mtg_id,
            })

        for ln in _jlist(r.get("learning_needs")):
            if not isinstance(ln, dict):
                continue
            text = ln.get("text", "")
            if not text:
                continue
            lns_out.append({
                "id": ln.get("id", ""),
                "text": text,
                "completed": ln.get("completed", False),
                "completed_at": ln.get("completed_at"),
                "due_date": ln.get("due_date") or "",
                "assigned_to": ln.get("assigned_to") or "",
                "staff_names": staff_names,
                "staff_ids": staff_ids_list,
                "meeting_title": mtg_title,
                "meeting_date": mtg_date,
                "meeting_id": mtg_id,
            })

        for ach in _jlist(r.get("achievements")):
            if not isinstance(ach, dict):
                continue
            text = ach.get("text") or ach.get("description") or ""
            if not text:
                continue
            achs_out.append({
                "id": ach.get("id", ""),
                "text": text,
                "staff_names": ach_names,
                "staff_ids": ach_ids,
                "meeting_title": mtg_title,
                "meeting_date": mtg_date,
                "meeting_id": mtg_id,
                "meeting_status": r.get("status", ""),
            })

    return actions_out, risks_out, lns_out, achs_out


def _reg_sort_registers(actions_out: list, risks_out: list, lns_out: list, achs_out: list):
    """Apply the display ordering for each register: priority/urgency first, then resolved/completed."""
    today = datetime.now(timezone.utc).date().isoformat()
    sev_order = {"high": 0, "medium": 1, "low": 2}

    # Actions: overdue first, then outstanding, then completed
    overdue_a  = [a for a in actions_out if not a["completed"] and a["due_date"] and a["due_date"] < today]
    open_a     = [a for a in actions_out if not a["completed"] and not (a["due_date"] and a["due_date"] < today)]
    done_a     = [a for a in actions_out if a["completed"]]
    actions_out = overdue_a + open_a + done_a

    # Risks: high→medium→low unresolved, then resolved
    open_r     = sorted([r for r in risks_out if not r["is_resolved"]], key=lambda x: sev_order.get(x["severity"], 2))
    resolved_r = [r for r in risks_out if r["is_resolved"]]
    risks_out  = open_r + resolved_r

    # LNs: outstanding first, then addressed
    open_l  = [l for l in lns_out if not l["completed"]]
    done_l  = [l for l in lns_out if l["completed"]]
    lns_out = open_l + done_l

    # Achievements: newest meeting first
    achs_out.sort(key=lambda a: a.get("meeting_date") or "", reverse=True)

    return actions_out, risks_out, lns_out, achs_out


@router.get("/team-insights/registers")
async def get_registers(
    team_id: Optional[str] = None,
    setting_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    """Return per-item detail lists for Actions, Risks and Learning Needs across the org."""
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user.get("org_id", "")

    async with database.with_org(org_id) as conn:
        staff = await _reg_resolve_staff(conn, org_id, current_user, team_id, setting_id)
        if not staff:
            return {"actions": [], "risks": [], "learning_needs": []}

        staff_id_to_name = {str(s["id"]): s["name"] for s in staff}
        staff_id_set = set(staff_id_to_name.keys())

        rows = await _reg_load_meetings(conn, date_from, date_to)

    actions_out, risks_out, lns_out, achs_out = _reg_extract_registers(rows, staff_id_to_name, staff_id_set)
    actions_out, risks_out, lns_out, achs_out = _reg_sort_registers(actions_out, risks_out, lns_out, achs_out)

    return {"actions": actions_out, "risks": risks_out, "learning_needs": lns_out, "achievements": achs_out}


@router.patch("/team-insights/actions/{meeting_id}/{action_id}")
async def toggle_register_action(meeting_id: str, action_id: str, data: dict, current_user=Depends(get_current_user)):
    """Toggle action.completed from the Team Insights register (bypasses meeting-status
    lock), or from My Portfolio by the staff member it's actually assigned to — either
    way the audit entry below is attributed to whoever genuinely made the request."""
    org_id = current_user.get("org_id", "")
    completed = data.get("completed")
    if completed is None:
        raise HTTPException(400, "completed field required")

    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow(
            "SELECT analysis_id FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id
        )
        if not m_row or not m_row["analysis_id"]:
            raise HTTPException(404, "Meeting not found")
        a_row = await conn.fetchrow("SELECT id, actions FROM analyses WHERE id=$1", m_row["analysis_id"])
        if not a_row:
            raise HTTPException(404, "Analysis not found")
        actions = _jlist(a_row["actions"])
        target_idx = next((i for i, a in enumerate(actions) if isinstance(a, dict) and a.get("id") == action_id), None)
        if target_idx is None:
            raise HTTPException(404, "Action not found")
        if current_user["role"] not in ("admin", "manager") and actions[target_idx].get("assigned_to_user_id") != current_user["id"]:
            raise HTTPException(403, "You can only tick off actions assigned to you")
        now = datetime.now(timezone.utc).isoformat()
        actions[target_idx]["completed"] = completed
        actions[target_idx]["completed_at"] = now if completed else None
        await conn.execute(
            "UPDATE analyses SET actions=$1::jsonb WHERE id=$2", actions, a_row["id"]
        )
        action_text = actions[target_idx].get("text", action_id)
        status_label = "completed" if completed else "re-opened"
        try:
            await _audit(conn, meeting_id, org_id, "action_status_changed",
                         current_user["id"], current_user.get("name", ""),
                         f'Action {status_label}: "{action_text[:120]}"')
        except Exception as _e:
            logger.error(f"[AUDIT] _audit failed for action_status_changed meeting={meeting_id}: {_e}")
    return {"message": "Action updated", "completed": completed}


@router.patch("/team-insights/learning_needs/{meeting_id}/{ln_id}")
async def toggle_register_ln(meeting_id: str, ln_id: str, data: dict, current_user=Depends(get_current_user)):
    """Toggle learning_need.completed from the Team Insights register, or from My
    Portfolio by the staff member it's assigned to."""
    org_id = current_user.get("org_id", "")
    completed = data.get("completed")
    if completed is None:
        raise HTTPException(400, "completed field required")

    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow(
            "SELECT analysis_id FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id
        )
        if not m_row or not m_row["analysis_id"]:
            raise HTTPException(404, "Meeting not found")
        a_row = await conn.fetchrow(
            "SELECT id, learning_needs FROM analyses WHERE id=$1", m_row["analysis_id"]
        )
        if not a_row:
            raise HTTPException(404, "Analysis not found")
        lns = _jlist(a_row["learning_needs"])
        target_idx = next((i for i, ln in enumerate(lns) if isinstance(ln, dict) and ln.get("id") == ln_id), None)
        if target_idx is None:
            raise HTTPException(404, "Learning need not found")
        if current_user["role"] not in ("admin", "manager") and lns[target_idx].get("assigned_to_user_id") != current_user["id"]:
            raise HTTPException(403, "You can only tick off learning needs assigned to you")
        now = datetime.now(timezone.utc).isoformat()
        lns[target_idx]["completed"] = completed
        lns[target_idx]["completed_at"] = now if completed else None
        await conn.execute(
            "UPDATE analyses SET learning_needs=$1::jsonb WHERE id=$2", lns, a_row["id"]
        )
        ln_text = lns[target_idx].get("text", ln_id)
        status_label = "completed" if completed else "re-opened"
        await _audit(conn, meeting_id, org_id, "learning_need_status_changed",
                     current_user["id"], current_user["name"],
                     f'Learning need {status_label}: "{ln_text[:120]}"')
    return {"message": "Learning need updated", "completed": completed}


@router.patch("/team-insights/achievements/{meeting_id}/{ach_id}")
async def toggle_register_achievement(meeting_id: str, ach_id: str, data: dict, current_user=Depends(get_current_user)):
    """Toggle achievement.acknowledged from the Team Themes register."""
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user.get("org_id", "")
    acknowledged = data.get("acknowledged")
    if acknowledged is None:
        raise HTTPException(400, "acknowledged field required")

    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow(
            "SELECT analysis_id FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id
        )
        if not m_row or not m_row["analysis_id"]:
            raise HTTPException(404, "Meeting not found")
        a_row = await conn.fetchrow(
            "SELECT id, achievements FROM analyses WHERE id=$1", m_row["analysis_id"]
        )
        if not a_row:
            raise HTTPException(404, "Analysis not found")
        achs = _jlist(a_row["achievements"])
        updated = False
        for i, ach in enumerate(achs):
            if isinstance(ach, dict) and ach.get("id") == ach_id:
                achs[i]["acknowledged"] = acknowledged
                updated = True
                break
        if not updated:
            raise HTTPException(404, "Achievement not found")
        await conn.execute(
            "UPDATE analyses SET achievements=$1::jsonb WHERE id=$2", achs, a_row["id"]
        )
        ach_text = next((a.get("text","") for a in achs if a.get("id") == ach_id), ach_id)
        status_label = "acknowledged" if acknowledged else "un-acknowledged"
        await _audit(conn, meeting_id, org_id, "achievement_acknowledged",
                     current_user["id"], current_user["name"],
                     f'Achievement {status_label}: "{ach_text[:120]}"')
    return {"message": "Achievement updated", "acknowledged": acknowledged}


# ── Export endpoints ──────────────────────────────────────────────────────────

@router.get("/meetings-brief")
async def list_meetings_brief(current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user.get("org_id", "")
    scope = get_manager_scope(current_user)
    async with database.with_org(org_id) as conn:
        if scope["level"] != "org":
            scoped_ids = await get_scoped_staff_ids(conn, org_id, scope) or []
            scoped_ids = list(set(scoped_ids) | {current_user["id"]})
            rows = await conn.fetch(
                """SELECT id, title, date, attendees FROM meetings
                   WHERE status IN ('signed_off','shared')
                     AND (created_by = ANY($1::uuid[])
                          OR sign_off_manager_id = ANY($1::uuid[])
                          OR EXISTS (SELECT 1 FROM jsonb_array_elements(
                                         CASE WHEN jsonb_typeof(COALESCE(attendees,'[]'::jsonb)) = 'array'
                                              THEN COALESCE(attendees,'[]'::jsonb) ELSE '[]'::jsonb END) a
                                     WHERE a->>'user_id' = ANY($1::text[])))
                   ORDER BY date DESC""",
                scoped_ids,
            )
        else:
            rows = await conn.fetch(
                "SELECT id, title, date, attendees FROM meetings WHERE status IN ('signed_off','shared') ORDER BY date DESC"
            )
    return [{"id": r["id"], "title": r["title"], "date": r["date"],
             "attendees": [{"user_id": a.get("user_id"), "name": a.get("name")} for a in _jlist(r["attendees"])]}
            for r in rows]


@router.post("/export-evidence")
async def export_evidence(request: Request, current_user=Depends(get_current_user)):
    data = await request.json()
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    # Rate limit: 10 evidence exports per user / 60 min
    from utils.rate_limit import check_rate_limit
    async with database.with_admin() as _rl_conn:
        await check_rate_limit(
            _rl_conn,
            identifier=f"export:{current_user['id']}",
            max_attempts=10,
            window_minutes=60,
            error_detail="Export limit reached. A maximum of 10 exports can be generated per hour.",
        )
    org_id = current_user.get("org_id", "")
    fmt = data.get("format", "csv")
    staff_ids = data.get("staff_ids") or []
    date_from = data.get("date_from")
    date_to = data.get("date_to")
    meeting_ids = data.get("meeting_ids") or []

    conditions = ["status IN ('signed_off','shared')", "analysis_id IS NOT NULL"]
    params: list = []

    rows_csv, mtg_analyses = [], []

    async with database.with_org(org_id) as conn:
        # SEC-002: constrain to the caller's assigned team/setting — applied
        # unconditionally so an explicit meeting_ids/staff_ids filter can't be
        # used to reach records outside a scoped manager's remit.
        scope = get_manager_scope(current_user)
        if scope["level"] != "org":
            scoped_ids = await get_scoped_staff_ids(conn, org_id, scope) or []
            scoped_ids = list(set(scoped_ids) | {current_user["id"]})
            params.append(scoped_ids)
            conditions.append(f"(created_by = ANY(${len(params)}::uuid[]) OR sign_off_manager_id = ANY(${len(params)}::uuid[]) OR EXISTS (SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(COALESCE(attendees,'[]'::jsonb)) = 'array' THEN COALESCE(attendees,'[]'::jsonb) ELSE '[]'::jsonb END) a WHERE a->>'user_id' = ANY(${len(params)}::text[])))")

        if meeting_ids:
            params.append(meeting_ids)
            conditions.append(f"id = ANY(${len(params)}::uuid[])")
        else:
            if staff_ids:
                params.append(staff_ids)
                conditions.append(f"EXISTS (SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(COALESCE(attendees,'[]'::jsonb)) = 'array' THEN COALESCE(attendees,'[]'::jsonb) ELSE '[]'::jsonb END) a WHERE a->>'user_id' = ANY(${len(params)}::text[]))")
            if date_from:
                params.append(date_from)
                conditions.append(f"date >= ${len(params)}")
            if date_to:
                params.append(date_to)
                conditions.append(f"date <= ${len(params)}")

        where = " AND ".join(conditions)
        mtg_rows = await conn.fetch(
            f"SELECT id, title, date, analysis_id, transcript_id, pii_redactions, attendees, "
            f"sign_off_manager_id, sign_off_manager_name FROM meetings WHERE {where} ORDER BY date DESC",
            *params,
        )
        mtg_dicts = [dict(r) for r in mtg_rows]
        analysis_ids = list({m["analysis_id"] for m in mtg_dicts if m.get("analysis_id")})
        analyses_by_id = {}
        if analysis_ids:
            a_rows = await conn.fetch(
                "SELECT id, cqc_mappings, care_cert_mappings, custom_mappings FROM analyses WHERE id = ANY($1::uuid[])",
                analysis_ids,
            )
            analyses_by_id = {r["id"]: dict(r) for r in a_rows}

    # Pure Python from here (redaction + CSV row building) — done after the
    # transaction/connection is released, not while holding it open.
    for mtg in mtg_dicts:
        a_row = analyses_by_id.get(mtg["analysis_id"])
        if not a_row:
            continue
        adoc = dict(a_row)
        redactions = _jlist(mtg.get("pii_redactions"))
        if redactions:
            adoc = _apply_redactions_deep(adoc, redactions)
        # SEC-PII-001: redact attendee/manager names too — not just the
        # analysis body — since these are printed verbatim in the PDF/CSV.
        mtg_for_pdf = mtg
        if redactions:
            mtg_for_pdf = dict(mtg)
            mtg_for_pdf["attendees"] = _apply_redactions_deep(mtg.get("attendees") or [], redactions)
            if mtg.get("sign_off_manager_name"):
                mtg_for_pdf["sign_off_manager_name"] = _apply_redactions_to_text(mtg["sign_off_manager_name"], redactions)
        mtg_analyses.append({"meeting": mtg_for_pdf, "analysis": adoc})
        sign_off_mgr_id = str(mtg.get("sign_off_manager_id") or "")
        for attendee in _jlist(mtg_for_pdf.get("attendees")):
            if sign_off_mgr_id and attendee.get("user_id") == sign_off_mgr_id:
                continue
            staff_name = attendee.get("name", "Unknown")
            for m in _jlist(adoc.get("cqc_mappings")):
                rows_csv.append([staff_name, mtg.get("title", ""), mtg.get("date", "")[:10], "CQC", m.get("regulation_ref", ""), m.get("regulation_name", ""), m.get("confidence", ""), m.get("status", "pending"), (m.get("edited_evidence_summary") or m.get("evidence_summary", ""))[:200]])
            for m in _jlist(adoc.get("care_cert_mappings")):
                rows_csv.append([staff_name, mtg.get("title", ""), mtg.get("date", "")[:10], "Care Cert", m.get("standard_ref", ""), m.get("standard_name", ""), m.get("confidence", ""), m.get("status", "pending"), (m.get("edited_evidence_summary") or m.get("evidence_summary", ""))[:200]])
            for m in _jlist(adoc.get("custom_mappings")):
                rows_csv.append([staff_name, mtg.get("title", ""), mtg.get("date", "")[:10], "Organisational", m.get("criterion_ref", ""), m.get("criterion_name", ""), m.get("confidence", ""), m.get("status", "pending"), (m.get("edited_evidence_summary") or m.get("evidence_summary", ""))[:200]])

    if fmt == "csv":
        import csv, io

        def _csv_safe(val: str) -> str:
            """Prevent spreadsheet formula injection (OWASP CSV Injection)."""
            s = str(val) if val is not None else ""
            return ("\t" + s) if s and s[0] in ("=", "+", "-", "@", "|", "%") else s

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Staff Member", "Meeting", "Date", "Evidence Type", "Reference", "Standard Name", "Confidence", "Status", "Evidence Summary"])
        writer.writerows([[_csv_safe(cell) for cell in row] for row in rows_csv])
        return _Response(content=buf.getvalue().encode("utf-8-sig"), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="evidence_export.csv"'})
    else:
        return _Response(content=_generate_export_pdf(mtg_analyses), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="evidence_export.pdf"'})


@router.get("/export-cqc-excerpts")
async def export_cqc_excerpts(current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user.get("org_id", "")
    from collections import defaultdict
    reg_map = defaultdict(list)
    reg_names = {}

    async with database.with_org(org_id) as conn:
        mtg_rows = await conn.fetch(
            "SELECT id, title, date, analysis_id, pii_redactions, attendees, sign_off_manager_id, sign_off_manager_name "
            "FROM meetings WHERE status IN ('in_review','reviewed','signed_off','shared') AND analysis_id IS NOT NULL ORDER BY date DESC"
        )
        mtg_dicts = [dict(r) for r in mtg_rows]
        analysis_ids = list({m["analysis_id"] for m in mtg_dicts if m.get("analysis_id")})
        analyses_by_id = {}
        if analysis_ids:
            a_rows = await conn.fetch(
                "SELECT id, cqc_mappings, care_cert_mappings, custom_mappings FROM analyses WHERE id = ANY($1::uuid[])",
                analysis_ids,
            )
            analyses_by_id = {r["id"]: dict(r) for r in a_rows}

    # Pure Python from here (redaction + regulation grouping) — after the
    # transaction/connection is released.
    for mtg in mtg_dicts:
        a_row = analyses_by_id.get(mtg["analysis_id"])
        if not a_row: continue
        adoc = dict(a_row)
        redactions = _jlist(mtg.get("pii_redactions"))
        if redactions:
            adoc = _apply_redactions_deep(adoc, redactions)
        # SEC-PII-001: attendee/manager names are printed in the excerpt
        # metadata line, so redact them the same as the evidence body.
        attendee_list = _apply_redactions_deep(_jlist(mtg.get("attendees")), redactions) if redactions else _jlist(mtg.get("attendees"))
        attendees = ", ".join(a.get("name", "") for a in attendee_list)
        manager_name = mtg.get("sign_off_manager_name", "")
        if redactions and manager_name:
            manager_name = _apply_redactions_to_text(manager_name, redactions)
        ctx = {"meeting_title": mtg.get("title", "Meeting"), "meeting_date": mtg.get("date", ""), "meeting_id": mtg["id"], "attendees": attendees, "manager": manager_name}
        for m in _jlist(adoc.get("cqc_mappings")):
            if m.get("status") == "rejected": continue
            ref = m.get("regulation_ref", "")
            if not ref: continue
            if ref not in reg_names: reg_names[ref] = m.get("regulation_name", ref)
            reg_map[ref].append({**ctx, **m})

    if not reg_map:
        raise HTTPException(404, "No CQC evidence found in any meetings")
    sorted_refs = sorted(reg_map.keys())
    pdf_bytes = _generate_cqc_excerpts_pdf(sorted_refs, reg_map, reg_names, len({item["meeting_id"] for items in reg_map.values() for item in items}))
    return _Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="cqc_evidence_excerpts.pdf"'})


@router.get("/export-cc-excerpts")
async def export_cc_excerpts(staff_ids: str = None, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user.get("org_id", "")
    selected_ids = [s.strip() for s in staff_ids.split(",") if s.strip()] if staff_ids else []
    from collections import defaultdict
    std_map = defaultdict(list)
    std_names = {}

    async with database.with_org(org_id) as conn:
        mtg_rows = await conn.fetch(
            "SELECT id, title, date, analysis_id, pii_redactions, attendees, sign_off_manager_id, sign_off_manager_name "
            "FROM meetings WHERE status IN ('in_review','reviewed','signed_off','shared') AND analysis_id IS NOT NULL ORDER BY date DESC"
        )
        mtg_dicts = [dict(r) for r in mtg_rows]
        if selected_ids:
            mtg_dicts = [m for m in mtg_dicts if any(a.get("user_id") in selected_ids for a in _jlist(m.get("attendees")))]
        analysis_ids = list({m["analysis_id"] for m in mtg_dicts if m.get("analysis_id")})
        analyses_by_id = {}
        if analysis_ids:
            a_rows = await conn.fetch(
                "SELECT id, cqc_mappings, care_cert_mappings, custom_mappings FROM analyses WHERE id = ANY($1::uuid[])",
                analysis_ids,
            )
            analyses_by_id = {r["id"]: dict(r) for r in a_rows}

    # Pure Python from here (redaction + standard grouping) — after the
    # transaction/connection is released.
    for mtg in mtg_dicts:
        a_row = analyses_by_id.get(mtg["analysis_id"])
        if not a_row: continue
        adoc = dict(a_row)
        redactions = _jlist(mtg.get("pii_redactions"))
        if redactions:
            adoc = _apply_redactions_deep(adoc, redactions)
        sign_off_mgr_id = str(mtg.get("sign_off_manager_id") or "")
        include = [a for a in _jlist(mtg.get("attendees")) if str(a.get("user_id", "")) != sign_off_mgr_id and (not selected_ids or a.get("user_id") in selected_ids)]
        if not include: continue
        # SEC-PII-001: attendee/manager names are printed in the excerpt
        # metadata line, so redact them the same as the evidence body.
        if redactions:
            include = _apply_redactions_deep(include, redactions)
        attendees_str = ", ".join(a.get("name", "") for a in include)
        manager_name = mtg.get("sign_off_manager_name", "")
        if redactions and manager_name:
            manager_name = _apply_redactions_to_text(manager_name, redactions)
        ctx = {"meeting_title": mtg.get("title", "Meeting"), "meeting_date": mtg.get("date", ""), "meeting_id": mtg["id"], "attendees": attendees_str, "manager": manager_name}
        for m in _jlist(adoc.get("care_cert_mappings")):
            if m.get("status") == "rejected": continue
            ref = m.get("standard_ref", "")
            if not ref: continue
            if ref not in std_names: std_names[ref] = m.get("standard_name", ref)
            std_map[ref].append({**ctx, **m})

    if not std_map:
        raise HTTPException(404, "No Care Certificate evidence found for the selected staff")

    sorted_refs = sorted(std_map.keys())
    meeting_count = len({item["meeting_id"] for items in std_map.values() for item in items})
    staff_label = "All staff"
    if selected_ids:
        # SEC-003: with_org() so RLS drops foreign-org user ids from selected_ids
        async with database.with_org(org_id) as conn:
            u_rows = await conn.fetch("SELECT name FROM users WHERE id = ANY($1::uuid[])", selected_ids)
        names = [r["name"] for r in u_rows]
        staff_label = ", ".join(sorted(names)) if names else "Selected staff"
    else:
        names = []

    pdf_bytes = _generate_cc_excerpts_pdf(sorted_refs, std_map, std_names, meeting_count, staff_label)
    filename = f"care_cert_{'_'.join(names).replace(' ', '_')}.pdf" if selected_ids and names else "care_cert_evidence_excerpts.pdf"
    return _Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/export-transcripts")
async def export_transcripts(request: Request, current_user=Depends(get_current_user)):
    data = await request.json()
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    # Rate limit: 10 transcript exports per user / 60 min (shared bucket with evidence exports)
    from utils.rate_limit import check_rate_limit
    async with database.with_admin() as _rl_conn:
        await check_rate_limit(
            _rl_conn,
            identifier=f"export:{current_user['id']}",
            max_attempts=10,
            window_minutes=60,
            error_detail="Export limit reached. A maximum of 10 exports can be generated per hour.",
        )
    org_id = current_user.get("org_id", "")
    staff_ids = data.get("staff_ids") or []
    date_from = data.get("date_from")
    date_to = data.get("date_to")
    meeting_ids = data.get("meeting_ids") or []

    conditions = ["status='signed_off'", "analysis_id IS NOT NULL", "transcript_id IS NOT NULL"]
    params: list = []
    meetings_data = []

    async with database.with_org(org_id) as conn:
        # SEC-002: constrain to the caller's assigned team/setting — applied
        # unconditionally so an explicit meeting_ids/staff_ids filter can't be
        # used to reach records outside a scoped manager's remit.
        scope = get_manager_scope(current_user)
        if scope["level"] != "org":
            scoped_ids = await get_scoped_staff_ids(conn, org_id, scope) or []
            scoped_ids = list(set(scoped_ids) | {current_user["id"]})
            params.append(scoped_ids)
            conditions.append(f"(created_by = ANY(${len(params)}::uuid[]) OR sign_off_manager_id = ANY(${len(params)}::uuid[]) OR EXISTS (SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(COALESCE(attendees,'[]'::jsonb)) = 'array' THEN COALESCE(attendees,'[]'::jsonb) ELSE '[]'::jsonb END) a WHERE a->>'user_id' = ANY(${len(params)}::text[])))")

        if meeting_ids:
            params.append(meeting_ids)
            conditions.append(f"id = ANY(${len(params)}::uuid[])")
        else:
            if staff_ids:
                params.append(staff_ids)
                conditions.append(f"EXISTS (SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(COALESCE(attendees,'[]'::jsonb)) = 'array' THEN COALESCE(attendees,'[]'::jsonb) ELSE '[]'::jsonb END) a WHERE a->>'user_id' = ANY(${len(params)}::text[]))")
            if date_from:
                params.append(date_from)
                conditions.append(f"date >= ${len(params)}")
            if date_to:
                params.append(date_to)
                conditions.append(f"date <= ${len(params)}")

        where = " AND ".join(conditions)
        mtg_rows = await conn.fetch(
            f"SELECT id, title, date, analysis_id, transcript_id, pii_redactions, attendees, "
            f"sign_off_manager_id, sign_off_manager_name FROM meetings WHERE {where} ORDER BY date DESC",
            *params,
        )
        mtg_dicts = [dict(r) for r in mtg_rows]
        transcript_ids = list({m["transcript_id"] for m in mtg_dicts if m.get("transcript_id")})
        transcripts_by_id = {}
        if transcript_ids:
            t_rows = await conn.fetch(
                "SELECT id, speaker_text, text FROM transcripts WHERE id = ANY($1::uuid[])", transcript_ids,
            )
            transcripts_by_id = {r["id"]: r for r in t_rows}

    # Pure Python from here (PII redaction of transcript text) — after the
    # transaction/connection is released.
    for mtg in mtg_dicts:
        t_row = transcripts_by_id.get(mtg["transcript_id"])
        if not t_row: continue
        speaker_text = t_row["speaker_text"] or ""
        transcript_text = t_row["text"] or ""
        redactions = _jlist(mtg.get("pii_redactions"))
        if redactions:
            if speaker_text: speaker_text = _apply_redactions_to_text(speaker_text, redactions)
            if transcript_text: transcript_text = _apply_redactions_to_text(transcript_text, redactions)
        # SEC-PII-001: attendee/manager names are printed in the PDF header
        # for every session, so redact them the same as the transcript body.
        mtg_for_pdf = mtg
        if redactions:
            mtg_for_pdf = dict(mtg)
            mtg_for_pdf["attendees"] = _apply_redactions_deep(mtg.get("attendees") or [], redactions)
            if mtg.get("sign_off_manager_name"):
                mtg_for_pdf["sign_off_manager_name"] = _apply_redactions_to_text(mtg["sign_off_manager_name"], redactions)
        meetings_data.append({"meeting": mtg_for_pdf, "speaker_text": speaker_text, "transcript_text": transcript_text})

    if not meetings_data:
        raise HTTPException(404, "No transcripts found for the selected filters")
    return _Response(content=_generate_bulk_transcripts_pdf(meetings_data), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="transcripts_export.pdf"'})


@router.get("/stats")
async def get_stats(current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user.get("org_id", "")

    # Return cached result if still fresh
    cached = _stats_cache.get(org_id)
    if cached and (time.monotonic() - cached[0]) < _STATS_TTL:
        return cached[1]

    async with database.with_org(org_id) as conn:
        total_meetings = await conn.fetchval("SELECT COUNT(*) FROM meetings")
        signed_off = await conn.fetchval("SELECT COUNT(*) FROM meetings WHERE status='signed_off'")
        in_review = await conn.fetchval("SELECT COUNT(*) FROM meetings WHERE status IN ('in_review','reviewed')")
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE org_id=$1", org_id)
        total_standards = await conn.fetchval(
            "SELECT COUNT(*) FROM standards_entries WHERE is_active=TRUE AND (is_system=TRUE OR org_id=$1)", org_id
        )
    result = {
        "total_meetings": total_meetings,
        "signed_off": signed_off,
        "in_review": in_review,
        "total_users": total_users,
        "total_standards": total_standards,
    }
    _stats_cache[org_id] = (time.monotonic(), result)
    return result


# ── PDF generation helpers (unchanged logic, no db access) ───────────────────

def _generate_cqc_excerpts_pdf(sorted_refs, reg_map, reg_names, meeting_count) -> bytes:
    from io import BytesIO
    from xml.sax.saxutils import escape as _xe
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from datetime import datetime as _dt

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    NAVY = colors.HexColor("#1E3A8A"); PURPLE = colors.HexColor("#7C3AED")
    PURPLE_BG = colors.HexColor("#F5F3FF"); MID_GRAY = colors.HexColor("#6B7280"); LIGHT_BG = colors.HexColor("#F8FAFC")
    title_s = ParagraphStyle("T", fontName="Helvetica-Bold", fontSize=16, textColor=NAVY, spaceAfter=6, leading=20)
    meta_s = ParagraphStyle("M", fontName="Helvetica", fontSize=8, textColor=MID_GRAY, spaceAfter=3, leading=12)
    reg_s = ParagraphStyle("RH", fontName="Helvetica-Bold", fontSize=11, textColor=colors.white, spaceAfter=0, leading=14)
    item_s = ParagraphStyle("EI", fontName="Helvetica", fontSize=8, textColor=colors.HexColor("#374151"), leading=11, spaceAfter=2)
    summary_s = ParagraphStyle("ES", fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#1F2937"), leading=13, spaceAfter=3, leftIndent=4)
    small_s = ParagraphStyle("S", fontName="Helvetica", fontSize=8, textColor=MID_GRAY, spaceAfter=1, leading=11)
    def e(t): return _xe(str(t or ""))
    story = []
    meta_right_s = ParagraphStyle("MR", fontName="Helvetica", fontSize=8, textColor=MID_GRAY, leading=12, alignment=2)
    hdr_row = Table([[Paragraph("CQC Evidence Excerpts", title_s), Paragraph(f"Generated {_dt.now().strftime('%d %b %Y %H:%M')} UTC", meta_right_s)]], colWidths=[120*mm, 50*mm])
    hdr_row.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "BOTTOM"), ("TOPPADDING", (0,0), (-1,-1), 0), ("BOTTOMPADDING", (0,0), (-1,-1), 4), ("LEFTPADDING", (0,0), (-1,-1), 0), ("RIGHTPADDING", (0,0), (-1,-1), 0)]))
    story.append(hdr_row)
    story.append(Paragraph(f"{len(sorted_refs)} regulation(s) | evidence drawn from {meeting_count} meeting(s)", meta_s))
    story.append(HRFlowable(width="100%", thickness=2, color=NAVY, spaceAfter=8))
    for ref in sorted_refs:
        items = reg_map[ref]; name = reg_names.get(ref, ref)
        hdr_tbl = Table([[Paragraph(f'<font color="white"><b>{e(ref)} — {e(name)}</b></font>', reg_s)]], colWidths=[170*mm])
        hdr_tbl.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), PURPLE), ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6), ("LEFTPADDING", (0,0), (-1,-1), 8)]))
        story.append(hdr_tbl)
        for idx, item in enumerate(items):
            conf = item.get("confidence", "").replace("_", " ").title(); status = item.get("status", "pending").title()
            summary = (item.get("edited_evidence_summary") or item.get("evidence_summary", "")).strip()
            excerpt = (item.get("transcript_excerpt", "")).strip()
            bg = PURPLE_BG if idx % 2 == 0 else LIGHT_BG
            meta_text = f'<b>{e(item["meeting_title"])}</b>  ·  {e(item["meeting_date"])}' + (f'  ·  {e(item["attendees"])}' if item["attendees"] else "") + (f'  ·  Mgr: {e(item["manager"])}' if item["manager"] else "") + f'  ·  <font color="#6B7280">{e(conf)} / {e(status)}</font>'
            cell_rows = [Paragraph(meta_text, item_s)]
            if summary: cell_rows.append(Paragraph(e(summary), summary_s))
            if excerpt and excerpt != summary: cell_rows.append(Paragraph(f'<i>"{e(excerpt[:300])}{"…" if len(excerpt) > 300 else ""}"</i>', item_s))
            row_tbl = Table([[cell_rows]], colWidths=[170*mm])
            row_tbl.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), bg), ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5), ("LEFTPADDING", (0,0), (-1,-1), 8), ("RIGHTPADDING", (0,0), (-1,-1), 8), ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#E5E7EB"))]))
            story.append(row_tbl)
        story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MID_GRAY))
    story.append(Paragraph("1two.one — CQC Evidence Excerpts — Confidential", small_s))
    doc.build(story)
    return buf.getvalue()


def _generate_cc_excerpts_pdf(sorted_refs, std_map, std_names, meeting_count, staff_label="All staff") -> bytes:
    from io import BytesIO
    from xml.sax.saxutils import escape as _xe
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from datetime import datetime as _dt

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    NAVY = colors.HexColor("#1E3A8A"); BLUE = colors.HexColor("#2563EB"); BLUE_BG = colors.HexColor("#EFF6FF")
    LIGHT_BG = colors.HexColor("#F8FAFC"); MID_GRAY = colors.HexColor("#6B7280")
    title_s = ParagraphStyle("T", fontName="Helvetica-Bold", fontSize=16, textColor=NAVY, spaceAfter=6, leading=20)
    meta_s = ParagraphStyle("M", fontName="Helvetica", fontSize=8, textColor=MID_GRAY, spaceAfter=3, leading=12)
    hdr_s = ParagraphStyle("RH", fontName="Helvetica-Bold", fontSize=11, textColor=colors.white, spaceAfter=0, leading=14)
    item_s = ParagraphStyle("EI", fontName="Helvetica", fontSize=8, textColor=colors.HexColor("#374151"), leading=11, spaceAfter=2)
    summary_s = ParagraphStyle("ES", fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#1F2937"), leading=13, spaceAfter=3, leftIndent=4)
    small_s = ParagraphStyle("S", fontName="Helvetica", fontSize=8, textColor=MID_GRAY, spaceAfter=1, leading=11)
    def e(t): return _xe(str(t or ""))
    story = []
    meta_right_s = ParagraphStyle("MR", fontName="Helvetica", fontSize=8, textColor=MID_GRAY, leading=12, alignment=2)
    staff_name_s = ParagraphStyle("SN", fontName="Helvetica-Bold", fontSize=13, textColor=NAVY, spaceAfter=2, leading=17)
    hdr_row = Table([[Paragraph("Care Certificate Evidence Excerpts", title_s), Paragraph(f"Generated {_dt.now().strftime('%d %b %Y %H:%M')} UTC", meta_right_s)]], colWidths=[120*mm, 50*mm])
    hdr_row.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "BOTTOM"), ("TOPPADDING", (0,0), (-1,-1), 0), ("BOTTOMPADDING", (0,0), (-1,-1), 4), ("LEFTPADDING", (0,0), (-1,-1), 0), ("RIGHTPADDING", (0,0), (-1,-1), 0)]))
    story.append(hdr_row); story.append(Paragraph(f"<b>{e(staff_label)}</b>", staff_name_s))
    story.append(Paragraph(f"{len(sorted_refs)} standard(s) | evidence drawn from {meeting_count} meeting(s)", meta_s))
    story.append(HRFlowable(width="100%", thickness=2, color=BLUE, spaceAfter=8))
    for ref in sorted_refs:
        items = std_map[ref]; name = std_names.get(ref, ref)
        hdr_tbl = Table([[Paragraph(f'<font color="white"><b>{e(ref)} — {e(name)}</b></font>', hdr_s)]], colWidths=[170*mm])
        hdr_tbl.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), BLUE), ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6), ("LEFTPADDING", (0,0), (-1,-1), 8)]))
        story.append(hdr_tbl)
        for idx, item in enumerate(items):
            conf = item.get("confidence", "").replace("_", " ").title(); status = item.get("status", "pending").title()
            summary = (item.get("edited_evidence_summary") or item.get("evidence_summary", "")).strip()
            excerpt = (item.get("transcript_excerpt", "")).strip(); outcome = item.get("outcome_ref", "")
            bg = BLUE_BG if idx % 2 == 0 else LIGHT_BG
            meta_text = f'<b>{e(item["meeting_title"])}</b>  ·  {e(item["meeting_date"])}' + (f'  ·  {e(item["attendees"])}' if item["attendees"] else "") + (f'  ·  Mgr: {e(item["manager"])}' if item["manager"] else "") + (f'  ·  <i>Outcome: {e(outcome)}</i>' if outcome else "") + f'  ·  <font color="#6B7280">{e(conf)} / {e(status)}</font>'
            cell_rows = [Paragraph(meta_text, item_s)]
            if summary: cell_rows.append(Paragraph(e(summary), summary_s))
            if excerpt and excerpt != summary: cell_rows.append(Paragraph(f'<i>"{e(excerpt[:300])}{"…" if len(excerpt) > 300 else ""}"</i>', item_s))
            row_tbl = Table([[cell_rows]], colWidths=[170*mm])
            row_tbl.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), bg), ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5), ("LEFTPADDING", (0,0), (-1,-1), 8), ("RIGHTPADDING", (0,0), (-1,-1), 8), ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#E5E7EB"))]))
            story.append(row_tbl)
        story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MID_GRAY))
    story.append(Paragraph("1two.one — Care Certificate Evidence Excerpts — Confidential", small_s))
    doc.build(story)
    return buf.getvalue()


def _generate_export_pdf(mtg_analyses: list) -> bytes:
    from io import BytesIO
    from xml.sax.saxutils import escape as _xe
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, PageBreak
    from datetime import datetime as _dt

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    NAVY = colors.HexColor("#1E3A8A"); MID_GRAY = colors.HexColor("#6B7280")
    PURPLE_BG = colors.HexColor("#EDE9FE"); BLUE_BG = colors.HexColor("#EFF6FF"); TEAL_BG = colors.HexColor("#F0FDF4")
    title_s = ParagraphStyle("T", fontName="Helvetica-Bold", fontSize=16, textColor=NAVY, spaceAfter=2)
    h2_s = ParagraphStyle("H2", fontName="Helvetica-Bold", fontSize=11, textColor=NAVY, spaceAfter=3, spaceBefore=8)
    small_s = ParagraphStyle("S", fontName="Helvetica", fontSize=8, textColor=MID_GRAY, spaceAfter=1, leading=11)
    def e(t): return _xe(str(t or ""))
    story = []
    story.append(Paragraph("Supervision 2.0 — Evidence Export", small_s))
    story.append(Paragraph(f"Generated {_dt.now().strftime('%d %b %Y %H:%M')} UTC", small_s))
    story.append(Paragraph(f"{len(mtg_analyses)} meeting(s) included", small_s))
    story.append(HRFlowable(width="100%", thickness=2, color=NAVY, spaceAfter=6))
    def section_hdr(title, bg=NAVY):
        t = Table([[Paragraph(f'<font color="white"><b>{title}</b></font>', ParagraphStyle("SH", fontName="Helvetica-Bold", fontSize=10, textColor=colors.white))]], colWidths=[170*mm])
        t.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), bg), ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5), ("LEFTPADDING", (0,0), (-1,-1), 8)]))
        return t
    for i, item in enumerate(mtg_analyses):
        mtg = item["meeting"]; ana = item["analysis"]
        if i > 0: story.append(PageBreak())
        story.append(Paragraph(e(mtg.get("title", "Meeting")), title_s))
        attendees = ", ".join(a.get("name", "") for a in _jlist(mtg.get("attendees")))
        story.append(Paragraph(f'Date: {e(mtg.get("date", "—"))} | Attendees: {e(attendees)} | Manager: {e(mtg.get("sign_off_manager_name", "—"))}', small_s))
        story.append(Spacer(1, 3*mm))
        for maps, label, bg, ref_key, name_key in [
            (_jlist(ana.get("cqc_mappings")), "CQC Regulatory Evidence", PURPLE_BG, "regulation_ref", "regulation_name"),
            (_jlist(ana.get("care_cert_mappings")), "Care Certificate Evidence", BLUE_BG, "standard_ref", "standard_name"),
            (_jlist(ana.get("custom_mappings")), "Organisational Standards Evidence", TEAL_BG, "criterion_ref", "criterion_name"),
        ]:
            if not maps: continue
            story.append(Paragraph(label, h2_s))
            data_rows = [[m.get(ref_key, ""), m.get(name_key, ""), m.get("confidence", "").replace("_", " ").title(), m.get("status", "pending").title(), (m.get("edited_evidence_summary") or m.get("evidence_summary", ""))[:120]] for m in maps]
            tbl = Table([["Reference", "Standard", "Confidence", "Status", "Evidence Summary"]] + data_rows, colWidths=[22*mm, 40*mm, 28*mm, 18*mm, 62*mm])
            tbl.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), NAVY), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,-1), 8), ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, bg]), ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#E5E7EB")), ("TOPPADDING", (0,0), (-1,-1), 3), ("BOTTOMPADDING", (0,0), (-1,-1), 3), ("LEFTPADDING", (0,0), (-1,-1), 4), ("WORDWRAP", (0,0), (-1,-1), True)]))
            story.append(tbl); story.append(Spacer(1, 2*mm))
    story.append(Spacer(1, 6*mm)); story.append(HRFlowable(width="100%", thickness=0.5, color=MID_GRAY))
    story.append(Paragraph("Supervision 2.0 — Confidential evidence export.", small_s))
    doc.build(story)
    return buf.getvalue()


def _generate_bulk_transcripts_pdf(meetings_data: list) -> bytes:
    import re as _re
    from io import BytesIO
    from xml.sax.saxutils import escape as _xe
    from datetime import datetime as _dt
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, PageBreak

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    NAVY = colors.HexColor("#1E3A8A"); MID_GRAY = colors.HexColor("#6B7280")
    MGMT_NAVY = colors.HexColor("#1E3A8A"); WORKER_GREEN = colors.HexColor("#065F46")
    cover_s = ParagraphStyle("C", fontName="Helvetica-Bold", fontSize=16, textColor=NAVY, spaceAfter=4, leading=20)
    meta_r_s = ParagraphStyle("MR", fontName="Helvetica", fontSize=8, textColor=MID_GRAY, leading=12, alignment=2)
    title_s = ParagraphStyle("T", fontName="Helvetica-Bold", fontSize=13, textColor=NAVY, spaceAfter=2, leading=17)
    name_s = ParagraphStyle("SN", fontName="Helvetica-Bold", fontSize=11, textColor=NAVY, spaceAfter=2, leading=14)
    small_s = ParagraphStyle("S", fontName="Helvetica", fontSize=8, textColor=MID_GRAY, spaceAfter=1, leading=11)
    label_s = ParagraphStyle("L", fontName="Helvetica-Bold", fontSize=7, textColor=colors.white, leading=9)
    turn_s = ParagraphStyle("TT", fontName="Helvetica", fontSize=8.5, textColor=colors.HexColor("#1F2937"), leading=13)
    mono_s = ParagraphStyle("M", fontName="Courier", fontSize=8, textColor=colors.HexColor("#374151"), leading=12, spaceAfter=3)
    def e(t): return _xe(str(t or ""))
    story = []
    cover_hdr = Table([[Paragraph("Supervision Transcripts", cover_s), Paragraph(f"Generated {_dt.now().strftime('%d %b %Y %H:%M')} UTC", meta_r_s)]], colWidths=[120*mm, 50*mm])
    cover_hdr.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "BOTTOM"), ("TOPPADDING", (0,0), (-1,-1), 0), ("BOTTOMPADDING", (0,0), (-1,-1), 4), ("LEFTPADDING", (0,0), (-1,-1), 0), ("RIGHTPADDING", (0,0), (-1,-1), 0)]))
    story.append(cover_hdr); story.append(Paragraph(f"{len(meetings_data)} session(s) included", small_s))
    story.append(HRFlowable(width="100%", thickness=2, color=NAVY, spaceAfter=8))
    for idx, item in enumerate(meetings_data):
        if idx > 0: story.append(PageBreak())
        meeting = item["meeting"]; speaker_text = item["speaker_text"]; transcript_text = item["transcript_text"]
        sign_off_mgr_id = str(meeting.get("sign_off_manager_id") or "")
        supervisees = [a.get("name", "") for a in _jlist(meeting.get("attendees")) if a.get("user_id") != sign_off_mgr_id]
        mtg_hdr = Table([[Paragraph(e(meeting.get("title", "Meeting")), title_s), Paragraph(e(meeting.get("date", "")[:10]), small_s)]], colWidths=[140*mm, 30*mm])
        mtg_hdr.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "BOTTOM"), ("TOPPADDING", (0,0), (-1,-1), 0), ("BOTTOMPADDING", (0,0), (-1,-1), 4), ("LEFTPADDING", (0,0), (-1,-1), 0), ("RIGHTPADDING", (1,0), (1,0), 0), ("ALIGN", (1,0), (1,0), "RIGHT")]))
        story.append(mtg_hdr)
        if supervisees: story.append(Paragraph(", ".join(supervisees), name_s))
        story.append(Paragraph(f"Manager: {e(meeting.get('sign_off_manager_name', '—'))}", small_s))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E1"), spaceAfter=5))
        manager_name = meeting.get("sign_off_manager_name", "")
        manager_words = [w.lower() for w in manager_name.split() if len(w) > 2] if manager_name else []
        if speaker_text:
            turns = []
            for line in speaker_text.split("\n"):
                line = line.strip()
                if not line: continue
                # Handle timestamped lines: "[MM:SS] Speaker Name: text..."
                m = _re.match(r'^(\[\d+:\d+\])\s+([^:]{1,60}):\s*(.+)', line)
                if m:
                    timestamp, speaker, text = m.group(1), m.group(2).strip(), m.group(3).strip()
                    turns.append([speaker, f"{timestamp}  {text}"])
                    continue
                # Plain "Speaker Name: text..." (no timestamp)
                m = _re.match(r'^([^:\[\]]{1,60}):\s*(.+)', line)
                if m:
                    turns.append([m.group(1).strip(), m.group(2).strip()])
                elif turns:
                    turns[-1][1] += " " + line
                else:
                    turns.append(["Speaker", line])
            for speaker, text in turns:
                sl = speaker.lower()
                is_mgr = sl in ("manager", "supervisor") or any(w in sl for w in manager_words)
                color = MGMT_NAVY if is_mgr else WORKER_GREEN
                # Split timestamp prefix from body for styled display
                ts_match = _re.match(r'^(\[\d+:\d+\])\s+(.*)', text, _re.DOTALL)
                if ts_match:
                    ts_str = ts_match.group(1)
                    body_str = ts_match.group(2)
                    text_para = Paragraph(f'<font color="#9CA3AF">{e(ts_str)}</font>  {e(body_str)}', turn_s)
                else:
                    text_para = Paragraph(e(text), turn_s)
                row = [[Paragraph(e(speaker.upper()), label_s), text_para]]
                t = Table(row, colWidths=[32*mm, 138*mm])
                t.setStyle(TableStyle([("BACKGROUND", (0,0), (0,0), color), ("BACKGROUND", (1,0), (1,0), colors.HexColor("#F9FAFB")), ("VALIGN", (0,0), (-1,-1), "TOP"), ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5), ("LEFTPADDING", (0,0), (0,0), 5), ("RIGHTPADDING", (0,0), (0,0), 5), ("LEFTPADDING", (1,0), (1,0), 7), ("RIGHTPADDING", (1,0), (1,0), 6), ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#E5E7EB"))]))
                story.append(t); story.append(Spacer(1, 1*mm))
        elif transcript_text:
            for chunk in transcript_text.split("\n"):
                if chunk.strip(): story.append(Paragraph(e(chunk.strip()), mono_s))
        else:
            story.append(Paragraph("No transcript available.", small_s))
    story.append(Spacer(1, 6*mm)); story.append(HRFlowable(width="100%", thickness=0.5, color=MID_GRAY))
    story.append(Paragraph("1two.one — Transcripts Export — Confidential", small_s))
    doc.build(story)
    return buf.getvalue()



# ── Integration health check ──────────────────────────────────────────────────

@router.post("/standards/reseed")
async def force_reseed_standards(current_user=Depends(get_current_user)):
    """
    Force re-seed all system standards and rewarm the in-memory cache.
    Super-admin only. Use when CQC or other standards are missing from production
    without requiring a full redeploy.
    """
    if current_user["role"] != "super_admin":
        raise HTTPException(403, "Super admin only")

    from utils.seed import seed_standards, seed_welsh_standards, seed_scotland_standards, seed_northern_ireland_standards
    from utils import standards_cache

    results = {}
    try:
        await seed_standards()
        results["england"] = "ok"
    except Exception as e:
        results["england"] = f"error: {e}"

    try:
        await seed_welsh_standards()
        results["wales"] = "ok"
    except Exception as e:
        results["wales"] = f"error: {e}"

    try:
        await seed_scotland_standards()
        results["scotland"] = "ok"
    except Exception as e:
        results["scotland"] = f"error: {e}"

    try:
        await seed_northern_ireland_standards()
        results["northern_ireland"] = "ok"
    except Exception as e:
        results["northern_ireland"] = f"error: {e}"

    # Rewarm the in-process cache so changes are immediately visible
    try:
        async with database.with_admin() as conn:
            await standards_cache.rewarm(conn)
        cache_counts = {k.split(":")[0]: len(v) for k, v in standards_cache._system.items()}
        results["cache"] = cache_counts
    except Exception as e:
        results["cache"] = f"error: {e}"

    logger.info(f"[admin] Force reseed triggered by {current_user.get('email')} — {results}")
    return {"status": "complete", "results": results}


@router.get("/integrations/health")
async def integration_health(current_user=Depends(get_current_user)):
    """
    Returns live connectivity status for OpenAI and AssemblyAI.
    Admin/super_admin only. Safe to call from production to diagnose missing API keys.
    """
    if current_user["role"] not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin only")

    import requests as _req

    results = {}

    # ── OpenAI ───────────────────────────────────────────────────────────────
    openai_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
    if openai_key:
        try:
            r = _req.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {openai_key}"},
                timeout=8,
            )
            results["openai"] = {"configured": True, "status": r.status_code, "ok": r.status_code == 200}
        except Exception as e:
            results["openai"] = {"configured": True, "status": "error", "ok": False, "detail": str(e)}
    else:
        results["openai"] = {"configured": False, "ok": False}

    # ── AssemblyAI (EU) ───────────────────────────────────────────────────────
    aai_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if aai_key:
        try:
            r = _req.get(
                "https://api.eu.assemblyai.com/v2/transcript?limit=1",
                headers={"authorization": aai_key},
                timeout=8,
            )
            results["assemblyai"] = {
                "configured": True,
                "endpoint": "api.eu.assemblyai.com",
                "status": r.status_code,
                "ok": r.status_code == 200,
                "transcript_count": r.json().get("page_details", {}).get("result_count") if r.status_code == 200 else None,
            }
        except Exception as e:
            results["assemblyai"] = {"configured": True, "status": "error", "ok": False, "detail": str(e)}
    else:
        results["assemblyai"] = {"configured": False, "ok": False}

    return results



@router.get("/users/debug-by-email")
async def debug_user_by_email(email: str, current_user=Depends(get_current_user)):
    """Admin: check a user's org membership and meeting visibility by email."""
    if current_user["role"] not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin only")
    caller_org = current_user.get("org_id", "")
    async with database.with_admin() as conn:
        u = await conn.fetchrow(
            "SELECT id, name, email, role, org_id, is_active, must_change_password FROM users WHERE LOWER(email)=LOWER($1)",
            email,
        )
        if not u:
            raise HTTPException(404, "User not found")
        u = dict(u)
        # SEC-002: plain admins may only debug users in their own org
        if current_user["role"] != "super_admin" and u["org_id"] != caller_org:
            raise HTTPException(404, "User not found")

        # Query across all orgs (admin context bypasses RLS).
        # Do NOT pass empty string for UUID org_id — query by user_id only.
        meeting_count = await conn.fetchrow(
            """SELECT COUNT(*) as cnt FROM meetings
               WHERE EXISTS (
                   SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(COALESCE(attendees,'null'::jsonb))='array' THEN attendees ELSE '[]'::jsonb END) a
                   WHERE a->>'user_id' = $1
               )""",
            str(u["id"]),
        )

        org = None
        if u["org_id"]:
            org_row = await conn.fetchrow("SELECT name FROM organisations WHERE id=$1", u["org_id"])
            org = org_row["name"] if org_row else "NOT FOUND IN organisations TABLE"

    issues = []
    if not u["org_id"]:
        issues.append("org_id is NULL — user cannot see meetings unless fixed")
    if not u["is_active"]:
        issues.append("User is inactive (is_active=FALSE)")
    if u.get("must_change_password"):
        issues.append("must_change_password=TRUE — user has not accepted invite yet")

    return {
        "user": u,
        "org_name": org,
        "meetings_as_attendee": meeting_count["cnt"] if meeting_count else 0,
        "issues": issues or None,
    }


@router.get("/users/{user_id}/debug")
async def debug_user(user_id: str, current_user=Depends(get_current_user)):
    """Admin: check a user's org membership and meeting visibility."""
    if current_user["role"] not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin only")
    caller_org = current_user.get("org_id", "")
    async with database.with_admin() as conn:
        u = await conn.fetchrow(
            "SELECT id, name, email, role, org_id, is_active, must_change_password FROM users WHERE id=$1",
            user_id,
        )
        if not u:
            raise HTTPException(404, "User not found")
        u = dict(u)
        # SEC-002: plain admins may only debug users in their own org
        if current_user["role"] != "super_admin" and u["org_id"] != caller_org:
            raise HTTPException(404, "User not found")

        # Count meetings where this user is an attendee (raw SQL, bypasses RLS)
        meeting_count = await conn.fetchrow(
            """SELECT COUNT(*) as cnt FROM meetings
               WHERE EXISTS (
                   SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(COALESCE(attendees,'null'::jsonb))='array' THEN attendees ELSE '[]'::jsonb END) a
                   WHERE a->>'user_id' = $1
               )""",
            str(u["id"]),
        )

        org = None
        if u["org_id"]:
            org_row = await conn.fetchrow("SELECT name FROM organisations WHERE id=$1", u["org_id"])
            org = org_row["name"] if org_row else "NOT FOUND"

    issues = []
    if not u["org_id"]:
        issues.append("org_id is NULL — user cannot see meetings unless fixed")
    if not u["is_active"]:
        issues.append("User is inactive (is_active=FALSE)")
    if u.get("must_change_password"):
        issues.append("must_change_password=TRUE — user has not accepted invite yet")

    return {
        "user":  u,
        "org_name": org,
        "meetings_as_attendee": meeting_count["cnt"] if meeting_count else 0,
        "issues": issues or None,
    }


class FixOrgRequest(BaseModel):
    org_id: str


@router.post("/users/fix-org-by-email")
async def fix_user_org_by_email(data: FixOrgRequest, email: str, current_user=Depends(get_current_user)):
    """Super Admin / Admin: assign an org_id to a user whose org_id is NULL.
    Used to repair invited users who somehow ended up without an org assignment.

    SECURITY (P0-01): a non-super_admin caller may only repair a user whose
    org_id is CURRENTLY NULL — that is the only legitimate documented use
    case for this endpoint. Without this check, any org's admin could look
    up ANY other org's user by email (the lookup runs on with_admin(), which
    bypasses RLS) and silently reassign them into their own org, after which
    the existing org-scoped reset-password/update-user endpoints would treat
    that user as their own and allow a full account takeover. super_admin is
    exempt since cross-org reassignment is a legitimate support action for
    that role. Every successful reassignment is now audit-logged.
    """
    if current_user["role"] not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin only")
    caller_org = current_user.get("org_id", "")

    async with database.with_admin() as conn:
        u = await conn.fetchrow(
            "SELECT id, org_id FROM users WHERE LOWER(email)=LOWER($1)", email
        )
        if not u:
            raise HTTPException(404, "User not found")

        # SECURITY (P0-01): non-super_admins can only repair a user whose
        # org_id is currently NULL. Returns the same 404 as "not found" so a
        # caller cannot use this endpoint to probe whether a given email
        # belongs to a (differently-orged) existing account.
        if current_user["role"] != "super_admin" and u["org_id"] is not None:
            raise HTTPException(404, "User not found")

        # Non-super_admins can only assign their own org
        target_org = data.org_id
        if current_user["role"] != "super_admin" and target_org != caller_org:
            raise HTTPException(403, "You can only assign users to your own organisation")

        # Validate org exists
        org_row = await conn.fetchrow("SELECT name FROM organisations WHERE id=$1", target_org)
        if not org_row:
            raise HTTPException(404, "Organisation not found")

        previous_org = "NULL" if u["org_id"] is None else str(u["org_id"])
        await conn.execute("UPDATE users SET org_id=$1 WHERE id=$2", target_org, u["id"])
        await _audit(
            conn, None, target_org, "user_org_fixed_by_email", current_user["id"], current_user.get("name", ""),
            f"Assigned org_id for {email} (previously {previous_org}) to {org_row['name']} by {current_user['role']} {current_user.get('name', '')}",
        )

    return {"message": f"User org_id set to {target_org} ({org_row['name']})", "user_id": str(u["id"])}


# ── Meeting repair endpoints ───────────────────────────────────────────────────

@router.get("/meetings/{meeting_id}/debug-attendees")
async def debug_meeting_attendees(meeting_id: str, current_user=Depends(get_current_user)):
    """Admin/Super Admin: return raw attendees/shared_with JSONB and user info for a meeting.
    Used to diagnose why a specific user can't see a meeting on their dashboard.
    """
    if current_user["role"] not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin only")
    caller_org = current_user.get("org_id", "")

    async with database.with_admin() as conn:
        row = await conn.fetchrow(
            """SELECT id, title, status, created_by, sign_off_manager_id, org_id,
                      attendees, shared_with,
                      jsonb_typeof(attendees) AS attendees_typeof,
                      jsonb_typeof(shared_with) AS shared_with_typeof
               FROM meetings WHERE id=$1""",
            meeting_id,
        )
        if not row:
            raise HTTPException(404, "Meeting not found")

        m = dict(row)
        # SEC-002: plain admins may only debug meetings in their own org
        if current_user["role"] != "super_admin" and m["org_id"] != caller_org:
            raise HTTPException(404, "Meeting not found")
        # Enrich created_by name
        creator = await conn.fetchrow("SELECT name, email FROM users WHERE id=$1", m["created_by"])
        m["created_by_info"] = dict(creator) if creator else None

        # Parse attendees safely
        raw_attendees = m.pop("attendees")
        raw_shared = m.pop("shared_with")
        if isinstance(raw_attendees, str):
            try:
                raw_attendees = json.loads(raw_attendees)
            except Exception:
                raw_attendees = raw_attendees
        if isinstance(raw_shared, str):
            try:
                raw_shared = json.loads(raw_shared)
            except Exception:
                raw_shared = raw_shared

        return {
            "meeting_id": meeting_id,
            "title": m["title"],
            "status": m["status"],
            "created_by": m["created_by"],
            "created_by_info": m["created_by_info"],
            "sign_off_manager_id": m["sign_off_manager_id"],
            "attendees_raw": raw_attendees,
            "attendees_typeof": m["attendees_typeof"],
            "shared_with_raw": raw_shared,
            "shared_with_typeof": m["shared_with_typeof"],
        }


class AddAttendeeRequest(BaseModel):
    user_email: str


@router.post("/meetings/{meeting_id}/add-attendee")
async def repair_add_attendee(meeting_id: str, data: AddAttendeeRequest, current_user=Depends(get_current_user)):
    """Admin/Super Admin: add a user to a meeting's attendees array.
    Used to repair meetings where the attendees JSONB was empty/corrupt.
    Safe to call multiple times — will not add a duplicate.
    """
    if current_user["role"] not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin only")
    caller_org = current_user.get("org_id", "")

    async with database.with_admin() as conn:
        # Find the user
        user_row = await conn.fetchrow(
            "SELECT id, name, email, role, org_id FROM users WHERE LOWER(email)=LOWER($1)",
            data.user_email,
        )
        if not user_row:
            raise HTTPException(404, f"User not found: {data.user_email}")

        # Find the meeting
        mtg_row = await conn.fetchrow(
            "SELECT id, org_id, attendees FROM meetings WHERE id=$1", meeting_id
        )
        if not mtg_row:
            raise HTTPException(404, "Meeting not found")

        # SEC-002: plain admins may only repair meetings/users in their own org
        if current_user["role"] != "super_admin":
            if mtg_row["org_id"] != caller_org or user_row["org_id"] != caller_org:
                raise HTTPException(404, "Meeting not found")

        uid = str(user_row["id"])
        raw = mtg_row["attendees"]
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = []
        existing: list = raw if isinstance(raw, list) else []

        # De-duplicate: don't add if already present
        if any(str(a.get("user_id", "")) == uid for a in existing if isinstance(a, dict)):
            return {
                "message": "User is already an attendee — no change made",
                "user_id": uid,
                "attendees": existing,
            }

        new_attendee = {
            "user_id": uid,
            "name": user_row["name"],
            "email": user_row["email"],
            "role": user_row["role"],
            "present": True,
            "reviewed": False,
            "reviewed_at": None,
        }
        existing.append(new_attendee)

        await conn.execute(
            "UPDATE meetings SET attendees=$1::jsonb, updated_at=$2 WHERE id=$3",
            existing,
            datetime.now(timezone.utc),
            meeting_id,
        )

    return {
        "message": f"Added {user_row['name']} ({data.user_email}) to meeting attendees",
        "user_id": uid,
        "attendees": existing,
    }
