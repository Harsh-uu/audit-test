"""
Supervision document upload router.
Allows managers/admins to upload a previous supervision document (PDF/DOCX),
extract its text, run AI evidence mapping, and link it to a specific staff member.
"""
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, BackgroundTasks
from datetime import datetime, timezone
from pydantic import BaseModel
from typing import Optional
import io
import json
import uuid
import logging

from deps import get_current_user
import database

router = APIRouter()
logger = logging.getLogger(__name__)

UPLOAD_MAX_CHARS = 20_000
_JSONB_FIELDS = ("cqc_mappings", "care_cert_mappings", "custom_mappings")


class UpdateUploadEvidenceRequest(BaseModel):
    status: Optional[str] = None                    # accepted | rejected | needs_followup | pending
    edited_evidence_summary: Optional[str] = None
    notes: Optional[str] = None


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

    upload_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    async with database.with_org(org_id) as conn:
        await conn.execute(
            """INSERT INTO supervision_uploads
               (id, org_id, uploader_id, uploader_name, staff_id, staff_name,
                filename, label, doc_type, meeting_date, file_ext, size_bytes,
                status, cqc_mappings, care_cert_mappings, custom_mappings, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb,$15::jsonb,$16::jsonb,$17)""",
            upload_id, org_id,
            current_user["id"], current_user.get("name", ""),
            staff_id, staff["name"],
            file.filename, (label.strip() or file.filename),
            (doc_type.strip() or "other"), (meeting_date or now[:10]),
            file_ext, len(file_data),
            "processing", "[]", "[]", "[]", now,
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
        if staff_id:
            rows = await conn.fetch(
                "SELECT id,org_id,uploader_id,uploader_name,staff_id,staff_name,filename,label,"
                "doc_type,meeting_date,file_ext,size_bytes,status,cqc_mappings,care_cert_mappings,"
                "custom_mappings,error,processed_at,created_at "
                "FROM supervision_uploads WHERE org_id=$1 AND staff_id=$2 ORDER BY created_at DESC",
                org_id, staff_id,
            )
        else:
            rows = await conn.fetch(
                "SELECT id,org_id,uploader_id,uploader_name,staff_id,staff_name,filename,label,"
                "doc_type,meeting_date,file_ext,size_bytes,status,cqc_mappings,care_cert_mappings,"
                "custom_mappings,error,processed_at,created_at "
                "FROM supervision_uploads WHERE org_id=$1 ORDER BY created_at DESC",
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
            "SELECT * FROM supervision_uploads WHERE id=$1 AND org_id=$2",
            upload_id, org_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return _upload_dict(row)


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
            "SELECT * FROM supervision_uploads WHERE id=$1 AND org_id=$2", upload_id, org_id
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
        result = await conn.execute(
            "DELETE FROM supervision_uploads WHERE id=$1 AND org_id=$2",
            upload_id, org_id,
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Not found")
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
                    "SELECT * FROM standards_entries WHERE type='ciw' AND is_active=TRUE AND jurisdiction='wales'",
                )
                care_cert_rows = await conn.fetch(
                    "SELECT * FROM standards_entries WHERE type IN ('awif','scw') AND is_active=TRUE AND jurisdiction='wales' ORDER BY type, reference",
                )
            elif org_jurisdiction == "scotland":
                cqc_rows = await conn.fetch(
                    "SELECT * FROM standards_entries WHERE type='ci' AND is_active=TRUE AND jurisdiction='scotland' ORDER BY reference",
                )
                care_cert_rows = await conn.fetch(
                    "SELECT * FROM standards_entries WHERE type='sssc' AND is_active=TRUE AND jurisdiction='scotland' ORDER BY reference",
                )
            elif org_jurisdiction == "northern_ireland":
                rqia_type = "rqia_dom" if org_service_type == "domiciliary" else "rqia_res"
                cqc_rows = await conn.fetch(
                    "SELECT * FROM standards_entries WHERE type=$1 AND is_active=TRUE AND jurisdiction='northern_ireland' ORDER BY reference",
                    rqia_type,
                )
                care_cert_rows = await conn.fetch(
                    "SELECT * FROM standards_entries WHERE type IN ('niscc_code','niscc_induction') AND is_active=TRUE AND jurisdiction='northern_ireland' ORDER BY type, reference",
                )
            else:
                cqc_rows = await conn.fetch(
                    "SELECT * FROM standards_entries WHERE type='cqc' AND is_active=TRUE ORDER BY reference ASC",
                )
                care_cert_rows = await conn.fetch(
                    "SELECT * FROM standards_entries WHERE type='care_cert' AND is_active=TRUE ORDER BY reference ASC",
                )
        async with database.with_org(org_id) as conn:
            custom_rows = await conn.fetch(
                "SELECT * FROM standards_documents WHERE org_id=$1 AND is_active=TRUE AND parse_status='parsed'",
                org_id,
            )

        cqc_stds = [dict(r) for r in cqc_rows]
        care_cert_stds = [dict(r) for r in care_cert_rows]
        custom_stds = [dict(r) for r in custom_rows]

        # Build effective jurisdiction for NI prompt routing
        effective_jurisdiction = org_jurisdiction
        if org_jurisdiction == "northern_ireland":
            effective_jurisdiction = f"northern_ireland_{org_service_type or 'domiciliary'}"

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
                    "failed", str(exc), upload_id,
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
