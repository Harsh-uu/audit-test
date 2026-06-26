from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, BackgroundTasks, Form
from pydantic import BaseModel, EmailStr
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional
import uuid
import logging
from deps import get_db, get_current_user, require_roles
from utils.storage import put_object

router = APIRouter()
logger = logging.getLogger(__name__)


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
async def update_user(user_id: str, data: UpdateUserRequest, db=Depends(get_db), current_user=Depends(get_current_user)):
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
        raise HTTPException(status_code=400, detail=f"Unsupported file type: .{file_ext}. Allowed: {', '.join(allowed_ext)}")

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
