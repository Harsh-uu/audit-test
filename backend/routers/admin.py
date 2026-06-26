from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, BackgroundTasks, Form
from pydantic import BaseModel, EmailStr
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional
import re as _re
import uuid
import logging
from deps import get_db, get_current_user
from utils.storage import put_object

router = APIRouter()
logger = logging.getLogger(__name__)


def _ref_nums(ref: str):
    """Natural numeric sort key — 'Standard 10' → [10], 'Regulation 9' → [9]."""
    return [int(n) for n in _re.findall(r'\d+', ref)] or [0]


def doc_to_dict(doc):
    if doc is None:
        return None
    doc = dict(doc)
    doc["id"] = str(doc["_id"])
    del doc["_id"]
    return doc


class CreateUserRequest(BaseModel):
    email: EmailStr
    name: str
    role: str
    password: str


class UpdateUserRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class CreateStandardRequest(BaseModel):
    type: str  # cqc | care_cert
    reference: str
    name: str
    description: str
    keywords: list = []
    source: Optional[str] = None


@router.get("/users")
async def list_users(db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    users = []
    async for doc in db.users.find({}, {"password_hash": 0}).sort("name", 1):
        users.append(doc_to_dict(doc))
    return users


@router.post("/users")
async def create_user(data: CreateUserRequest, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    from routers.auth import hash_password
    existing = await db.users.find_one({"email": data.email.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="Email already exists")
    role = data.role if data.role in ["admin", "manager", "attendee", "shared_reviewer"] else "attendee"
    doc = {
        "email": data.email.lower(),
        "password_hash": hash_password(data.password),
        "name": data.name,
        "role": role,
        "is_active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    result = await db.users.insert_one(doc)
    return {"id": str(result.inserted_id), "email": doc["email"], "name": doc["name"], "role": doc["role"]}


@router.put("/users/{user_id}")
async def update_user(user_id: str, data: UpdateUserRequest, db=Depends(get_db), current_user=Depends(get_current_user)):  # noqa: E501
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No update data provided")
    await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": update_data})
    return {"message": "User updated"}


@router.get("/standards")
async def list_standards(type: Optional[str] = None, db=Depends(get_db), current_user=Depends(get_current_user)):
    query = {"is_active": True}
    if type:
        query["type"] = type
    standards = []
    async for doc in db.standards_entries.find(query).sort([("type", 1), ("reference", 1)]):
        standards.append(doc_to_dict(doc))
    return standards


@router.post("/standards")
async def create_standard(data: CreateStandardRequest, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "type": data.type,
        "reference": data.reference,
        "name": data.name,
        "description": data.description,
        "keywords": data.keywords,
        "source": data.source or "",
        "is_active": True,
        "created_at": now,
        "created_by": current_user["id"],
    }
    result = await db.standards_entries.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    del doc["_id"]
    return doc


@router.delete("/standards/{standard_id}")
async def delete_standard(standard_id: str, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    await db.standards_entries.update_one({"_id": ObjectId(standard_id)}, {"$set": {"is_active": False}})
    return {"message": "Standard deactivated"}


@router.get("/standards/documents")
async def list_documents(db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Admin/Manager only")
    docs = []
    async for doc in db.standards_documents.find({}).sort("created_at", -1):
        docs.append(doc_to_dict(doc))
    return docs


@router.post("/standards/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    label: str = Form(""),
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Admin/Manager only")

    file_data = await file.read()
    if len(file_data) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    allowed_ext = {"pdf", "docx", "txt", "md", "csv"}
    file_ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "txt"
    if file_ext not in allowed_ext:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: .{file_ext}. Allowed: {', '.join(allowed_ext)}")  # noqa: E501

    storage_path = f"standards/docs/{uuid.uuid4()}.{file_ext}"
    try:
        result = put_object(storage_path, file_data, file.content_type or "application/octet-stream")
        actual_path = result.get("path", storage_path)
    except Exception as e:
        logger.error(f"Document storage failed: {e}")
        actual_path = storage_path

    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "filename": file.filename,
        "label": label or file.filename,
        "storage_path": actual_path,
        "content_type": file.content_type or "application/octet-stream",
        "size_bytes": len(file_data),
        "parse_status": "parsing",
        "is_active": True,
        "uploaded_by": current_user["id"],
        "uploaded_by_name": current_user.get("name", ""),
        "created_at": now,
    }
    result = await db.standards_documents.insert_one(doc)
    doc_id = str(result.inserted_id)
    doc["id"] = doc_id

    # Background: extract text + AI criteria extraction
    background_tasks.add_task(parse_document_background, doc_id, file_data, file.filename, label or file.filename, db)

    del doc["_id"]
    return doc


async def parse_document_background(doc_id: str, file_data: bytes, filename: str, label: str, db):
    """Extract text and run AI criteria extraction in background."""
    try:
        from utils.document_parser import extract_text
        from utils.ai import extract_document_criteria

        text = extract_text(file_data, filename)
        if not text.strip():
            await db.standards_documents.update_one(
                {"_id": ObjectId(doc_id)},
                {"$set": {"parse_status": "failed", "parse_error": "No text could be extracted"}}
            )
            return

        criteria_result = await extract_document_criteria(text, label)
        criteria = criteria_result.get("criteria", [])
        doc_summary = criteria_result.get("document_summary", "")

        await db.standards_documents.update_one(
            {"_id": ObjectId(doc_id)},
            {"$set": {
                "parse_status": "parsed",
                "extracted_text": text[:5000],  # Store a preview only
                "document_summary": doc_summary,
                "extracted_criteria": criteria,
                "criteria_count": len(criteria),
                "parsed_at": datetime.now(timezone.utc).isoformat(),
            }}
        )
        logger.info(f"Document {doc_id} parsed: {len(criteria)} criteria extracted")
        # Auto-rescan all existing analyses against this new document
        await rescan_meetings_background(doc_id, db)
    except Exception as e:
        logger.error(f"Document parse failed for {doc_id}: {e}")
        await db.standards_documents.update_one(
            {"_id": ObjectId(doc_id)},
            {"$set": {"parse_status": "failed", "parse_error": str(e)}}
        )


@router.patch("/standards/documents/{doc_id}")
async def update_document(doc_id: str, data: dict, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Admin/Manager only")
    allowed = {"is_active", "label"}
    update = {k: v for k, v in data.items() if k in allowed}
    if not update:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    await db.standards_documents.update_one({"_id": ObjectId(doc_id)}, {"$set": update})
    return {"message": "Updated"}


@router.delete("/standards/documents/{doc_id}")
async def delete_document(doc_id: str, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Admin/Manager only")
    await db.standards_documents.delete_one({"_id": ObjectId(doc_id)})
    return {"message": "Deleted"}


@router.get("/template")
async def get_template(db=Depends(get_db), current_user=Depends(get_current_user)):
    doc = await db.settings.find_one({"_id": "supervision_template"})
    if not doc:
        return {"steps": [], "name": "Supervision Template", "description": ""}
    return {"steps": doc.get("steps", []), "name": doc.get("name", "Supervision Template"), "description": doc.get("description", "")}  # noqa: E501


@router.put("/template")
async def save_template(data: dict, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Admin/Manager only")
    now = datetime.now(timezone.utc).isoformat()
    await db.settings.replace_one(
        {"_id": "supervision_template"},
        {
            "_id": "supervision_template",
            "steps": data.get("steps", []),
            "name": data.get("name", "Supervision Template"),
            "description": data.get("description", ""),
            "updated_at": now,
            "updated_by_name": current_user.get("name", ""),
        },
        upsert=True,
    )
    return {"message": "Template saved", "steps": data.get("steps", [])}


async def rescan_meetings_background(doc_id: str, db):
    """After a doc is parsed, scan all analysed meetings against it for new evidence."""
    from utils.ai import analyze_custom_only
    try:
        doc = await db.standards_documents.find_one({"_id": ObjectId(doc_id)})
        if not doc or doc.get("parse_status") != "parsed":
            return
        doc["id"] = str(doc["_id"])
        updated = 0
        async for analysis in db.analyses.find({}):
            # Skip if already mapped for this doc
            already = any(m.get("document_id") == doc_id for m in analysis.get("custom_mappings", []))
            if already:
                continue
            meeting = await db.meetings.find_one({"analysis_id": str(analysis["_id"])})
            if not meeting or not meeting.get("transcript_id"):
                continue
            tdoc = await db.transcripts.find_one({"_id": ObjectId(meeting["transcript_id"])})
            if not tdoc:
                continue
            new_mappings = await analyze_custom_only(tdoc.get("text", ""), doc)
            if new_mappings:
                current = analysis.get("custom_mappings", [])
                await db.analyses.update_one(
                    {"_id": analysis["_id"]},
                    {"$set": {"custom_mappings": current + new_mappings}}
                )
                updated += 1
        logger.info(f"Auto-rescan complete: {updated} meeting(s) updated for doc '{doc.get('label', doc_id)}'")
    except Exception as e:
        logger.error(f"Auto-rescan failed for doc {doc_id}: {e}")


@router.get("/team-insights")
async def get_team_insights(db=Depends(get_db), current_user=Depends(get_current_user)):
    """Returns evidence matrix + team themes for all staff."""
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # ── Staff ──────────────────────────────────────────────────────────────
    staff = []
    async for u in db.users.find({"role": {"$in": ["attendee", "manager"]}, "is_active": {"$ne": False}}):
        staff.append({"id": str(u["_id"]), "name": u.get("name", ""), "role": u.get("role", "")})

    if not staff:
        return {
            "staff_count": 0, "meeting_count": 0,
            "matrix": {
                "cqc": {"standards": [], "rows": []},
                "care_cert": {"standards": [], "rows": []},
                "custom": {"standards": [], "rows": []},
            },
            "themes": {"coverage_gaps": [], "common_risks": [], "outstanding_actions": []},
        }

    staff_ids = {s["id"] for s in staff}

    # ── Standards ──────────────────────────────────────────────────────────
    cqc_stds, cc_stds = [], []
    # Build Care Cert sub-outcomes lookup: standard_ref → list of sub-outcome refs
    cc_sub_outcomes: dict = {}  # "Standard 2" → ["2.1a", "2.1b", ...]
    async for s in db.standards_entries.find({"type": "cqc", "is_active": True}).sort("reference", 1):
        cqc_stds.append({"ref": s["reference"], "name": s.get("name", "")})
    async for s in db.standards_entries.find({"type": "care_cert", "is_active": True}).sort("reference", 1):
        cc_stds.append({"ref": s["reference"], "name": s.get("name", "")})
        subs = s.get("sub_outcomes", [])
        if subs:
            cc_sub_outcomes[s["reference"]] = [so["ref"] for so in subs]
    # Re-sort numerically (DB sort is alphabetical: Standard 10 < Standard 2)
    cqc_stds.sort(key=lambda x: _ref_nums(x["ref"]))
    cc_stds.sort(key=lambda x: _ref_nums(x["ref"]))

    # ── Load all signed-off meetings ────────────────────────────────────────
    all_items = []
    async for meeting in db.meetings.find(
        {"status": {"$in": ["signed_off", "shared"]}, "analysis_id": {"$exists": True}}
    ).sort("date", -1):
        adoc = await db.analyses.find_one({"_id": ObjectId(meeting["analysis_id"])})
        if adoc:
            all_items.append({"meeting": meeting, "analysis": adoc})

    # ── Evidence maps ───────────────────────────────────────────────────────
    # CQC: staff_id → standard_ref → count data
    def empty_cqc(): return {"likely": 0, "review": 0, "total": 0, "last_date": ""}
    # Care Cert: staff_id → standard_ref → {count data + set of covered sub-outcome refs}
    def empty_cc(): return {"likely": 0, "review": 0, "total": 0, "last_date": "", "covered_refs": set()}

    cqc_ev = {s["id"]: {} for s in staff}
    cc_ev = {s["id"]: {} for s in staff}
    cust_ev = {s["id"]: {} for s in staff}
    cust_names: dict = {}  # ref → display name

    all_risks: list = []
    all_outstanding: list = []

    for item in all_items:
        mtg, ana = item["meeting"], item["analysis"]
        date = mtg.get("date", "")

        for attendee in mtg.get("attendees", []):
            uid = attendee.get("user_id", "")
            if uid not in staff_ids:
                continue

            for m in ana.get("cqc_mappings", []):
                ref = m.get("regulation_ref", "")
                if not ref:
                    continue
                if ref not in cqc_ev[uid]:
                    cqc_ev[uid][ref] = empty_cqc()
                c = cqc_ev[uid][ref]
                c["total"] += 1
                if m.get("confidence") == "likely_evidence":
                    c["likely"] += 1
                elif m.get("confidence") == "needs_review":
                    c["review"] += 1
                if date > c["last_date"]:
                    c["last_date"] = date

            for m in ana.get("care_cert_mappings", []):
                std_ref = m.get("standard_ref", "")
                outcome_ref = m.get("outcome_ref", "")
                if not std_ref:
                    continue
                if std_ref not in cc_ev[uid]:
                    cc_ev[uid][std_ref] = empty_cc()
                c = cc_ev[uid][std_ref]
                c["total"] += 1
                if m.get("confidence") == "likely_evidence":
                    c["likely"] += 1
                elif m.get("confidence") == "needs_review":
                    c["review"] += 1
                if date > c["last_date"]:
                    c["last_date"] = date
                if outcome_ref:
                    c["covered_refs"].add(outcome_ref)

            for m in ana.get("custom_mappings", []):
                ref = m.get("criterion_ref", "") or m.get("document_name", "")
                if not ref:
                    continue
                cust_names.setdefault(ref, m.get("criterion_name", ref))
                if ref not in cust_ev[uid]:
                    cust_ev[uid][ref] = empty_cqc()
                c = cust_ev[uid][ref]
                c["total"] += 1
                if m.get("confidence") == "likely_evidence":
                    c["likely"] += 1
                elif m.get("confidence") == "needs_review":
                    c["review"] += 1
                if date > c["last_date"]:
                    c["last_date"] = date

        for risk in ana.get("risks", []):
            text = risk if isinstance(risk, str) else (risk.get("text", "") if isinstance(risk, dict) else "")
            if text.strip():
                all_risks.append(text.strip())

        for action in ana.get("actions", []):
            if isinstance(action, dict) and not action.get("completed", False):
                text = action.get("text", "").strip()
                if text:
                    all_outstanding.append(text)

    # ── Build matrix helpers ────────────────────────────────────────────────
    def build_cqc_matrix(stds, ev_map):
        """CQC matrix: evidenced if any likely evidence; needs_review if any review."""
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
        """Care Cert matrix: green ONLY when ALL sub-outcomes have evidence; amber when partial."""
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
                    # No sub-outcomes defined — fall back to old behaviour
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
                    "status": status,
                    "total": ev.get("total", 0),
                    "likely": ev.get("likely", 0),
                    "review": ev.get("review", 0),
                    "last_date": ev.get("last_date", ""),
                    "covered_sub": covered_count,
                    "total_sub": total_subs,
                    "pct": pct,
                }
            rows.append({"staff_id": s["id"], "staff_name": s["name"], "cells": cells})
        return {"standards": stds, "rows": rows}

    def build_custom_matrix(stds, ev_map):
        """Custom standards matrix: same as CQC (no sub-outcomes)."""
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

    # ── Coverage gaps ───────────────────────────────────────────────────────
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
            fully_covered = sum(
                1 for s in staff
                if len(cc_ev[s["id"]].get(ref, {}).get("covered_refs", set()) & all_subs) == total_subs
            )
            # Unique sub-outcomes that have evidence from at least one team member
            all_covered_refs = set()
            for s in staff:
                all_covered_refs |= cc_ev[s["id"]].get(ref, {}).get("covered_refs", set())
            union_covered = len(all_covered_refs & all_subs)
        else:
            fully_covered = sum(1 for s in staff if cc_ev[s["id"]].get(ref, {}).get("total", 0) > 0)
            union_covered = 0
        gaps.append({
            "ref": ref, "name": std["name"], "type": "care_cert",
            "covered": fully_covered, "total": len(staff),
            "covered_sub": union_covered, "total_sub": total_subs,
        })
    for std in cust_stds:
        ref = std["ref"]
        covered = sum(1 for s in staff if cust_ev[s["id"]].get(ref, {}).get("total", 0) > 0)
        gaps.append({"ref": ref, "name": std["name"], "type": "custom", "covered": covered, "total": len(staff)})
    # Sort gaps numerically by reference within each type
    _type_order = {"cqc": 0, "care_cert": 1, "custom": 2}
    gaps.sort(key=lambda x: (_type_order.get(x["type"], 9), _ref_nums(x["ref"])))

    # ── Aggregate risks / actions ───────────────────────────────────────────
    def agg(items, top=10):
        counts: dict = {}
        for text in items:
            key = text[:60].lower()
            if key not in counts:
                counts[key] = {"text": text, "count": 0}
            counts[key]["count"] += 1
        return sorted(counts.values(), key=lambda x: -x["count"])[:top]

    return {
        "staff_count": len(staff),
        "meeting_count": len(all_items),
        "matrix": {
            "cqc": build_cqc_matrix(cqc_stds, cqc_ev),
            "care_cert": build_cc_matrix(cc_stds, cc_ev),
            "custom": build_custom_matrix(cust_stds, cust_ev),
        },
        "themes": {
            "coverage_gaps": gaps,
            "common_risks": agg(all_risks),
            "outstanding_actions": agg(all_outstanding),
        },
    }


@router.get("/meetings-brief")
async def list_meetings_brief(db=Depends(get_db), current_user=Depends(get_current_user)):
    """Return lightweight meeting list for the export filter UI."""
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    meetings = []
    async for doc in db.meetings.find(
        {"status": {"$in": ["signed_off", "shared"]}},
        {"title": 1, "date": 1, "attendees": 1, "status": 1}
    ).sort("date", -1):
        meetings.append({
            "id": str(doc["_id"]),
            "title": doc.get("title", ""),
            "date": doc.get("date", ""),
            "attendees": [{"user_id": a.get("user_id"), "name": a.get("name")} for a in doc.get("attendees", [])],
        })
    return meetings


@router.post("/export-evidence")
async def export_evidence(data: dict, db=Depends(get_db), current_user=Depends(get_current_user)):
    """Bulk evidence export. Accepts filters: format, staff_ids, date_from, date_to, meeting_ids."""
    from fastapi.responses import Response as _Response
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    fmt = data.get("format", "csv")  # "pdf" | "csv"
    staff_ids = data.get("staff_ids") or []
    date_from = data.get("date_from")
    date_to = data.get("date_to")
    meeting_ids = data.get("meeting_ids") or []

    # Build query
    query: dict = {"status": {"$in": ["signed_off", "shared"]}, "analysis_id": {"$exists": True}}

    if meeting_ids:
        query["_id"] = {"$in": [ObjectId(mid) for mid in meeting_ids if mid]}
    else:
        if staff_ids:
            query["attendees.user_id"] = {"$in": staff_ids}
        if date_from or date_to:
            date_filter: dict = {}
            if date_from:
                date_filter["$gte"] = date_from
            if date_to:
                date_filter["$lte"] = date_to
            if date_filter:
                query["date"] = date_filter

    rows = []  # for CSV; (meeting, analysis) tuples for PDF
    mtg_analyses = []
    async for meeting in db.meetings.find(query).sort("date", -1):
        if not meeting.get("analysis_id"):
            continue
        adoc = await db.analyses.find_one({"_id": ObjectId(meeting["analysis_id"])})
        if not adoc:
            continue
        mtg_analyses.append({"meeting": meeting, "analysis": adoc})

        for attendee in meeting.get("attendees", []):
            staff_name = attendee.get("name", "Unknown")
            for m in adoc.get("cqc_mappings", []):
                rows.append([staff_name, meeting.get("title", ""), meeting.get("date", "")[:10],
                             "CQC", m.get("regulation_ref", ""), m.get("regulation_name", ""),
                             m.get("confidence", ""), m.get("status", "pending"),
                             (m.get("edited_evidence_summary") or m.get("evidence_summary", ""))[:200]])
            for m in adoc.get("care_cert_mappings", []):
                rows.append([staff_name, meeting.get("title", ""), meeting.get("date", "")[:10],
                             "Care Cert", m.get("standard_ref", ""), m.get("standard_name", ""),
                             m.get("confidence", ""), m.get("status", "pending"),
                             (m.get("edited_evidence_summary") or m.get("evidence_summary", ""))[:200]])
            for m in adoc.get("custom_mappings", []):
                rows.append([staff_name, meeting.get("title", ""), meeting.get("date", "")[:10],
                             "Organisational", m.get("criterion_ref", ""), m.get("criterion_name", ""),
                             m.get("confidence", ""), m.get("status", "pending"),
                             (m.get("edited_evidence_summary") or m.get("evidence_summary", ""))[:200]])

    if fmt == "csv":
        import csv
        import io
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Staff Member", "Meeting", "Date", "Evidence Type", "Reference", "Standard Name",
                         "Confidence", "Status", "Evidence Summary"])
        writer.writerows(rows)
        csv_bytes = buf.getvalue().encode("utf-8-sig")  # BOM for Excel
        return _Response(
            content=csv_bytes,
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="evidence_export.csv"'},
        )
    else:
        # PDF — generate multi-meeting report
        pdf_bytes = _generate_export_pdf(mtg_analyses)
        return _Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="evidence_export.pdf"'},
        )


def _generate_export_pdf(mtg_analyses: list) -> bytes:
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, PageBreak
    from datetime import datetime as _dt

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    NAVY = colors.HexColor("#1E3A8A")
    MID_GRAY = colors.HexColor("#6B7280")
    PURPLE_BG = colors.HexColor("#EDE9FE")
    BLUE_BG = colors.HexColor("#EFF6FF")
    TEAL_BG = colors.HexColor("#F0FDF4")

    title_s = ParagraphStyle("T", fontName="Helvetica-Bold", fontSize=16, textColor=NAVY, spaceAfter=2)
    h2_s = ParagraphStyle("H2", fontName="Helvetica-Bold", fontSize=11, textColor=NAVY, spaceAfter=3, spaceBefore=8)
    small_s = ParagraphStyle("S", fontName="Helvetica", fontSize=8, textColor=MID_GRAY, spaceAfter=1, leading=11)

    story = []
    story.append(Paragraph("Supervision 2.0 — Evidence Export", small_s))
    story.append(Paragraph(f"Generated {_dt.now().strftime('%d %b %Y %H:%M')} UTC", small_s))
    story.append(Paragraph(f"{len(mtg_analyses)} meeting(s) included", small_s))
    story.append(HRFlowable(width="100%", thickness=2, color=NAVY, spaceAfter=6))

    def section_hdr(title, bg=NAVY):
        t = Table([[Paragraph(f'<font color="white"><b>{title}</b></font>',
                    ParagraphStyle("SH", fontName="Helvetica-Bold", fontSize=10, textColor=colors.white))]],
                  colWidths=[170*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ]))
        return t

    for i, item in enumerate(mtg_analyses):
        mtg = item["meeting"]
        ana = item["analysis"]
        if i > 0:
            story.append(PageBreak())

        story.append(Paragraph(mtg.get("title", "Meeting"), title_s))
        attendees = ", ".join(a.get("name", "") for a in mtg.get("attendees", []))
        story.append(Paragraph(f'Date: {mtg.get("date", "—")} | Attendees: {attendees} | Manager: {mtg.get("sign_off_manager_name", "—")}', small_s))  # noqa: E501
        story.append(Spacer(1, 3*mm))

        for maps, label, bg, ref_key, name_key in [
            (ana.get("cqc_mappings", []), "CQC Regulatory Evidence", PURPLE_BG, "regulation_ref", "regulation_name"),
            (ana.get("care_cert_mappings", []), "Care Certificate Evidence", BLUE_BG, "standard_ref", "standard_name"),
            (ana.get("custom_mappings", []), "Organisational Standards Evidence", TEAL_BG, "criterion_ref", "criterion_name"),  # noqa: E501
        ]:
            if not maps:
                continue
            story.append(Paragraph(label, h2_s))
            hdr_row = [["Reference", "Standard", "Confidence", "Status", "Evidence Summary"]]
            data_rows = [[
                m.get(ref_key, ""),
                m.get(name_key, ""),
                m.get("confidence", "").replace("_", " ").title(),
                m.get("status", "pending").title(),
                (m.get("edited_evidence_summary") or m.get("evidence_summary", ""))[:120],
            ] for m in maps]
            tbl = Table(hdr_row + data_rows, colWidths=[22*mm, 40*mm, 28*mm, 18*mm, 62*mm])
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, bg]),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("WORDWRAP", (0, 0), (-1, -1), True),
            ]))
            story.append(tbl)
            story.append(Spacer(1, 2*mm))

    story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MID_GRAY))
    story.append(Paragraph("Supervision 2.0 — Confidential evidence export.", small_s))
    doc.build(story)
    return buf.getvalue()


@router.get("/stats")
async def get_stats(db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    total_meetings = await db.meetings.count_documents({})
    signed_off = await db.meetings.count_documents({"status": "signed_off"})
    in_review = await db.meetings.count_documents({"status": {"$in": ["in_review", "reviewed"]}})
    total_users = await db.users.count_documents({})
    total_standards = await db.standards_entries.count_documents({"is_active": True})
    return {
        "total_meetings": total_meetings,
        "signed_off": signed_off,
        "in_review": in_review,
        "total_users": total_users,
        "total_standards": total_standards,
    }
