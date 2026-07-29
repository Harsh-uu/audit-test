"""Dynamic Supervision Prep — backend router.

Endpoints:
  GET  /api/prep/{meeting_id}/context   — assemble context sources for a meeting
  GET  /api/prep/{meeting_id}           — get existing prep record
  POST /api/prep/{meeting_id}/generate  — trigger AI question generation (background)
  PUT  /api/prep/{meeting_id}           — save / update prep (questions, toggle sources)
  POST /api/prep/{meeting_id}/share     — share prep with supervisee attendees

Focus topics (org-level):
  GET    /api/prep/focus-topics         — list all focus topics for this org
  POST   /api/prep/focus-topics         — add a new topic (admin only)
  PUT    /api/prep/focus-topics/{id}    — set as current / edit (admin only)
  DELETE /api/prep/focus-topics/{id}    — remove (admin only)
"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional, List
import uuid
import logging
import os

from deps import get_db, get_current_user

router = APIRouter(prefix="/prep", tags=["prep"])
logger = logging.getLogger(__name__)


# ── Pydantic models ──────────────────────────────────────────────────────────

class FocusTopicCreate(BaseModel):
    topic: str
    is_current: bool = False


class QuestionUpdate(BaseModel):
    id: str
    text: str
    included: bool


class SectionUpdate(BaseModel):
    section_id: str
    label: str
    questions: List[QuestionUpdate]


class PrepSave(BaseModel):
    focus_topic: Optional[str] = None
    context_source_ids: Optional[List[str]] = None  # IDs of included context sources
    sections: Optional[List[SectionUpdate]] = None
    shared_with_attendees: Optional[bool] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _oid(v):
    try:
        return ObjectId(v)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid id: {v}")


def _d(doc):
    if doc is None:
        return None
    doc["id"] = str(doc.pop("_id"))
    return doc


async def _get_meeting_guarded(meeting_id: str, user: dict, db):
    """Return meeting or raise 403/404."""
    meeting = await db.meetings.find_one({"_id": _oid(meeting_id)})
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    org_id = user.get("org_id")
    if org_id and meeting.get("org_id") != org_id:
        raise HTTPException(status_code=404, detail="Meeting not found")
    # Manager/admin can access any meeting in org; attendees only their own
    if user["role"] in ("attendee", "shared_reviewer"):
        attendee_ids = [a.get("user_id") for a in meeting.get("attendees", [])]
        if user["id"] not in attendee_ids and meeting.get("sign_off_manager_id") != user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")
    return meeting


# ── Focus Topics ─────────────────────────────────────────────────────────────

@router.get("/focus-topics")
async def list_focus_topics(db=Depends(get_db), current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id")
    topics = []
    async for doc in db.focus_topics.find({"org_id": org_id}).sort("created_at", -1):
        topics.append(_d(doc))
    return topics


@router.post("/focus-topics")
async def create_focus_topic(
    data: FocusTopicCreate,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager only")
    org_id = current_user.get("org_id")
    now = datetime.now(timezone.utc).isoformat()

    # If this is set as current, unset all others first
    if data.is_current:
        await db.focus_topics.update_many(
            {"org_id": org_id, "is_current": True},
            {"$set": {"is_current": False}},
        )

    doc = {
        "org_id": org_id,
        "topic": data.topic.strip(),
        "is_current": data.is_current,
        "created_by": current_user["id"],
        "created_by_name": current_user.get("name", ""),
        "created_at": now,
    }
    result = await db.focus_topics.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    del doc["_id"]
    return doc


@router.put("/focus-topics/{topic_id}")
async def update_focus_topic(
    topic_id: str,
    data: FocusTopicCreate,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager only")
    org_id = current_user.get("org_id")

    if data.is_current:
        await db.focus_topics.update_many(
            {"org_id": org_id, "is_current": True},
            {"$set": {"is_current": False}},
        )

    result = await db.focus_topics.update_one(
        {"_id": _oid(topic_id), "org_id": org_id},
        {"$set": {"topic": data.topic.strip(), "is_current": data.is_current}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Focus topic not found")
    return {"message": "Updated"}


@router.delete("/focus-topics/{topic_id}")
async def delete_focus_topic(
    topic_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager only")
    org_id = current_user.get("org_id")
    result = await db.focus_topics.delete_one({"_id": _oid(topic_id), "org_id": org_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Focus topic not found")
    return {"message": "Deleted"}


# ── Context assembly ──────────────────────────────────────────────────────────

@router.get("/{meeting_id}/context")
async def get_prep_context(
    meeting_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Assemble all available context sources for a meeting's supervisee(s)."""
    meeting = await _get_meeting_guarded(meeting_id, current_user, db)
    org_id = meeting.get("org_id")

    # Supervisee IDs (exclude manager)
    manager_id = meeting.get("sign_off_manager_id")
    supervisee_ids = [
        a.get("user_id") for a in meeting.get("attendees", [])
        if a.get("user_id") and a.get("user_id") != manager_id
    ]

    sources = []

    # 1. Previous system supervision meetings for these supervisees
    async for prev in db.meetings.find(
        {
            "attendees.user_id": {"$in": supervisee_ids},
            "status": {"$in": ["signed_off", "shared", "in_review", "reviewed"]},
            "analysis_id": {"$exists": True},
            "_id": {"$ne": ObjectId(meeting_id)},
        },
        {"_id": 1, "title": 1, "date": 1, "analysis_id": 1}
    ).sort("date", -1).limit(5):
        analysis = None
        if prev.get("analysis_id"):
            analysis = await db.analyses.find_one(
                {"_id": ObjectId(prev["analysis_id"])},
                {"summary": 1, "edited_summary": 1, "actions": 1}
            )
        sources.append({
            "source_id": str(prev["_id"]),
            "source_type": "previous_meeting",
            "label": prev.get("title", "Previous Supervision"),
            "date": prev.get("date", ""),
            "included": True,
            "summary": (analysis.get("edited_summary") or analysis.get("summary", ""))[:600] if analysis else "",
            "actions": [
                {"text": a.get("text", a.get("action", "")), "completed": a.get("completed", False)}
                for a in (analysis.get("actions", []) if analysis else [])
            ][:10],
        })

    # 2. Uploaded documents for these supervisees
    async for doc in db.supervision_uploads.find(
        {"staff_id": {"$in": supervisee_ids}, "status": "done"}
    ).sort("meeting_date", -1).limit(10):
        sources.append({
            "source_id": str(doc["_id"]),
            "source_type": "doc_upload",
            "label": doc.get("label") or doc.get("filename", "Document"),
            "doc_type": doc.get("doc_type", "other"),
            "date": doc.get("meeting_date", ""),
            "included": True,
            "content_snippet": (doc.get("full_text") or "")[:800],
        })

    # 3. Org-level standards documents (values, objectives, etc.)
    async for doc in db.standards_documents.find(
        {"org_id": org_id, "is_active": True, "parse_status": "parsed"}
    ).limit(5):
        sources.append({
            "source_id": str(doc["_id"]),
            "source_type": "org_standards",
            "label": doc.get("label") or doc.get("filename", "Org Document"),
            "included": True,
            "content_snippet": (doc.get("full_text") or "")[:600],
        })

    # 4. Current org focus topic
    current_focus = await db.focus_topics.find_one({"org_id": org_id, "is_current": True})

    return {
        "meeting_id": meeting_id,
        "supervisees": [
            {"user_id": a.get("user_id"), "name": a.get("name")}
            for a in meeting.get("attendees", [])
            if a.get("user_id") != manager_id
        ],
        "sources": sources,
        "current_focus_topic": current_focus.get("topic") if current_focus else None,
        "current_focus_id": str(current_focus["_id"]) if current_focus else None,
    }


# ── Get / Create Prep ─────────────────────────────────────────────────────────

@router.get("/{meeting_id}")
async def get_prep(
    meeting_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    await _get_meeting_guarded(meeting_id, current_user, db)
    prep = await db.meeting_prep.find_one({"meeting_id": meeting_id})
    if not prep:
        return {"meeting_id": meeting_id, "exists": False, "gen_status": "idle", "sections": [], "shared_with_attendees": False}
    return _d(prep)


# ── Generate Questions (background) ──────────────────────────────────────────

async def _run_generate_prep(meeting_id: str, focus_topic: str, included_source_ids: list, org_id: str, db):
    """Background task: call AI to generate prep questions."""
    from utils.ai import generate_prep_questions

    try:
        await db.meeting_prep.update_one(
            {"meeting_id": meeting_id},
            {"$set": {"gen_status": "generating"}},
            upsert=True,
        )

        # Load context sources
        meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id)})
        manager_id = meeting.get("sign_off_manager_id")
        supervisee_ids = [
            a.get("user_id") for a in meeting.get("attendees", [])
            if a.get("user_id") and a.get("user_id") != manager_id
        ]
        supervisee_names = [
            a.get("name", "") for a in meeting.get("attendees", [])
            if a.get("user_id") and a.get("user_id") != manager_id
        ]
        supervisee_name = ", ".join(supervisee_names) if supervisee_names else "the supervisee"

        # Previous meetings
        prev_summaries = []
        async for prev in db.meetings.find(
            {
                "attendees.user_id": {"$in": supervisee_ids},
                "status": {"$in": ["signed_off", "shared"]},
                "analysis_id": {"$exists": True},
                "_id": {"$ne": ObjectId(meeting_id)},
            },
            {"_id": 1, "title": 1, "date": 1, "analysis_id": 1}
        ).sort("date", -1).limit(3):
            if str(prev["_id"]) in included_source_ids or not included_source_ids:
                analysis = await db.analyses.find_one(
                    {"_id": ObjectId(prev["analysis_id"])},
                    {"summary": 1, "edited_summary": 1, "actions": 1}
                ) if prev.get("analysis_id") else None
                prev_summaries.append({
                    "title": prev.get("title", ""),
                    "date": prev.get("date", ""),
                    "summary": (analysis.get("edited_summary") or analysis.get("summary", ""))[:600] if analysis else "",
                    "actions": (analysis.get("actions", []) if analysis else [])[:8],
                })

        # Uploaded docs
        uploaded_docs = []
        async for doc in db.supervision_uploads.find(
            {"staff_id": {"$in": supervisee_ids}, "status": "done"}
        ).sort("meeting_date", -1).limit(6):
            if str(doc["_id"]) in included_source_ids or not included_source_ids:
                uploaded_docs.append({
                    "label": doc.get("label", ""),
                    "doc_type": doc.get("doc_type", "other"),
                    "content_snippet": (doc.get("full_text") or "")[:800],
                })

        # Org standards docs
        org_values = []
        async for doc in db.standards_documents.find(
            {"org_id": org_id, "is_active": True, "parse_status": "parsed"}
        ).limit(4):
            if str(doc["_id"]) in included_source_ids or not included_source_ids:
                org_values.append({
                    "name": doc.get("label") or doc.get("filename", ""),
                    "snippet": (doc.get("full_text") or "")[:600],
                })

        result = await generate_prep_questions(
            supervisee_name=supervisee_name,
            focus_topic=focus_topic or "",
            previous_meeting_summaries=prev_summaries,
            uploaded_docs=uploaded_docs,
            org_values_snippets=org_values,
        )

        await db.meeting_prep.update_one(
            {"meeting_id": meeting_id},
            {"$set": {
                "sections": result.get("sections", []),
                "gen_status": result.get("gen_status", "done"),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        logger.info(f"Prep questions generated for meeting {meeting_id}")

    except Exception as exc:
        logger.error(f"Prep generation failed for {meeting_id}: {exc}")
        await db.meeting_prep.update_one(
            {"meeting_id": meeting_id},
            {"$set": {"gen_status": "failed", "updated_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )


@router.post("/{meeting_id}/generate")
async def generate_prep(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    included_source_ids: Optional[List[str]] = None,
    focus_topic: Optional[str] = None,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager only")

    meeting = await _get_meeting_guarded(meeting_id, current_user, db)
    org_id = meeting.get("org_id")

    # Persist focus topic on the prep record immediately
    now = datetime.now(timezone.utc).isoformat()
    await db.meeting_prep.update_one(
        {"meeting_id": meeting_id},
        {"$set": {
            "meeting_id": meeting_id,
            "org_id": org_id,
            "created_by": current_user["id"],
            "focus_topic": focus_topic or "",
            "included_source_ids": included_source_ids or [],
            "gen_status": "generating",
            "shared_with_attendees": False,
            "created_at": now,
            "updated_at": now,
        }},
        upsert=True,
    )

    background_tasks.add_task(
        _run_generate_prep, meeting_id, focus_topic or "", included_source_ids or [], org_id, db
    )

    return {"status": "generating", "message": "Question generation started — check back in a moment."}


# ── Save Prep ─────────────────────────────────────────────────────────────────

@router.put("/{meeting_id}")
async def save_prep(
    meeting_id: str,
    data: PrepSave,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager only")

    await _get_meeting_guarded(meeting_id, current_user, db)
    now = datetime.now(timezone.utc).isoformat()

    update: dict = {"updated_at": now}
    if data.focus_topic is not None:
        update["focus_topic"] = data.focus_topic
    if data.context_source_ids is not None:
        update["included_source_ids"] = data.context_source_ids
    if data.sections is not None:
        update["sections"] = [s.dict() for s in data.sections]
    if data.shared_with_attendees is not None:
        update["shared_with_attendees"] = data.shared_with_attendees

    result = await db.meeting_prep.update_one(
        {"meeting_id": meeting_id},
        {"$set": update},
        upsert=True,
    )
    return {"message": "Prep saved", "upserted": result.upserted_id is not None}


# ── Share with attendees ──────────────────────────────────────────────────────

@router.post("/{meeting_id}/share")
async def share_prep(
    meeting_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager only")

    await _get_meeting_guarded(meeting_id, current_user, db)
    now = datetime.now(timezone.utc).isoformat()

    result = await db.meeting_prep.update_one(
        {"meeting_id": meeting_id},
        {"$set": {"shared_with_attendees": True, "shared_at": now}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="No prep found — generate questions first")
    return {"message": "Prep shared with attendees"}
