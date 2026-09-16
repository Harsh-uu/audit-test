"""
Supervision document upload router.
Allows managers/admins to upload a previous supervision document (PDF/DOCX),
extract its text, run AI evidence mapping, and link it to a specific staff member.
"""
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, BackgroundTasks
from datetime import datetime, timezone
from pydantic import BaseModel
from typing import Optional, Literal
import io
import json
import uuid
import logging

from deps import get_current_user
from utils.supabase_storage import put_document, get_document, delete_document
import database

router = APIRouter()
logger = logging.getLogger(__name__)

UPLOAD_MAX_CHARS = 20_000
_JSONB_FIELDS = ("cqc_mappings", "care_cert_mappings", "custom_mappings")


def _parse_std(r) -> dict:
    """Normalize standards_entries JSONB columns before passing to ai.py."""
    s = dict(r) if not isinstance(r, dict) else r
    for f in ("sub_outcomes", "key_questions", "keywords"):
        v = s.get(f)
        if isinstance(v, str):
            try: s[f] = json.loads(v)
            except Exception: s[f] = []
        elif v is None:
            s[f] = []
    return s


class UpdateUploadEvidenceRequest(BaseModel):
    status: Optional[str] = None                    # accepted | rejected | needs_followup | pending
    edited_evidence_summary: Optional[str] = None
    notes: Optional[str] = None


# Legacy confidence values pre-date the likely/possible rename — treat them as
# "possible" so bulk-accept still works on older document scans.
_CONFIDENCE_ALIASES = {
    "likely_evidence": {"likely_evidence"},
    "possible_evidence": {"possible_evidence", "needs_review", "not_enough_evidence"},
}


class BulkUploadEvidenceActionRequest(BaseModel):
    confidence: Literal["likely_evidence", "possible_evidence"]
    status: Literal["accepted", "rejected", "needs_followup"] = "accepted"


def _upload_dict(row) -> dict:
    """Convert asyncpg Record → dict, ensuring JSONB mapping fields are lists."""
    d = dict(row)
    for field in _JSONB_FIELDS:
        val = d.get(field)
        if isinstance(val, str):
            try:
                d[field] = json.loads(val)
            except Exception:
                d[field] = []
        elif val is None:
            d[field] = []
    return d


@router.post("/")
async def upload_supervision_doc(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    staff_id: str = Form(...),
    label: str = Form(""),
    meeting_date: str = Form(""),
    doc_type: str = Form(""),
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Admin/Manager only")

    org_id = current_user.get("org_id")

    async with database.with_org(org_id) as conn:
        staff = await conn.fetchrow(
            "SELECT id, name FROM users WHERE id = $1 AND org_id = $2",
            staff_id, org_id,
        )
    if not staff:
        raise HTTPException(status_code=404, detail="Staff member not found in your organisation")

    allowed_ext = {"pdf", "docx"}
    file_ext = (
        file.filename.rsplit(".", 1)[-1].lower()
        if file.filename and "." in file.filename
        else ""
    )
    if file_ext not in allowed_ext:
        raise HTTPException(status_code=400, detail="Only PDF and DOCX files are supported")

    file_data = await file.read()
    if len(file_data) == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(file_data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 20 MB)")

    # Magic-byte validation — consistent with standards/logo upload endpoints
    from utils.file_security import validate_upload, guard_zip_bomb
    try:
        canonical_mime = validate_upload(file_data, file_ext)
        if file_ext == "docx":
            guard_zip_bomb(file_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    storage_path = f"supervision/uploads/{uuid.uuid4()}.{file_ext}"
    try:
        result = await put_document(storage_path, file_data, canonical_mime)
        actual_path = result.get("path", storage_path)
    except Exception as e:
        logger.error(f"Supervision upload storage failed: {e}")
        actual_path = None

    upload_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    async with database.with_org(org_id) as conn:
        await conn.execute(
            """INSERT INTO supervision_uploads
               (id, org_id, uploader_id, uploader_name, staff_id, staff_name,
                filename, label, doc_type, meeting_date, file_ext, size_bytes,
                status, cqc_mappings, care_cert_mappings, custom_mappings, created_at, storage_path)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb,$15::jsonb,$16::jsonb,$17,$18)""",
            upload_id, org_id,
            current_user["id"], current_user.get("name", ""),
            staff_id, staff["name"],
            file.filename, (label.strip() or file.filename),
            (doc_type.strip() or "other"), (meeting_date or now[:10]),
            file_ext, len(file_data),
            "processing", "[]", "[]", "[]", now, actual_path,
        )

    background_tasks.add_task(process_upload_background, upload_id, file_data, file.filename, org_id)

    return {
        "id": upload_id, "org_id": org_id,
        "uploader_id": current_user["id"], "uploader_name": current_user.get("name", ""),
        "staff_id": staff_id, "staff_name": staff["name"],
        "filename": file.filename, "label": label.strip() or file.filename,
        "doc_type": doc_type.strip() or "other", "meeting_date": meeting_date or now[:10],
        "file_ext": file_ext, "size_bytes": len(file_data),
        "status": "processing",
        "cqc_mappings": [], "care_cert_mappings": [], "custom_mappings": [],
        "created_at": now,
    }


@router.get("/")
async def list_uploads(
    staff_id: str = None,
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Admin/Manager only")
    org_id = current_user.get("org_id")
    async with database.with_org(org_id) as conn:
        # PERF-004: cap to the 200 most recent uploads — this list has no
        # pagination UI, so an unbounded org-lifetime history would only ever
        # get slower to load as more uploads accumulate.
        if staff_id:
            rows = await conn.fetch(
                "SELECT id,org_id,uploader_id,uploader_name,staff_id,staff_name,filename,label,"
                "doc_type,meeting_date,file_ext,size_bytes,status,cqc_mappings,care_cert_mappings,"
                "custom_mappings,error,processed_at,created_at "
                "FROM supervision_uploads WHERE org_id=$1 AND staff_id=$2 ORDER BY created_at DESC LIMIT 200",
                org_id, staff_id,
            )
        else:
            rows = await conn.fetch(
                "SELECT id,org_id,uploader_id,uploader_name,staff_id,staff_name,filename,label,"
                "doc_type,meeting_date,file_ext,size_bytes,status,cqc_mappings,care_cert_mappings,"
                "custom_mappings,error,processed_at,created_at "
                "FROM supervision_uploads WHERE org_id=$1 ORDER BY created_at DESC LIMIT 200",
                org_id,
            )
    return [_upload_dict(r) for r in rows]


@router.get("/{upload_id}")
async def get_upload(
    upload_id: str,
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Admin/Manager only")
    org_id = current_user.get("org_id")
    async with database.with_org(org_id) as conn:
        row = await conn.fetchrow(
            "SELECT id,org_id,uploader_id,uploader_name,staff_id,staff_name,filename,label,"
            "doc_type,meeting_date,file_ext,size_bytes,status,cqc_mappings,care_cert_mappings,"
            "custom_mappings,error,processed_at,created_at,storage_path "
            "FROM supervision_uploads WHERE id=$1 AND org_id=$2",
            upload_id, org_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return _upload_dict(row)


@router.get("/{upload_id}/download")
async def download_upload(
    upload_id: str,
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Admin/Manager only")
    org_id = current_user.get("org_id")
    async with database.with_org(org_id) as conn:
        row = await conn.fetchrow(
            "SELECT filename, storage_path FROM supervision_uploads WHERE id=$1 AND org_id=$2",
            upload_id, org_id,
        )
    if not row or not row["storage_path"]:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        file_data, content_type = await get_document(row["storage_path"])
    except Exception as e:
        logger.error(f"Supervision upload download failed for {upload_id}: {e}")
        raise HTTPException(status_code=404, detail="File not found in storage")
    from fastapi.responses import Response as _Response
    filename = row["filename"] or "document"
    return _Response(
        content=file_data,
        media_type=content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{upload_id}/evidence/bulk-action")
async def bulk_update_upload_evidence(
    upload_id: str,
    data: BulkUploadEvidenceActionRequest,
    current_user=Depends(get_current_user),
):
    """
    Accept/reject/flag every pending item of one confidence tier in a single
    atomic update (SELECT ... FOR UPDATE + one write) — firing N separate PUT
    calls in parallel races on the same JSONB column and silently drops all
    but the last writer, which is what made "Accept all" look like a no-op.
    """
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Admin/Manager only")
    org_id = current_user.get("org_id")
    confidence_set = _CONFIDENCE_ALIASES.get(data.confidence, {data.confidence})

    async with database.with_org(org_id) as conn:
        row = await conn.fetchrow(
            "SELECT cqc_mappings, care_cert_mappings, custom_mappings FROM supervision_uploads WHERE id=$1 AND org_id=$2 FOR UPDATE",
            upload_id, org_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Not found")

        upload = _upload_dict(row)
        update_cols = {}
        changed_count = 0
        for field in _JSONB_FIELDS:
            mappings = list(upload.get(field) or [])
            changed = False
            for i, m in enumerate(mappings):
                if m.get("confidence") in confidence_set and (m.get("status") or "pending") == "pending":
                    mappings[i]["status"] = data.status
                    changed = True
                    changed_count += 1
            if changed:
                update_cols[field] = mappings

        if update_cols:
            set_parts = []
            values = []
            idx = 1
            for field, val in update_cols.items():
                set_parts.append(f"{field}=${idx}")
                values.append(val)
                idx += 1
            values.append(upload_id)
            await conn.execute(f"UPDATE supervision_uploads SET {', '.join(set_parts)} WHERE id=${idx}", *values)

    return {"message": f"{changed_count} item{'s' if changed_count != 1 else ''} updated", "changed_count": changed_count}


@router.put("/{upload_id}/evidence/{evidence_id}")
async def update_upload_evidence(
    upload_id: str,
    evidence_id: str,
    data: UpdateUploadEvidenceRequest,
    current_user=Depends(get_current_user),
):
    """Accept, reject, flag or edit wording on a mapped evidence item in an uploaded document."""
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Admin/Manager only")
    org_id = current_user.get("org_id")
    async with database.with_org(org_id) as conn:
        row = await conn.fetchrow(
            "SELECT id, cqc_mappings, care_cert_mappings, custom_mappings FROM supervision_uploads WHERE id=$1 AND org_id=$2",
            upload_id, org_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Not found")

    upload = _upload_dict(row)
    updated_field = None
    updated_list = None

    for field in _JSONB_FIELDS:
        mappings = list(upload.get(field) or [])
        for i, m in enumerate(mappings):
            if m.get("id") == evidence_id:
                if data.status is not None:
                    mappings[i]["status"] = data.status
                if data.edited_evidence_summary is not None:
                    mappings[i]["edited_evidence_summary"] = data.edited_evidence_summary
                if data.notes is not None:
                    mappings[i]["notes"] = data.notes
                updated_field = field
                updated_list = mappings
                break
        if updated_field:
            break

    if not updated_field:
        raise HTTPException(status_code=404, detail="Evidence item not found")

    async with database.with_org(org_id) as conn:
        await conn.execute(
            f"UPDATE supervision_uploads SET {updated_field}=$1 WHERE id=$2",
            updated_list, upload_id,
        )
    return {"message": "Evidence updated"}


@router.delete("/{upload_id}")
async def delete_upload(
    upload_id: str,
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Admin/Manager only")
    org_id = current_user.get("org_id")
    async with database.with_org(org_id) as conn:
        row = await conn.fetchrow(
            "SELECT storage_path FROM supervision_uploads WHERE id=$1 AND org_id=$2",
            upload_id, org_id,
        )
        result = await conn.execute(
            "DELETE FROM supervision_uploads WHERE id=$1 AND org_id=$2",
            upload_id, org_id,
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Not found")
    if row and row["storage_path"]:
        try:
            await delete_document(row["storage_path"])
        except Exception as e:
            logger.error(f"Failed to delete supervision upload file from storage for {upload_id}: path={row['storage_path']} error={e}")
    return {"message": "Deleted"}


async def process_upload_background(upload_id: str, file_data: bytes, filename: str, org_id: str):
    """Extract text and run AI evidence mapping in the background."""
    try:
        text = _extract_text(file_data, filename)
        if not text.strip():
            async with database.with_org(org_id) as conn:
                await conn.execute(
                    "UPDATE supervision_uploads SET status=$1, error=$2 WHERE id=$3",
                    "failed", "No text could be extracted from this document", upload_id,
                )
            return

        # Phase 1: text extracted — make document available in context sources immediately
        async with database.with_org(org_id) as conn:
            await conn.execute(
                "UPDATE supervision_uploads SET full_text=$1, status=$2 WHERE id=$3",
                text, "text_ready", upload_id,
            )

        # Phase 2: run AI evidence mapping
        async with database.with_admin() as conn:
            org_row = await conn.fetchrow(
                "SELECT jurisdiction, service_type FROM organisations WHERE id=$1", org_id
            )
            org_jurisdiction = (org_row["jurisdiction"] if org_row else None) or "england"
            org_service_type = (org_row["service_type"] if org_row else None)

            if org_jurisdiction == "wales":
                cqc_rows = await conn.fetch(
                    "SELECT reference, name, description, key_questions, sub_outcomes FROM standards_entries WHERE type='ciw' AND is_active=TRUE AND jurisdiction='wales'",
                )
                care_cert_rows = await conn.fetch(
                    "SELECT reference, name, description, key_questions, sub_outcomes FROM standards_entries WHERE type IN ('awif','scw') AND is_active=TRUE AND jurisdiction='wales' ORDER BY type, reference",
                )
            elif org_jurisdiction == "scotland":
                cqc_rows = await conn.fetch(
                    "SELECT reference, name, description, key_questions, sub_outcomes FROM standards_entries WHERE type='ci' AND is_active=TRUE AND jurisdiction='scotland' ORDER BY reference",
                )
                care_cert_rows = await conn.fetch(
                    "SELECT reference, name, description, key_questions, sub_outcomes FROM standards_entries WHERE type='sssc' AND is_active=TRUE AND jurisdiction='scotland' ORDER BY reference",
                )
            elif org_jurisdiction == "northern_ireland":
                rqia_type = "rqia_dom" if org_service_type == "domiciliary" else "rqia_res"
                cqc_rows = await conn.fetch(
                    "SELECT reference, name, description, key_questions, sub_outcomes FROM standards_entries WHERE type=$1 AND is_active=TRUE AND jurisdiction='northern_ireland' ORDER BY reference",
                    rqia_type,
                )
                care_cert_rows = await conn.fetch(
                    "SELECT reference, name, description, key_questions, sub_outcomes FROM standards_entries WHERE type IN ('niscc_code','niscc_induction') AND is_active=TRUE AND jurisdiction='northern_ireland' ORDER BY type, reference",
                )
            elif org_jurisdiction == "ofsted":
                ofsted_reg_type = {"school": "eif", "early_years": "eyfs_safeguarding", "childrens_home": "chqs"}.get(org_service_type, "eif")
                ofsted_cert_type = {"school": "teachers_standards", "early_years": "eyfs_learning", "childrens_home": "l3_residential"}.get(org_service_type, "teachers_standards")
                cqc_rows = await conn.fetch(
                    "SELECT reference, name, description, key_questions, sub_outcomes FROM standards_entries WHERE type=$1 AND is_active=TRUE AND jurisdiction='ofsted' ORDER BY reference",
                    ofsted_reg_type,
                )
                care_cert_rows = await conn.fetch(
                    "SELECT reference, name, description, key_questions, sub_outcomes FROM standards_entries WHERE type=$1 AND is_active=TRUE AND jurisdiction='ofsted' ORDER BY reference",
                    ofsted_cert_type,
                )
            else:
                cqc_rows = await conn.fetch(
                    "SELECT reference, name, description, key_questions, sub_outcomes FROM standards_entries WHERE type='cqc' AND is_active=TRUE ORDER BY reference ASC",
                )
                care_cert_rows = await conn.fetch(
                    "SELECT reference, name, description, key_questions, sub_outcomes FROM standards_entries WHERE type='care_cert' AND is_active=TRUE ORDER BY reference ASC",
                )
        async with database.with_org(org_id) as conn:
            custom_rows = await conn.fetch(
                "SELECT id, label, filename, extracted_criteria FROM standards_documents WHERE org_id=$1 AND is_active=TRUE AND parse_status='parsed'",
                org_id,
            )

        cqc_stds = [_parse_std(dict(r)) for r in cqc_rows]
        care_cert_stds = [_parse_std(dict(r)) for r in care_cert_rows]
        custom_stds = [dict(r) for r in custom_rows]

        # Build effective jurisdiction for NI/Ofsted prompt routing
        effective_jurisdiction = org_jurisdiction
        if org_jurisdiction == "northern_ireland":
            effective_jurisdiction = f"northern_ireland_{org_service_type or 'domiciliary'}"
        elif org_jurisdiction == "ofsted":
            effective_jurisdiction = f"ofsted_{org_service_type or 'school'}"

        from utils.ai import analyze_doc_for_evidence
        result = await analyze_doc_for_evidence(text, cqc_stds, care_cert_stds, custom_stds, jurisdiction=effective_jurisdiction)

        async with database.with_org(org_id) as conn:
            await conn.execute(
                """UPDATE supervision_uploads
                   SET status=$1, cqc_mappings=$2::jsonb, care_cert_mappings=$3::jsonb,
                       custom_mappings=$4::jsonb, processed_at=$5
                   WHERE id=$6""",
                "done",
                result.get("cqc_mappings", []),
                result.get("care_cert_mappings", []),
                result.get("custom_mappings", []),
                datetime.now(timezone.utc).isoformat(),
                upload_id,
            )
        logger.info(
            "Upload %s processed: %d CQC, %d Care Cert, %d custom",
            upload_id,
            len(result.get("cqc_mappings", [])),
            len(result.get("care_cert_mappings", [])),
            len(result.get("custom_mappings", [])),
        )
    except Exception as exc:
        logger.error("Upload processing failed for %s: %s", upload_id, exc, exc_info=True)
        try:
            async with database.with_org(org_id) as conn:
                await conn.execute(
                    "UPDATE supervision_uploads SET status=$1, error=$2 WHERE id=$3",
                    "failed", "Processing failed — please retry or contact support.", upload_id,
                )
        except Exception:
            pass


def _extract_text(file_data: bytes, filename: str) -> str:
    """Extract plain text from PDF or DOCX with a higher char limit than the standards parser."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    try:
        if ext == "pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(file_data))
            parts = []
            for page in reader.pages:
                parts.append(page.extract_text() or "")
                if sum(len(p) for p in parts) >= UPLOAD_MAX_CHARS:
                    break
            return "\n".join(parts)[:UPLOAD_MAX_CHARS]
        elif ext == "docx":
            from docx import Document as DocxDocument
            doc = DocxDocument(io.BytesIO(file_data))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            return text[:UPLOAD_MAX_CHARS]
        else:
            return file_data.decode("utf-8", errors="replace")[:UPLOAD_MAX_CHARS]
    except Exception as exc:
        logger.warning("Text extraction failed for %s: %s", filename, exc)
        return ""
