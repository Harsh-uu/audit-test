import json
import uuid
import re as _re
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, BackgroundTasks, Form, Request
from pydantic import BaseModel, EmailStr
from fastapi.responses import Response as _Response
from deps import get_db, get_current_user, get_manager_scope, get_scoped_staff_ids
from utils.supabase_storage import put_document
from utils.redaction import apply_redactions_deep as _apply_redactions_deep
import database

router = APIRouter()
logger = logging.getLogger(__name__)


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


class ResetPasswordRequest(BaseModel):
    new_password: str


@router.get("/users")
async def list_users(current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user.get("org_id", "")
    scope = get_manager_scope(current_user)
    _cols = "SELECT id, org_id, email, name, role, is_active, team_id, setting_id, created_at FROM users"
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
    role = data.role if data.role in ["admin", "manager", "attendee", "shared_reviewer"] else "attendee"
    user_id = str(uuid.uuid4())
    org_id = current_user.get("org_id", "")
    now = datetime.now(timezone.utc).isoformat()
    async with database.with_admin() as conn:
        existing = await conn.fetchrow("SELECT id FROM users WHERE email = $1", data.email.lower())
        if existing:
            raise HTTPException(400, "Email already exists")
        await conn.execute(
            "INSERT INTO users (id, email, password_hash, name, role, org_id, is_active, must_change_password, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)",
            user_id, data.email.lower(), hash_password(data.password), data.name, role, org_id, True, True, now,
        )
    return {"id": user_id, "email": data.email.lower(), "name": data.name, "role": role}


@router.put("/users/{user_id}")
async def update_user(user_id: str, data: UpdateUserRequest, current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(400, "No update data provided")
    if "email" in update_data:
        update_data["email"] = update_data["email"].lower().strip()
    set_parts = [f"{k}=${i+2}" for i, k in enumerate(update_data.keys())]
    org_id = current_user.get("org_id", "")
    async with database.with_admin() as conn:
        if "email" in update_data:
            clash = await conn.fetchrow("SELECT id FROM users WHERE email = $1 AND id <> $2", update_data["email"], user_id)
            if clash:
                raise HTTPException(400, "Email address already in use")
        u = await conn.fetchrow("SELECT id FROM users WHERE id = $1 AND org_id = $2", user_id, org_id)
        if not u:
            raise HTTPException(404, "User not found")
        await conn.execute(f"UPDATE users SET {', '.join(set_parts)} WHERE id=$1", user_id, *list(update_data.values()))
    return {"message": "User updated"}


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(user_id: str, data: ResetPasswordRequest, current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    if len(data.new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    from routers.auth import hash_password
    org_id = current_user.get("org_id", "")
    async with database.with_admin() as conn:
        u = await conn.fetchrow("SELECT id FROM users WHERE id = $1 AND org_id = $2", user_id, org_id)
        if not u:
            raise HTTPException(404, "User not found")
        await conn.execute("UPDATE users SET password_hash = $1 WHERE id = $2", hash_password(data.new_password), user_id)
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

    async with database.with_admin() as conn:
        # Get org jurisdiction and service_type to filter system standards correctly
        org_row = await conn.fetchrow("SELECT jurisdiction, service_type FROM organisations WHERE id=$1", org_id)
        jurisdiction = (org_row["jurisdiction"] if org_row else None) or "england"
        org_service_type = (org_row["service_type"] if org_row else None)

        if jurisdiction == "northern_ireland":
            # NI: RQIA standards filtered by service_type, NISCC (service_type=NULL) always shown
            if type:
                rows = await conn.fetch(
                    """SELECT * FROM standards_entries
                       WHERE type=$1 AND is_active=TRUE
                       AND ((is_system=TRUE AND jurisdiction='northern_ireland'
                             AND (service_type IS NULL OR service_type=$2))
                            OR org_id=$3)
                       ORDER BY type, reference""",
                    type, org_service_type, org_id,
                )
            else:
                rows = await conn.fetch(
                    """SELECT * FROM standards_entries
                       WHERE is_active=TRUE
                       AND ((is_system=TRUE AND jurisdiction='northern_ireland'
                             AND (service_type IS NULL OR service_type=$1))
                            OR org_id=$2)
                       ORDER BY type, reference""",
                    org_service_type, org_id,
                )
        elif type:
            rows = await conn.fetch(
                """SELECT * FROM standards_entries
                   WHERE type=$1 AND is_active=TRUE
                   AND ((is_system=TRUE AND jurisdiction=$2) OR org_id=$3)
                   ORDER BY type, reference""",
                type, jurisdiction, org_id,
            )
        else:
            rows = await conn.fetch(
                """SELECT * FROM standards_entries
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
    now = datetime.now(timezone.utc).isoformat()
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        await conn.execute(
            """INSERT INTO standards_entries (id, type, reference, name, description, keywords, source,
               is_active, is_system, org_id, created_at, created_by)
               VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9,$10,$11,$12)""",
            std_id, data.type, data.reference, data.name, data.description,
            json.dumps(data.keywords), data.source or "", True, False, org_id, now, current_user["id"],
        )
    return {"id": std_id, "type": data.type, "reference": data.reference, "name": data.name,
            "description": data.description, "org_id": org_id}


@router.delete("/standards/{standard_id}")
async def delete_standard(standard_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    async with database.with_admin() as conn:
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
        rows = await conn.fetch("SELECT * FROM standards_documents ORDER BY created_at DESC")
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
    allowed_ext = {"pdf", "docx", "txt", "md", "csv"}
    file_ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "txt"
    if file_ext not in allowed_ext:
        raise HTTPException(400, f"Unsupported file type: .{file_ext}")

    storage_path = f"standards/docs/{uuid.uuid4()}.{file_ext}"
    try:
        result = await put_document(storage_path, file_data, file.content_type or "application/octet-stream")
        actual_path = result.get("path", storage_path)
    except Exception as e:
        logger.error(f"Document storage failed: {e}")
        actual_path = storage_path

    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        await conn.execute(
            """INSERT INTO standards_documents (id, filename, label, storage_path, content_type, size_bytes,
               parse_status, is_active, org_id, uploaded_by, uploaded_by_name, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
            doc_id, file.filename, label or file.filename, actual_path,
            file.content_type or "application/octet-stream", len(file_data),
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
                text[:5000], doc_summary, json.dumps(criteria), len(criteria),
                datetime.now(timezone.utc).isoformat(), doc_id,
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
    return {"message": "Updated"}


@router.delete("/standards/documents/{doc_id}")
async def delete_document(doc_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Admin/Manager only")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        await conn.execute("DELETE FROM standards_documents WHERE id=$1", doc_id)
    return {"message": "Deleted"}


async def rescan_meetings_background(doc_id: str, org_id: str):
    from utils.ai import analyze_custom_only
    try:
        async with database.with_org(org_id) as conn:
            doc_row = await conn.fetchrow("SELECT * FROM standards_documents WHERE id=$1 AND parse_status='parsed'", doc_id)
            if not doc_row:
                return
            doc = dict(doc_row)
            analysis_rows = await conn.fetch("SELECT * FROM analyses")

        updated = 0
        for a_row in analysis_rows:
            analysis = dict(a_row)
            custom_mappings = analysis.get("custom_mappings") or []
            if any(m.get("document_id") == doc_id for m in custom_mappings):
                continue
            async with database.with_org(org_id) as conn:
                mtg = await conn.fetchrow(
                    "SELECT id, transcript_id FROM meetings WHERE analysis_id=$1", analysis["id"]
                )
            if not mtg or not mtg["transcript_id"]:
                continue
            async with database.with_org(org_id) as conn:
                t_row = await conn.fetchrow("SELECT text FROM transcripts WHERE id=$1", mtg["transcript_id"])
            if not t_row:
                continue
            new_mappings = await analyze_custom_only(t_row["text"], doc)
            if new_mappings:
                async with database.with_org(org_id) as conn:
                    await conn.execute(
                        "UPDATE analyses SET custom_mappings=$1::jsonb WHERE id=$2",
                        json.dumps(custom_mappings + new_mappings), analysis["id"],
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
    d = row["data"] or {}
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
    async with database.with_admin() as conn:
        await conn.execute(
            """INSERT INTO settings (id, org_id, data) VALUES ($1,$2,$3::jsonb)
               ON CONFLICT (id) DO UPDATE SET data=$3::jsonb""",
            key, org_id, json.dumps(payload),
        )
    return {"message": "Template saved", "steps": data.get("steps", [])}


# ── Team Insights ─────────────────────────────────────────────────────────────

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
        # Staff
        if team_id:
            staff_rows = await conn.fetch(
                "SELECT id, name, role FROM users WHERE org_id=$1 AND role IN ('attendee','manager') AND is_active=TRUE AND team_id=$2",
                org_id, team_id,
            )
        elif setting_id:
            staff_rows = await conn.fetch(
                "SELECT id, name, role FROM users WHERE org_id=$1 AND role IN ('attendee','manager') AND is_active=TRUE AND setting_id=$2",
                org_id, setting_id,
            )
        elif current_user["role"] == "manager":
            mgr_scope = get_manager_scope(current_user)
            if mgr_scope["level"] == "team":
                staff_rows = await conn.fetch(
                    "SELECT id, name, role FROM users WHERE org_id=$1 AND role IN ('attendee','manager') AND is_active=TRUE AND team_id=$2",
                    org_id, mgr_scope["team_id"],
                )
            elif mgr_scope["level"] == "setting":
                staff_rows = await conn.fetch(
                    "SELECT id, name, role FROM users WHERE org_id=$1 AND role IN ('attendee','manager') AND is_active=TRUE AND setting_id=$2",
                    org_id, mgr_scope["setting_id"],
                )
            else:
                staff_rows = await conn.fetch(
                    "SELECT id, name, role FROM users WHERE org_id=$1 AND role IN ('attendee','manager') AND is_active=TRUE",
                    org_id,
                )
        else:
            staff_rows = await conn.fetch(
                "SELECT id, name, role FROM users WHERE org_id=$1 AND role IN ('attendee','manager') AND is_active=TRUE",
                org_id,
            )

        staff = [dict(r) for r in staff_rows]
        if not staff:
            return {
                "staff_count": 0, "meeting_count": 0,
                "matrix": {"cqc": {"standards": [], "rows": []}, "care_cert": {"standards": [], "rows": []}, "custom": {"standards": [], "rows": []}},
                "themes": {"coverage_gaps": [], "common_risks": [], "outstanding_actions": []},
            }

    # Get org jurisdiction to load the correct framework standards
    async with database.with_admin() as conn:
        org_info = await conn.fetchrow("SELECT jurisdiction, service_type FROM organisations WHERE id=$1", org_id)
    org_jurisdiction = (org_info["jurisdiction"] if org_info else None) or "england"
    org_service_type = (org_info["service_type"] if org_info else None)

    # Standards — jurisdiction-aware (reg types map to "cqc" matrix key; cert types to "care_cert")
    REG_TYPES = {"cqc", "ciw", "ci", "rqia_dom", "rqia_res"}
    async with database.with_org(org_id) as conn:
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
                subs = s.get("sub_outcomes") or []
                if subs:
                    cc_sub_outcomes[s["reference"]] = [so["ref"] for so in subs]

        cqc_stds.sort(key=lambda x: _ref_nums(x["ref"]))
        cc_stds.sort(key=lambda x: _ref_nums(x["ref"]))

        # Meetings with analyses
        date_conds = ["status IN ('in_review','reviewed','signed_off','shared')", "analysis_id IS NOT NULL"]
        date_params: list = []
        if date_from:
            date_params.append(date_from)
            date_conds.append(f"date >= ${len(date_params)}")
        if date_to:
            date_params.append(date_to + "T23:59:59")
            date_conds.append(f"date <= ${len(date_params)}")
        mtg_rows = await conn.fetch(
            f"SELECT * FROM meetings WHERE {' AND '.join(date_conds)}",
            *date_params,
        )
        all_items = []
        for mtg_row in mtg_rows:
            mtg = dict(mtg_row)
            a_row = await conn.fetchrow("SELECT * FROM analyses WHERE id=$1", mtg["analysis_id"])
            if a_row:
                all_items.append({"meeting": mtg, "analysis": dict(a_row)})

    staff_ids = {s["id"] for s in staff}

    def empty_cqc(): return {"likely": 0, "review": 0, "total": 0, "last_date": "", "latest_excerpt": "", "source_meeting_id": ""}
    def empty_cc(): return {"likely": 0, "review": 0, "total": 0, "last_date": "", "latest_excerpt": "", "source_meeting_id": "", "covered_refs": set()}

    cqc_ev = {s["id"]: {} for s in staff}
    cc_ev = {s["id"]: {} for s in staff}
    cust_ev = {s["id"]: {} for s in staff}
    cust_names: dict = {}
    all_risks, all_outstanding = [], []

    for item in all_items:
        mtg, ana = item["meeting"], item["analysis"]
        date = mtg.get("date", "")
        sign_off_mgr_id = str(mtg.get("sign_off_manager_id") or "")
        for attendee in (mtg.get("attendees") or []):
            uid = attendee.get("user_id", "")
            if uid not in staff_ids or (sign_off_mgr_id and uid == sign_off_mgr_id):
                continue
            for m in (ana.get("cqc_mappings") or []):
                if m.get("status") == "rejected": continue
                ref = m.get("regulation_ref", "")
                if not ref: continue
                if ref not in cqc_ev[uid]: cqc_ev[uid][ref] = empty_cqc()
                c = cqc_ev[uid][ref]
                c["total"] += 1
                if m.get("confidence") == "likely_evidence": c["likely"] += 1
                elif m.get("confidence") == "needs_review": c["review"] += 1
                if date > c["last_date"]:
                    c["last_date"] = date
                    if m.get("transcript_excerpt"):
                        c["latest_excerpt"] = m["transcript_excerpt"][:200]
                        c["source_meeting_id"] = str(mtg.get("id", ""))
            for m in (ana.get("care_cert_mappings") or []):
                if m.get("status") == "rejected": continue
                std_ref = m.get("standard_ref", "")
                if not std_ref: continue
                if std_ref not in cc_ev[uid]: cc_ev[uid][std_ref] = empty_cc()
                c = cc_ev[uid][std_ref]
                c["total"] += 1
                if m.get("confidence") == "likely_evidence": c["likely"] += 1
                elif m.get("confidence") == "needs_review": c["review"] += 1
                if date > c["last_date"]:
                    c["last_date"] = date
                    if m.get("transcript_excerpt"):
                        c["latest_excerpt"] = m["transcript_excerpt"][:200]
                        c["source_meeting_id"] = str(mtg.get("id", ""))
                or_ref = m.get("outcome_ref", "")
                if or_ref: c["covered_refs"].add(or_ref)
            for m in (ana.get("custom_mappings") or []):
                if m.get("status") == "rejected": continue
                ref = m.get("criterion_ref", "") or m.get("document_name", "")
                if not ref: continue
                cust_names.setdefault(ref, m.get("criterion_name", ref))
                if ref not in cust_ev[uid]: cust_ev[uid][ref] = empty_cqc()
                c = cust_ev[uid][ref]
                c["total"] += 1
                if m.get("confidence") == "likely_evidence": c["likely"] += 1
                elif m.get("confidence") == "needs_review": c["review"] += 1
                if date > c["last_date"]:
                    c["last_date"] = date
                    if m.get("transcript_excerpt"):
                        c["latest_excerpt"] = m["transcript_excerpt"][:200]
                        c["source_meeting_id"] = str(mtg.get("id", ""))
        for risk in (ana.get("risks") or []):
            text = risk if isinstance(risk, str) else (risk.get("text", "") if isinstance(risk, dict) else "")
            if text.strip(): all_risks.append(text.strip())
        for action in (ana.get("actions") or []):
            if isinstance(action, dict) and not action.get("completed", False):
                t = action.get("text", "").strip()
                if t: all_outstanding.append(t)

    def build_cqc_matrix(stds, ev_map):
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
            rows.append({"staff_id": s["id"], "staff_name": s["name"], "cells": cells})
        return {"standards": stds, "rows": rows}

    def build_cc_matrix(stds, ev_map):
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
            rows.append({"staff_id": s["id"], "staff_name": s["name"], "cells": cells})
        return {"standards": stds, "rows": rows}

    def build_custom_matrix(stds, ev_map):
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
            rows.append({"staff_id": s["id"], "staff_name": s["name"], "cells": cells})
        return {"standards": stds, "rows": rows}

    cust_stds = [{"ref": r, "name": cust_names.get(r, r)} for r in sorted(cust_names)]

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

    def agg(items, top=10):
        counts: dict = {}
        for text in items:
            key = text[:60].lower()
            if key not in counts: counts[key] = {"text": text, "count": 0}
            counts[key]["count"] += 1
        return sorted(counts.values(), key=lambda x: -x["count"])[:top]

    return {
        "staff_count": len(staff), "meeting_count": len(all_items),
        "matrix": {
            "cqc": build_cqc_matrix(cqc_stds, cqc_ev),
            "care_cert": build_cc_matrix(cc_stds, cc_ev),
            "custom": build_custom_matrix(cust_stds, cust_ev),
        },
        "themes": {"coverage_gaps": gaps, "common_risks": agg(all_risks), "outstanding_actions": agg(all_outstanding)},
    }


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
                     AND (created_by = ANY($1)
                          OR sign_off_manager_id = ANY($1)
                          OR EXISTS (SELECT 1 FROM jsonb_array_elements(attendees) a
                                     WHERE a->>'user_id' = ANY($1)))
                   ORDER BY date DESC""",
                scoped_ids,
            )
        else:
            rows = await conn.fetch(
                "SELECT id, title, date, attendees FROM meetings WHERE status IN ('signed_off','shared') ORDER BY date DESC"
            )
    return [{"id": r["id"], "title": r["title"], "date": r["date"],
             "attendees": [{"user_id": a.get("user_id"), "name": a.get("name")} for a in (r["attendees"] or [])]}
            for r in rows]


@router.post("/export-evidence")
async def export_evidence(request: Request, current_user=Depends(get_current_user)):
    data = await request.json()
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user.get("org_id", "")
    fmt = data.get("format", "csv")
    staff_ids = data.get("staff_ids") or []
    date_from = data.get("date_from")
    date_to = data.get("date_to")
    meeting_ids = data.get("meeting_ids") or []

    conditions = ["status IN ('signed_off','shared')", "analysis_id IS NOT NULL"]
    params: list = []

    if meeting_ids:
        params.append(meeting_ids)
        conditions.append(f"id = ANY(${len(params)})")
    else:
        if staff_ids:
            params.append(staff_ids)
            conditions.append(f"EXISTS (SELECT 1 FROM jsonb_array_elements(attendees) a WHERE a->>'user_id' = ANY(${len(params)}))")
        if date_from:
            params.append(date_from)
            conditions.append(f"date >= ${len(params)}")
        if date_to:
            params.append(date_to)
            conditions.append(f"date <= ${len(params)}")

    where = " AND ".join(conditions)
    rows_csv, mtg_analyses = [], []

    async with database.with_org(org_id) as conn:
        mtg_rows = await conn.fetch(f"SELECT * FROM meetings WHERE {where} ORDER BY date DESC", *params)
        for mtg_row in mtg_rows:
            mtg = dict(mtg_row)
            a_row = await conn.fetchrow("SELECT * FROM analyses WHERE id=$1", mtg["analysis_id"])
            if not a_row:
                continue
            adoc = dict(a_row)
            redactions = mtg.get("pii_redactions") or []
            if redactions:
                adoc = _apply_redactions_deep(adoc, redactions)
            mtg_analyses.append({"meeting": mtg, "analysis": adoc})
            sign_off_mgr_id = str(mtg.get("sign_off_manager_id") or "")
            for attendee in (mtg.get("attendees") or []):
                if sign_off_mgr_id and attendee.get("user_id") == sign_off_mgr_id:
                    continue
                staff_name = attendee.get("name", "Unknown")
                for m in (adoc.get("cqc_mappings") or []):
                    rows_csv.append([staff_name, mtg.get("title", ""), mtg.get("date", "")[:10], "CQC", m.get("regulation_ref", ""), m.get("regulation_name", ""), m.get("confidence", ""), m.get("status", "pending"), (m.get("edited_evidence_summary") or m.get("evidence_summary", ""))[:200]])
                for m in (adoc.get("care_cert_mappings") or []):
                    rows_csv.append([staff_name, mtg.get("title", ""), mtg.get("date", "")[:10], "Care Cert", m.get("standard_ref", ""), m.get("standard_name", ""), m.get("confidence", ""), m.get("status", "pending"), (m.get("edited_evidence_summary") or m.get("evidence_summary", ""))[:200]])
                for m in (adoc.get("custom_mappings") or []):
                    rows_csv.append([staff_name, mtg.get("title", ""), mtg.get("date", "")[:10], "Organisational", m.get("criterion_ref", ""), m.get("criterion_name", ""), m.get("confidence", ""), m.get("status", "pending"), (m.get("edited_evidence_summary") or m.get("evidence_summary", ""))[:200]])

    if fmt == "csv":
        import csv, io
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Staff Member", "Meeting", "Date", "Evidence Type", "Reference", "Standard Name", "Confidence", "Status", "Evidence Summary"])
        writer.writerows(rows_csv)
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
            "SELECT * FROM meetings WHERE status IN ('in_review','reviewed','signed_off','shared') AND analysis_id IS NOT NULL ORDER BY date DESC"
        )
        for mtg_row in mtg_rows:
            mtg = dict(mtg_row)
            a_row = await conn.fetchrow("SELECT * FROM analyses WHERE id=$1", mtg["analysis_id"])
            if not a_row: continue
            adoc = dict(a_row)
            redactions = mtg.get("pii_redactions") or []
            if redactions:
                adoc = _apply_redactions_deep(adoc, redactions)
            attendees = ", ".join(a.get("name", "") for a in (mtg.get("attendees") or []))
            ctx = {"meeting_title": mtg.get("title", "Meeting"), "meeting_date": mtg.get("date", ""), "meeting_id": mtg["id"], "attendees": attendees, "manager": mtg.get("sign_off_manager_name", "")}
            for m in (adoc.get("cqc_mappings") or []):
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
            "SELECT * FROM meetings WHERE status IN ('in_review','reviewed','signed_off','shared') AND analysis_id IS NOT NULL ORDER BY date DESC"
        )
        for mtg_row in mtg_rows:
            mtg = dict(mtg_row)
            if selected_ids and not any(a.get("user_id") in selected_ids for a in (mtg.get("attendees") or [])):
                continue
            a_row = await conn.fetchrow("SELECT * FROM analyses WHERE id=$1", mtg["analysis_id"])
            if not a_row: continue
            adoc = dict(a_row)
            redactions = mtg.get("pii_redactions") or []
            if redactions:
                adoc = _apply_redactions_deep(adoc, redactions)
            sign_off_mgr_id = str(mtg.get("sign_off_manager_id") or "")
            include = [a for a in (mtg.get("attendees") or []) if str(a.get("user_id", "")) != sign_off_mgr_id and (not selected_ids or a.get("user_id") in selected_ids)]
            if not include: continue
            attendees_str = ", ".join(a.get("name", "") for a in include)
            ctx = {"meeting_title": mtg.get("title", "Meeting"), "meeting_date": mtg.get("date", ""), "meeting_id": mtg["id"], "attendees": attendees_str, "manager": mtg.get("sign_off_manager_name", "")}
            for m in (adoc.get("care_cert_mappings") or []):
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
        async with database.with_admin() as conn:
            u_rows = await conn.fetch("SELECT name FROM users WHERE id = ANY($1)", selected_ids)
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
    org_id = current_user.get("org_id", "")
    staff_ids = data.get("staff_ids") or []
    date_from = data.get("date_from")
    date_to = data.get("date_to")
    meeting_ids = data.get("meeting_ids") or []

    conditions = ["status='signed_off'", "analysis_id IS NOT NULL", "transcript_id IS NOT NULL"]
    params: list = []
    if meeting_ids:
        params.append(meeting_ids)
        conditions.append(f"id = ANY(${len(params)})")
    else:
        if staff_ids:
            params.append(staff_ids)
            conditions.append(f"EXISTS (SELECT 1 FROM jsonb_array_elements(attendees) a WHERE a->>'user_id' = ANY(${len(params)}))")
        if date_from:
            params.append(date_from)
            conditions.append(f"date >= ${len(params)}")
        if date_to:
            params.append(date_to)
            conditions.append(f"date <= ${len(params)}")

    where = " AND ".join(conditions)
    meetings_data = []

    async with database.with_org(org_id) as conn:
        mtg_rows = await conn.fetch(f"SELECT * FROM meetings WHERE {where} ORDER BY date DESC", *params)
        for mtg_row in mtg_rows:
            mtg = dict(mtg_row)
            t_row = await conn.fetchrow("SELECT speaker_text, text FROM transcripts WHERE id=$1", mtg["transcript_id"])
            if not t_row: continue
            speaker_text = t_row["speaker_text"] or ""
            transcript_text = t_row["text"] or ""
            redactions = mtg.get("pii_redactions") or []
            if redactions:
                from utils.redaction import apply_redactions_to_text as _art
                if speaker_text: speaker_text = _art(speaker_text, redactions)
                if transcript_text: transcript_text = _art(transcript_text, redactions)
            meetings_data.append({"meeting": mtg, "speaker_text": speaker_text, "transcript_text": transcript_text})

    if not meetings_data:
        raise HTTPException(404, "No transcripts found for the selected filters")
    return _Response(content=_generate_bulk_transcripts_pdf(meetings_data), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="transcripts_export.pdf"'})


@router.get("/stats")
async def get_stats(current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(403, "Insufficient permissions")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        total_meetings = await conn.fetchval("SELECT COUNT(*) FROM meetings")
        signed_off = await conn.fetchval("SELECT COUNT(*) FROM meetings WHERE status='signed_off'")
        in_review = await conn.fetchval("SELECT COUNT(*) FROM meetings WHERE status IN ('in_review','reviewed')")
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE org_id=$1", org_id)
        total_standards = await conn.fetchval(
            "SELECT COUNT(*) FROM standards_entries WHERE is_active=TRUE AND (is_system=TRUE OR org_id=$1)", org_id
        )
    return {"total_meetings": total_meetings, "signed_off": signed_off, "in_review": in_review, "total_users": total_users, "total_standards": total_standards}


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
        attendees = ", ".join(a.get("name", "") for a in (mtg.get("attendees") or []))
        story.append(Paragraph(f'Date: {e(mtg.get("date", "—"))} | Attendees: {e(attendees)} | Manager: {e(mtg.get("sign_off_manager_name", "—"))}', small_s))
        story.append(Spacer(1, 3*mm))
        for maps, label, bg, ref_key, name_key in [
            (ana.get("cqc_mappings", []), "CQC Regulatory Evidence", PURPLE_BG, "regulation_ref", "regulation_name"),
            (ana.get("care_cert_mappings", []), "Care Certificate Evidence", BLUE_BG, "standard_ref", "standard_name"),
            (ana.get("custom_mappings", []), "Organisational Standards Evidence", TEAL_BG, "criterion_ref", "criterion_name"),
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
        supervisees = [a.get("name", "") for a in (meeting.get("attendees") or []) if a.get("user_id") != sign_off_mgr_id]
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
                m = _re.match(r'^([^:]{1,50}):\s*(.+)', line)
                if m: turns.append([m.group(1).strip(), m.group(2).strip()])
                elif turns: turns[-1][1] += " " + line
                else: turns.append(["Speaker", line])
            for speaker, text in turns:
                sl = speaker.lower()
                is_mgr = sl in ("manager", "supervisor") or any(w in sl for w in manager_words)
                color = MGMT_NAVY if is_mgr else WORKER_GREEN
                row = [[Paragraph(e(speaker.upper()), label_s), Paragraph(e(text), turn_s)]]
                t = Table(row, colWidths=[22*mm, 148*mm])
                t.setStyle(TableStyle([("BACKGROUND", (0,0), (0,0), color), ("BACKGROUND", (1,0), (1,0), colors.HexColor("#F9FAFB")), ("VALIGN", (0,0), (-1,-1), "TOP"), ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4), ("LEFTPADDING", (0,0), (0,0), 4), ("RIGHTPADDING", (0,0), (0,0), 4), ("LEFTPADDING", (1,0), (1,0), 6), ("RIGHTPADDING", (1,0), (1,0), 6), ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#E5E7EB"))]))
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
