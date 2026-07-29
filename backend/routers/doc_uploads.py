"""
Supervision document upload router.
Allows managers/admins to upload a previous supervision document (PDF/DOCX),
extract its text, run AI evidence mapping, and link it to a specific staff member.
"""
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, BackgroundTasks
from bson import ObjectId
from datetime import datetime, timezone
import io
import logging

from deps import get_db, get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)

UPLOAD_MAX_CHARS = 20_000  # Higher than the standards parser (12 000) for full supervision docs


def doc_to_dict(doc):
    if doc is None:
        return None
    doc = dict(doc)
    doc["id"] = str(doc["_id"])
    del doc["_id"]
    return doc


# ── Upload ────────────────────────────────────────────────────────────────────

@router.post("/")
async def upload_supervision_doc(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    staff_id: str = Form(...),
    label: str = Form(""),
    meeting_date: str = Form(""),
    doc_type: str = Form(""),
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Admin/Manager only")

    org_id = current_user.get("org_id")
    staff = await db.users.find_one({"_id": ObjectId(staff_id)})
    if not staff or staff.get("org_id") != org_id:
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

    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "org_id": org_id,
        "uploader_id": current_user["id"],
        "uploader_name": current_user.get("name", ""),
        "staff_id": staff_id,
        "staff_name": staff.get("name", ""),
        "filename": file.filename,
        "label": label.strip() or file.filename,
        "doc_type": doc_type.strip() or "other",
        "meeting_date": meeting_date or now[:10],
        "file_ext": file_ext,
        "size_bytes": len(file_data),
        "status": "processing",
        "cqc_mappings": [],
        "care_cert_mappings": [],
        "custom_mappings": [],
        "created_at": now,
    }
    result = await db.supervision_uploads.insert_one(doc)
    upload_id = str(result.inserted_id)

    background_tasks.add_task(
        process_upload_background,
        upload_id, file_data, file.filename, org_id, db
    )

    doc["id"] = upload_id
    del doc["_id"]
    return doc


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("/")
async def list_uploads(
    staff_id: str = None,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Admin/Manager only")
    query = {"org_id": current_user.get("org_id")}
    if staff_id:
        query["staff_id"] = staff_id
    uploads = []
    async for doc in db.supervision_uploads.find(query).sort("created_at", -1):
        d = doc_to_dict(doc)
        d.pop("extracted_text_preview", None)
        uploads.append(d)
    return uploads


# ── Get single ────────────────────────────────────────────────────────────────

@router.get("/{upload_id}")
async def get_upload(
    upload_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Admin/Manager only")
    doc = await db.supervision_uploads.find_one({
        "_id": ObjectId(upload_id),
        "org_id": current_user.get("org_id"),
    })
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return doc_to_dict(doc)


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/{upload_id}")
async def delete_upload(
    upload_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Admin/Manager only")
    result = await db.supervision_uploads.delete_one({
        "_id": ObjectId(upload_id),
        "org_id": current_user.get("org_id"),
    })
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"message": "Deleted"}


# ── Background processing ─────────────────────────────────────────────────────

async def process_upload_background(
    upload_id: str, file_data: bytes, filename: str, org_id: str, db
):
    """Extract text and run AI evidence mapping in the background."""
    try:
        text = _extract_text(file_data, filename)
        if not text.strip():
            await db.supervision_uploads.update_one(
                {"_id": ObjectId(upload_id)},
                {"$set": {"status": "failed", "error": "No text could be extracted from this document"}},
            )
            return

        # ── Phase 1: text extracted — make document available in context sources immediately ──
        await db.supervision_uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {"$set": {
                "full_text": text,
                "status": "text_ready",
            }},
        )

        # ── Phase 2: run AI evidence mapping (slow) ──────────────────────────
        cqc_stds, care_cert_stds, custom_stds = [], [], []
        async for s in db.standards_entries.find({"type": "cqc", "is_active": True}).sort("reference", 1):
            cqc_stds.append(doc_to_dict(s))
        async for s in db.standards_entries.find({"type": "care_cert", "is_active": True}).sort("reference", 1):
            care_cert_stds.append(doc_to_dict(s))
        async for s in db.standards_documents.find(
            {"org_id": org_id, "is_active": True, "parse_status": "parsed"}
        ):
            custom_stds.append(doc_to_dict(s))

        from utils.ai import analyze_doc_for_evidence
        result = await analyze_doc_for_evidence(text, cqc_stds, care_cert_stds, custom_stds)

        await db.supervision_uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {"$set": {
                "status": "done",
                "cqc_mappings": result.get("cqc_mappings", []),
                "care_cert_mappings": result.get("care_cert_mappings", []),
                "custom_mappings": result.get("custom_mappings", []),
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }},
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
        await db.supervision_uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {"$set": {"status": "failed", "error": str(exc)}},
        )


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
