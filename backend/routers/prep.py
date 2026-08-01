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
from datetime import datetime, timezone
from typing import Optional, List
import json
import uuid
import logging

from deps import get_current_user
import database

router = APIRouter(prefix="/prep", tags=["prep"])
logger = logging.getLogger(__name__)


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


class GeneratePrepRequest(BaseModel):
    focus_topic: Optional[str] = None
    included_source_ids: Optional[List[str]] = None


class PrepSave(BaseModel):
    focus_topic: Optional[str] = None
    context_source_ids: Optional[List[str]] = None
    sections: Optional[List[SectionUpdate]] = None
    shared_with_attendees: Optional[bool] = None


def _topic_row_to_dict(row) -> dict:
    """Map focus_topics row to API shape (text column → topic field)."""
    d = dict(row)
    d["topic"] = d.pop("text", "")
    return d


async def _get_meeting_guarded(meeting_id: str, user: dict):
    """Return meeting or raise 403/404."""
    org_id = user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        row = await conn.fetchrow("SELECT * FROM meetings WHERE id=$1", meeting_id)
    if not row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = dict(row)
    if org_id and meeting.get("org_id") != org_id:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if user["role"] in ("attendee", "shared_reviewer"):
        attendee_ids = [a.get("user_id") for a in (meeting.get("attendees") or [])]
        if user["id"] not in attendee_ids and meeting.get("sign_off_manager_id") != user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")
    return meeting


# ── Focus Topics ─────────────────────────────────────────────────────────────

@router.get("/focus-topics")
async def list_focus_topics(current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        rows = await conn.fetch(
            "SELECT * FROM focus_topics WHERE org_id=$1 ORDER BY created_at DESC", org_id,
        )
    return [_topic_row_to_dict(r) for r in rows]


@router.post("/focus-topics")
async def create_focus_topic(data: FocusTopicCreate, current_user=Depends(get_current_user)):
    if current_user["role"] not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager only")
    org_id = current_user.get("org_id", "")
    now = datetime.now(timezone.utc).isoformat()
    topic_id = str(uuid.uuid4())

    async with database.with_org(org_id) as conn:
        if data.is_current:
            await conn.execute(
                "UPDATE focus_topics SET is_current=FALSE WHERE org_id=$1 AND is_current=TRUE",
                org_id,
            )
        await conn.execute(
            "INSERT INTO focus_topics (id, org_id, text, is_current, created_by, created_at) VALUES ($1,$2,$3,$4,$5,$6)",
            topic_id, org_id, data.topic.strip(), data.is_current, current_user["id"], now,
        )

    return {
        "id": topic_id, "org_id": org_id, "topic": data.topic.strip(),
        "is_current": data.is_current, "created_by": current_user["id"], "created_at": now,
    }


@router.put("/focus-topics/{topic_id}")
async def update_focus_topic(topic_id: str, data: FocusTopicCreate, current_user=Depends(get_current_user)):
    if current_user["role"] not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager only")
    org_id = current_user.get("org_id", "")

    async with database.with_org(org_id) as conn:
        if data.is_current:
            await conn.execute(
                "UPDATE focus_topics SET is_current=FALSE WHERE org_id=$1 AND is_current=TRUE", org_id,
            )
        result = await conn.execute(
            "UPDATE focus_topics SET text=$1, is_current=$2 WHERE id=$3 AND org_id=$4",
            data.topic.strip(), data.is_current, topic_id, org_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Focus topic not found")
    return {"message": "Updated"}


@router.delete("/focus-topics/{topic_id}")
async def delete_focus_topic(topic_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager only")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        result = await conn.execute(
            "DELETE FROM focus_topics WHERE id=$1 AND org_id=$2", topic_id, org_id,
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Focus topic not found")
    return {"message": "Deleted"}


# ── Context assembly ──────────────────────────────────────────────────────────

@router.get("/{meeting_id}/context")
async def get_prep_context(meeting_id: str, current_user=Depends(get_current_user)):
    meeting = await _get_meeting_guarded(meeting_id, current_user)
    org_id = meeting.get("org_id", "")

    manager_id = meeting.get("sign_off_manager_id")
    supervisee_ids = [
        a.get("user_id") for a in (meeting.get("attendees") or [])
        if a.get("user_id") and a.get("user_id") != manager_id
    ]

    sources = []

    # 1. Previous system supervision meetings for these supervisees
    if supervisee_ids:
        async with database.with_org(org_id) as conn:
            prev_rows = await conn.fetch(
                """SELECT id, title, date, analysis_id FROM meetings
                   WHERE org_id=$1
                     AND status IN ('signed_off','shared','in_review','reviewed')
                     AND analysis_id IS NOT NULL
                     AND id != $2
                     AND EXISTS (
                         SELECT 1 FROM jsonb_array_elements(attendees) elem
                         WHERE elem->>'user_id' = ANY($3::text[])
                     )
                   ORDER BY date DESC LIMIT 5""",
                org_id, meeting_id, supervisee_ids,
            )
        for prev in prev_rows:
            prev = dict(prev)
            analysis = None
            if prev.get("analysis_id"):
                async with database.with_org(org_id) as conn:
                    a_row = await conn.fetchrow(
                        "SELECT summary, edited_summary, actions FROM analyses WHERE id=$1",
                        prev["analysis_id"],
                    )
                if a_row:
                    analysis = dict(a_row)
            sources.append({
                "source_id": prev["id"],
                "source_type": "previous_meeting",
                "label": prev.get("title", "Previous Supervision"),
                "date": prev.get("date", ""),
                "included": True,
                "summary": ((analysis.get("edited_summary") or analysis.get("summary", ""))[:600] if analysis else ""),
                "actions": [
                    {"text": a.get("text", a.get("action", "")), "completed": a.get("completed", False)}
                    for a in ((analysis.get("actions") or []) if analysis else [])
                ][:10],
            })

    # 2. Uploaded documents for these supervisees
    if supervisee_ids:
        async with database.with_org(org_id) as conn:
            doc_rows = await conn.fetch(
                """SELECT id, label, filename, doc_type, meeting_date, status, full_text
                   FROM supervision_uploads
                   WHERE staff_id = ANY($1::text[]) AND status IN ('text_ready','done')
                   ORDER BY meeting_date DESC LIMIT 10""",
                supervisee_ids,
            )
        for doc in doc_rows:
            doc = dict(doc)
            content = doc.get("full_text") or ""
            sources.append({
                "source_id": doc["id"],
                "source_type": "doc_upload",
                "label": doc.get("label") or doc.get("filename", "Document"),
                "doc_type": doc.get("doc_type", "other"),
                "date": doc.get("meeting_date", ""),
                "status": doc.get("status", "done"),
                "included": True,
                "content_snippet": content[:800],
            })

    # 3. Org-level standards documents
    async with database.with_org(org_id) as conn:
        std_rows = await conn.fetch(
            "SELECT id, label, filename, extracted_text FROM standards_documents WHERE org_id=$1 AND is_active=TRUE AND parse_status='parsed' LIMIT 5",
            org_id,
        )
    for doc in std_rows:
        doc = dict(doc)
        sources.append({
            "source_id": doc["id"],
            "source_type": "org_standards",
            "label": doc.get("label") or doc.get("filename", "Org Document"),
            "included": True,
            "content_snippet": (doc.get("extracted_text") or "")[:600],
        })

    # 4. Current org focus topic
    async with database.with_org(org_id) as conn:
        focus_row = await conn.fetchrow(
            "SELECT id, text FROM focus_topics WHERE org_id=$1 AND is_current=TRUE LIMIT 1", org_id,
        )

    return {
        "meeting_id": meeting_id,
        "supervisees": [
            {"user_id": a.get("user_id"), "name": a.get("name")}
            for a in (meeting.get("attendees") or [])
            if a.get("user_id") != manager_id
        ],
        "sources": sources,
        "current_focus_topic": focus_row["text"] if focus_row else None,
        "current_focus_id": focus_row["id"] if focus_row else None,
    }


# ── Get / Create Prep ─────────────────────────────────────────────────────────

@router.get("/{meeting_id}")
async def get_prep(meeting_id: str, current_user=Depends(get_current_user)):
    await _get_meeting_guarded(meeting_id, current_user)
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        row = await conn.fetchrow("SELECT * FROM meeting_prep WHERE meeting_id=$1", meeting_id)
    if not row:
        return {"meeting_id": meeting_id, "exists": False, "gen_status": "idle", "sections": [], "shared_with_attendees": False}
    d = dict(row)
    d["exists"] = True
    return d


# ── Generate Questions (background) ──────────────────────────────────────────

async def _run_generate_prep(meeting_id: str, focus_topic: str, included_source_ids: list, org_id: str):
    from utils.ai import generate_prep_questions
    try:
        async with database.with_org(org_id) as conn:
            await conn.execute(
                "UPDATE meeting_prep SET gen_status='generating' WHERE meeting_id=$1", meeting_id,
            )

        async with database.with_org(org_id) as conn:
            meeting_row = await conn.fetchrow("SELECT * FROM meetings WHERE id=$1", meeting_id)
        meeting = dict(meeting_row) if meeting_row else {}
        manager_id = meeting.get("sign_off_manager_id")
        supervisee_ids = [
            a.get("user_id") for a in (meeting.get("attendees") or [])
            if a.get("user_id") and a.get("user_id") != manager_id
        ]
        supervisee_names = [
            a.get("name", "") for a in (meeting.get("attendees") or [])
            if a.get("user_id") and a.get("user_id") != manager_id
        ]
        supervisee_name = ", ".join(supervisee_names) if supervisee_names else "the supervisee"

        prev_summaries = []
        include_all = included_source_ids is None
        if supervisee_ids:
            async with database.with_org(org_id) as conn:
                prev_rows = await conn.fetch(
                    """SELECT id, title, date, analysis_id FROM meetings
                       WHERE org_id=$1 AND status IN ('signed_off','shared')
                         AND analysis_id IS NOT NULL AND id != $2
                         AND EXISTS (
                             SELECT 1 FROM jsonb_array_elements(attendees) elem
                             WHERE elem->>'user_id' = ANY($3::text[])
                         )
                       ORDER BY date DESC LIMIT 3""",
                    org_id, meeting_id, supervisee_ids,
                )
            for prev in prev_rows:
                prev = dict(prev)
                if include_all or prev["id"] in included_source_ids:
                    analysis = None
                    if prev.get("analysis_id"):
                        async with database.with_org(org_id) as conn:
                            a_row = await conn.fetchrow(
                                "SELECT summary, edited_summary, actions FROM analyses WHERE id=$1",
                                prev["analysis_id"],
                            )
                        if a_row:
                            analysis = dict(a_row)
                    prev_summaries.append({
                        "title": prev.get("title", ""),
                        "date": prev.get("date", ""),
                        "summary": ((analysis.get("edited_summary") or analysis.get("summary", ""))[:600] if analysis else ""),
                        "actions": ((analysis.get("actions") or []) if analysis else [])[:8],
                    })

        uploaded_docs = []
        if supervisee_ids:
            async with database.with_org(org_id) as conn:
                upload_rows = await conn.fetch(
                    "SELECT id, label, doc_type, full_text FROM supervision_uploads WHERE staff_id = ANY($1::text[]) AND status IN ('text_ready','done') ORDER BY meeting_date DESC LIMIT 6",
                    supervisee_ids,
                )
            for doc in upload_rows:
                doc = dict(doc)
                if include_all or doc["id"] in included_source_ids:
                    content = doc.get("full_text") or ""
                    uploaded_docs.append({
                        "label": doc.get("label", ""),
                        "doc_type": doc.get("doc_type", "other"),
                        "content_snippet": content[:2500],
                    })

        org_values = []
        async with database.with_org(org_id) as conn:
            std_rows = await conn.fetch(
                "SELECT id, label, filename, extracted_text FROM standards_documents WHERE org_id=$1 AND is_active=TRUE AND parse_status='parsed' LIMIT 4",
                org_id,
            )
        for doc in std_rows:
            doc = dict(doc)
            if include_all or doc["id"] in included_source_ids:
                org_values.append({
                    "name": doc.get("label") or doc.get("filename", ""),
                    "snippet": (doc.get("extracted_text") or "")[:600],
                })

        result = await generate_prep_questions(
            supervisee_name=supervisee_name,
            focus_topic=focus_topic or "",
            previous_meeting_summaries=prev_summaries,
            uploaded_docs=uploaded_docs,
            org_values_snippets=org_values,
        )

        now = datetime.now(timezone.utc).isoformat()
        async with database.with_org(org_id) as conn:
            await conn.execute(
                """UPDATE meeting_prep
                   SET sections=$1::jsonb, gen_status=$2, generated_at=$3, updated_at=$3
                   WHERE meeting_id=$4""",
                json.dumps(result.get("sections", [])),
                result.get("gen_status", "done"),
                now, meeting_id,
            )
        logger.info(f"Prep questions generated for meeting {meeting_id}")

    except Exception as exc:
        logger.error(f"Prep generation failed for {meeting_id}: {exc}")
        try:
            now = datetime.now(timezone.utc).isoformat()
            async with database.with_org(org_id) as conn:
                await conn.execute(
                    "UPDATE meeting_prep SET gen_status='failed', updated_at=$1 WHERE meeting_id=$2",
                    now, meeting_id,
                )
        except Exception:
            pass


@router.post("/{meeting_id}/generate")
async def generate_prep(
    meeting_id: str,
    data: GeneratePrepRequest,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager only")

    meeting = await _get_meeting_guarded(meeting_id, current_user)
    org_id = meeting.get("org_id", "")

    focus_topic = (data.focus_topic or "").strip()
    included_source_ids = data.included_source_ids
    now = datetime.now(timezone.utc).isoformat()

    async with database.with_org(org_id) as conn:
        existing = await conn.fetchrow("SELECT id FROM meeting_prep WHERE meeting_id=$1", meeting_id)
        if existing:
            await conn.execute(
                """UPDATE meeting_prep
                   SET focus_topic=$1, included_source_ids=$2::jsonb, gen_status='generating', updated_at=$3
                   WHERE meeting_id=$4""",
                focus_topic,
                json.dumps(included_source_ids if included_source_ids is not None else []),
                now, meeting_id,
            )
        else:
            prep_id = str(uuid.uuid4())
            await conn.execute(
                """INSERT INTO meeting_prep
                   (id, meeting_id, org_id, created_by, focus_topic, included_source_ids,
                    gen_status, shared_with_attendees, sections, coverage_results, created_at, updated_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$11)""",
                prep_id, meeting_id, org_id, current_user["id"],
                focus_topic,
                json.dumps(included_source_ids if included_source_ids is not None else []),
                "generating", False, "[]", "{}", now,
            )

    background_tasks.add_task(_run_generate_prep, meeting_id, focus_topic, included_source_ids, org_id)
    return {"status": "generating", "message": "Question generation started — check back in a moment."}


@router.put("/{meeting_id}")
async def save_prep(meeting_id: str, data: PrepSave, current_user=Depends(get_current_user)):
    if current_user["role"] not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager only")

    await _get_meeting_guarded(meeting_id, current_user)
    org_id = current_user.get("org_id", "")
    now = datetime.now(timezone.utc).isoformat()

    set_clauses = ["updated_at=$1"]
    values = [now]
    idx = 2

    if data.focus_topic is not None:
        set_clauses.append(f"focus_topic=${idx}")
        values.append(data.focus_topic)
        idx += 1
    if data.context_source_ids is not None:
        set_clauses.append(f"included_source_ids=${idx}::jsonb")
        values.append(json.dumps(data.context_source_ids))
        idx += 1
    if data.sections is not None:
        set_clauses.append(f"sections=${idx}::jsonb")
        values.append(json.dumps([s.dict() for s in data.sections]))
        idx += 1
    if data.shared_with_attendees is not None:
        set_clauses.append(f"shared_with_attendees=${idx}")
        values.append(data.shared_with_attendees)
        idx += 1

    values.append(meeting_id)

    async with database.with_org(org_id) as conn:
        existing = await conn.fetchrow("SELECT id FROM meeting_prep WHERE meeting_id=$1", meeting_id)
        if existing:
            await conn.execute(
                f"UPDATE meeting_prep SET {', '.join(set_clauses)} WHERE meeting_id=${idx}",
                *values,
            )
            upserted = False
        else:
            prep_id = str(uuid.uuid4())
            await conn.execute(
                """INSERT INTO meeting_prep
                   (id, meeting_id, org_id, created_by, gen_status, sections, focus_topic,
                    included_source_ids, shared_with_attendees, coverage_results, created_at, updated_at)
                   VALUES ($1,$2,$3,$4,'idle','[]',$5,'[]',$6,'{}',$7,$7)""",
                prep_id, meeting_id, org_id, current_user["id"],
                data.focus_topic or "",
                data.shared_with_attendees or False,
                now,
            )
            upserted = True

    return {"message": "Prep saved", "upserted": upserted}


@router.post("/{meeting_id}/share")
async def share_prep(meeting_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager only")
    await _get_meeting_guarded(meeting_id, current_user)
    org_id = current_user.get("org_id", "")
    now = datetime.now(timezone.utc).isoformat()
    async with database.with_org(org_id) as conn:
        result = await conn.execute(
            "UPDATE meeting_prep SET shared_with_attendees=TRUE, shared_at=$1 WHERE meeting_id=$2",
            now, meeting_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="No prep found — generate questions first")
    return {"message": "Prep shared with attendees"}


@router.post("/{meeting_id}/carry-forward-missed")
async def carry_forward_missed(meeting_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager only")

    meeting = await _get_meeting_guarded(meeting_id, current_user)
    analysis_id = meeting.get("analysis_id")
    if not analysis_id:
        raise HTTPException(status_code=400, detail="No analysis found for this meeting")

    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        prep_row = await conn.fetchrow("SELECT * FROM meeting_prep WHERE meeting_id=$1", meeting_id)
    if not prep_row:
        raise HTTPException(status_code=404, detail="No prep found")

    coverage = prep_row.get("coverage_results") or {}
    if not coverage:
        raise HTTPException(status_code=400, detail="Coverage check hasn't run yet — process the meeting first")

    missed = []
    for section in (prep_row.get("sections") or []):
        for q in section.get("questions", []):
            if q.get("included", True) and coverage.get(q["id"], {}).get("status") == "missed":
                missed.append({
                    "id": f"cf_{q['id']}",
                    "text": q["text"],
                    "action": f"[Carry forward] {q['text']}",
                    "assigned_to": None,
                    "due_date": None,
                    "completed": False,
                    "completed_at": None,
                    "source": "carry_forward_prep",
                })

    if not missed:
        return {"message": "No missed questions to carry forward"}

    async with database.with_org(org_id) as conn:
        a_row = await conn.fetchrow("SELECT id, actions FROM analyses WHERE id=$1", analysis_id)
    if not a_row:
        raise HTTPException(status_code=404, detail="Analysis not found")

    existing_actions = a_row["actions"] or []
    existing_ids = {a.get("id") for a in existing_actions}
    new_actions = [a for a in missed if a["id"] not in existing_ids]
    all_actions = existing_actions + new_actions

    async with database.with_org(org_id) as conn:
        await conn.execute(
            "UPDATE analyses SET actions=$1::jsonb WHERE id=$2",
            json.dumps(all_actions), analysis_id,
        )
    return {"message": f"{len(new_actions)} action(s) added", "added": len(new_actions)}
