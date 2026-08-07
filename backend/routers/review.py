from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from datetime import datetime, timezone
from typing import Optional, List
import asyncio
import json
import logging
import os
import re
import uuid

from deps import get_current_user
import database
from utils.redaction import apply_redactions_to_text as _apply_redactions_to_text
from utils.redaction import apply_redactions_deep as _apply_redactions_deep

router = APIRouter()
logger = logging.getLogger(__name__)


# ── JSONB normalisation helpers ───────────────────────────────────────────────

def _ensure_list(val):
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return val or []


def _ensure_dict(val):
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return val or {}


def _parse_meeting_row(m: dict) -> dict:
    for field in ("attendees", "recording_events", "paused_periods", "shared_with", "pii_redactions"):
        m[field] = _ensure_list(m.get(field))
    for field in ("sign_off_record", "reopen_record"):
        m[field] = _ensure_dict(m.get(field))
    return m


def _parse_analysis_row(a: dict) -> dict:
    for field in ("actions", "risks", "cqc_mappings", "care_cert_mappings", "custom_mappings", "pii_redactions"):
        a[field] = _ensure_list(a.get(field))
    for field in ("speaker_colors",):
        a[field] = _ensure_dict(a.get(field))
    return a


# ── Pydantic models ───────────────────────────────────────────────────────────

class UpdateSummaryRequest(BaseModel):
    summary: str

class UpdateActionsRequest(BaseModel):
    actions: List[dict]

class UpdateEvidenceRequest(BaseModel):
    edited_evidence_summary: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None

class UpdateRiskRequest(BaseModel):
    is_resolved: Optional[bool] = None
    notes: Optional[str] = None

class ShareRequest(BaseModel):
    user_ids: List[str]

class CommentRequest(BaseModel):
    text: str

class PIIReviewRequest(BaseModel):
    redactions: List[dict] = []
    skipped: bool = False

class FindReplaceRequest(BaseModel):
    find: str
    replace: str
    case_sensitive: bool = False
    replace_one: bool = False
    occurrence_index: int = 0

class AnonymiseRequest(BaseModel):
    phrase: str

class SpeakerTextUpdateRequest(BaseModel):
    speaker_text: str
    speaker_colors: Optional[dict] = None

class RescanRequest(BaseModel):
    custom_prompt: Optional[str] = None

class ReopenRequest(BaseModel):
    reason: str

class EmailRequest(BaseModel):
    recipients: List[str]
    message: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _has_privileged_access(meeting: dict, user_id: str) -> bool:
    if meeting.get("created_by") == user_id:
        return True
    for a in (meeting.get("attendees") or []):
        if a.get("user_id") == user_id:
            return True
    return False


async def _log_edit(conn, meeting_id: str, org_id: str, action: str, user_id: str, user_name: str, detail: str = ""):
    await conn.execute(
        "INSERT INTO review_edits (id, meeting_id, org_id, action, user_id, user_name, detail, timestamp) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
        str(uuid.uuid4()), meeting_id, org_id, action, user_id, user_name, detail,
        datetime.now(timezone.utc).isoformat(),
    )


async def _audit(conn, meeting_id: str, org_id: str, action: str, user_id: str, user_name: str, detail: str = ""):
    await conn.execute(
        "INSERT INTO audit_logs (id, meeting_id, org_id, action, user_id, user_name, detail, timestamp) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
        str(uuid.uuid4()), meeting_id, org_id, action, user_id, user_name, detail,
        datetime.now(timezone.utc).isoformat(),
    )


async def delete_audio_after_grace(meeting_id: str):
    """Background task: delete audio after 5 minute grace period."""
    await asyncio.sleep(300)
    try:
        async with database.with_admin() as conn:
            meeting_row = await conn.fetchrow("SELECT * FROM meetings WHERE id=$1", meeting_id)
        if not meeting_row or meeting_row["status"] != "signed_off":
            return
        meeting = dict(meeting_row)
        audio_file_id = meeting.get("audio_file_id")
        now = datetime.now(timezone.utc).isoformat()
        if audio_file_id:
            async with database.with_admin() as conn:
                await conn.execute(
                    "UPDATE audio_files SET is_deleted=TRUE, deletion_status='deleted', deleted_at=$1 WHERE id=$2",
                    now, audio_file_id,
                )
        async with database.with_admin() as conn:
            await conn.execute(
                "UPDATE meetings SET audio_deletion_status='deleted', audio_deleted_at=$1, updated_at=$1 WHERE id=$2",
                now, meeting_id,
            )
        logger.info(f"Audio deleted for meeting {meeting_id}")
    except Exception as e:
        logger.error(f"Audio deletion failed for meeting {meeting_id}: {e}")


# ── Review data ───────────────────────────────────────────────────────────────

@router.get("/{meeting_id}")
async def get_review_data(meeting_id: str, current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        row = await conn.fetchrow("SELECT * FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = _parse_meeting_row(dict(row))

    user_id = current_user.get("id", "")
    if current_user.get("role") not in ["admin", "manager"]:
        attendee_ids = [a.get("user_id", "") for a in meeting["attendees"]]
        shared_with = meeting["shared_with"]
        if (user_id not in attendee_ids
                and not any(s.get("user_id") == user_id for s in shared_with if isinstance(s, dict))
                and user_id != meeting.get("created_by", "")):
            raise HTTPException(status_code=404, detail="Meeting not found")

    if meeting.get("transcript_id"):
        try:
            async with database.with_org(org_id) as conn:
                t_row = await conn.fetchrow("SELECT * FROM transcripts WHERE id=$1", meeting["transcript_id"])
            if t_row:
                t = dict(t_row)
                t["safety_warnings"] = _ensure_list(t.get("safety_warnings"))
                meeting["transcript"] = t
        except Exception:
            pass

    if meeting.get("analysis_id"):
        try:
            async with database.with_org(org_id) as conn:
                a_row = await conn.fetchrow("SELECT * FROM analyses WHERE id=$1", meeting["analysis_id"])
            if a_row:
                meeting["analysis"] = _parse_analysis_row(dict(a_row))
        except Exception:
            pass

    async with database.with_org(org_id) as conn:
        c_rows = await conn.fetch(
            "SELECT * FROM reviewer_comments WHERE meeting_id=$1 ORDER BY created_at ASC",
            meeting_id,
        )
    meeting["comments"] = [dict(c) for c in c_rows]

    redactions = meeting["pii_redactions"]
    privileged = _has_privileged_access(meeting, user_id)

    if redactions and meeting.get("transcript"):
        t = meeting["transcript"]
        if t.get("speaker_text"):
            t["speaker_text"] = _apply_redactions_to_text(t["speaker_text"], redactions)
        if not privileged and t.get("text"):
            t["text"] = _apply_redactions_to_text(t["text"], redactions)

    if redactions and meeting.get("analysis"):
        meeting["analysis"] = _apply_redactions_deep(meeting["analysis"], redactions)

    if not privileged:
        meeting.pop("pii_redactions", None)
        if redactions:
            meeting["pii_redactions_count"] = len(redactions)

    return meeting


# ── Summary & Actions ─────────────────────────────────────────────────────────

@router.put("/{meeting_id}/summary")
async def update_summary(meeting_id: str, data: UpdateSummaryRequest, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can edit the summary")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT analysis_id, status FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if m_row["status"] not in ["in_review", "reviewed"]:
        raise HTTPException(status_code=400, detail="Meeting not in review state")
    analysis_id = m_row["analysis_id"]
    if not analysis_id:
        raise HTTPException(status_code=400, detail="No analysis found")

    now = datetime.now(timezone.utc).isoformat()
    async with database.with_org(org_id) as conn:
        await conn.execute(
            "UPDATE analyses SET edited_summary=$1, last_edited_at=$2, last_edited_by=$3 WHERE id=$4",
            data.summary, now, current_user["id"], analysis_id,
        )
        await _log_edit(conn, meeting_id, org_id, "summary", current_user["id"], current_user.get("name", ""), data.summary[:200])
    return {"message": "Summary updated"}


@router.put("/{meeting_id}/actions")
async def update_actions(meeting_id: str, data: UpdateActionsRequest, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can edit action items")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT analysis_id, status FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if m_row["status"] not in ["in_review", "reviewed"]:
        raise HTTPException(status_code=400, detail="Meeting not in review state")
    analysis_id = m_row["analysis_id"]
    if not analysis_id:
        raise HTTPException(status_code=400, detail="No analysis found")

    now = datetime.now(timezone.utc).isoformat()
    async with database.with_org(org_id) as conn:
        await conn.execute(
            "UPDATE analyses SET actions=$1::jsonb, last_edited_at=$2, last_edited_by=$3 WHERE id=$4",
            json.dumps(data.actions), now, current_user["id"], analysis_id,
        )
        n = len(data.actions)
        completed_count = sum(1 for a in data.actions if a.get("completed"))
        await _log_edit(conn, meeting_id, org_id, "actions", current_user["id"], current_user.get("name", ""),
                        f"{n} action item{'s' if n != 1 else ''} saved; {completed_count} completed")
    return {"message": "Actions updated"}


@router.put("/{meeting_id}/evidence/{evidence_id}")
async def update_evidence(meeting_id: str, evidence_id: str, data: UpdateEvidenceRequest, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can edit evidence items")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT analysis_id, status FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")

    meeting_status = m_row["status"] or ""
    is_finalised = meeting_status in ["signed_off", "shared"]
    analysis_id = m_row["analysis_id"]
    if not analysis_id:
        raise HTTPException(status_code=400, detail="No analysis found")

    async with database.with_org(org_id) as conn:
        a_row = await conn.fetchrow("SELECT * FROM analyses WHERE id=$1", analysis_id)
    if not a_row:
        raise HTTPException(status_code=404, detail="Analysis not found")
    analysis = dict(a_row)

    update_cols = {}
    changed_fields = []
    for mapping_type in ["cqc_mappings", "care_cert_mappings", "custom_mappings"]:
        mappings = list(analysis.get(mapping_type) or [])
        for i, m in enumerate(mappings):
            if m.get("id") == evidence_id:
                if is_finalised:
                    if data.edited_evidence_summary is not None:
                        raise HTTPException(409, "Report is locked. Cannot edit evidence wording after sign-off.")
                    if data.notes is not None:
                        raise HTTPException(409, "Report is locked. Cannot edit evidence notes after sign-off.")
                if data.edited_evidence_summary is not None:
                    old_val = m.get("edited_evidence_summary") or m.get("evidence_summary", "")
                    mappings[i]["edited_evidence_summary"] = data.edited_evidence_summary
                    changed_fields.append(f"evidence_summary changed from '{old_val[:80]}' to '{data.edited_evidence_summary[:80]}'")
                if data.notes is not None:
                    mappings[i]["notes"] = data.notes
                    changed_fields.append("notes updated")
                if data.status is not None and data.status != m.get("status"):
                    changed_fields.append(f"status changed from '{m.get('status')}' to '{data.status}'")
                    mappings[i]["status"] = data.status
                update_cols[mapping_type] = mappings
                break

    if update_cols:
        now = datetime.now(timezone.utc).isoformat()
        set_parts = [f"last_edited_at=$1", f"last_edited_by=$2"]
        values = [now, current_user["id"]]
        idx = 3
        for field, val in update_cols.items():
            set_parts.append(f"{field}=${idx}::jsonb")
            values.append(json.dumps(val))
            idx += 1
        values.append(analysis_id)
        async with database.with_org(org_id) as conn:
            await conn.execute(
                f"UPDATE analyses SET {', '.join(set_parts)} WHERE id=${idx}",
                *values,
            )
            edit_type = "post_signoff_evidence_edit" if is_finalised else "evidence"
            detail = "; ".join(changed_fields) if changed_fields else "evidence updated"
            await _log_edit(conn, meeting_id, org_id, edit_type, current_user["id"], current_user.get("name", ""), detail)

    return {"message": "Evidence updated"}


# ── Risk management ───────────────────────────────────────────────────────────

@router.patch("/{meeting_id}/risks/{risk_id}")
async def update_risk(meeting_id: str, risk_id: str, data: UpdateRiskRequest, current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT analysis_id, status FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not m_row["analysis_id"]:
        raise HTTPException(status_code=404, detail="Analysis not found")

    async with database.with_org(org_id) as conn:
        a_row = await conn.fetchrow("SELECT id, risks FROM analyses WHERE id=$1", m_row["analysis_id"])
    if not a_row:
        raise HTTPException(status_code=404, detail="Analysis not found")

    risks = list(a_row["risks"] or [])
    is_locked = (m_row["status"] or "") in ["signed_off", "shared"]
    updated = False
    for i, r in enumerate(risks):
        if r.get("id") == risk_id:
            if is_locked and data.notes is not None:
                raise HTTPException(409, "Report is locked. Cannot edit risk notes after sign-off.")
            if data.is_resolved is not None:
                risks[i]["is_resolved"] = data.is_resolved
                risks[i]["resolved_at"] = datetime.now(timezone.utc).isoformat() if data.is_resolved else None
                risks[i]["resolved_by"] = current_user.get("name") if data.is_resolved else None
            if data.notes is not None:
                risks[i]["notes"] = data.notes
            updated = True
            break
    if not updated:
        raise HTTPException(status_code=404, detail="Risk not found")

    async with database.with_org(org_id) as conn:
        await conn.execute("UPDATE analyses SET risks=$1::jsonb WHERE id=$2", json.dumps(risks), a_row["id"])
        detail_parts = []
        if data.is_resolved is not None:
            resolved_risk = next((r for r in risks if r.get("id") == risk_id), {})
            risk_label = (resolved_risk.get("risk") or resolved_risk.get("description") or "")[:80]
            status = "Resolved" if data.is_resolved else "Re-opened"
            detail_parts.append(f"{status}: \"{risk_label}\"")
        if data.notes is not None:
            detail_parts.append(f"Notes updated: \"{data.notes[:80]}\"")
        await _log_edit(conn, meeting_id, org_id, "risk", current_user["id"], current_user.get("name", ""),
                        "; ".join(detail_parts))
    return {"message": "Risk updated", "risks": risks}


@router.post("/{meeting_id}/risks/{risk_id}/suggestions")
async def get_risk_suggestions(meeting_id: str, risk_id: str, current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT analysis_id FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row or not m_row["analysis_id"]:
        raise HTTPException(status_code=404, detail="Meeting not found")

    async with database.with_org(org_id) as conn:
        a_row = await conn.fetchrow("SELECT * FROM analyses WHERE id=$1", m_row["analysis_id"])
    if not a_row:
        raise HTTPException(status_code=404, detail="Analysis not found")
    analysis = dict(a_row)
    risk = next((r for r in (analysis.get("risks") or []) if r.get("id") == risk_id), None)
    if not risk:
        raise HTTPException(status_code=404, detail="Risk not found")

    if risk.get("suggested_resolutions") and risk.get("transcript_excerpt"):
        return {"transcript_excerpt": risk["transcript_excerpt"], "suggested_resolutions": risk["suggested_resolutions"]}

    async with database.with_org(org_id) as conn:
        t_row = await conn.fetchrow("SELECT speaker_text, text FROM transcripts WHERE meeting_id=$1", meeting_id)
    transcript_text = (t_row["speaker_text"] or t_row["text"] or "") if t_row else ""

    from utils.ai import generate_risk_suggestions
    result = await generate_risk_suggestions(risk["text"], risk.get("severity", "medium"), transcript_text[:6000])

    risks = list(analysis.get("risks") or [])
    for i, r in enumerate(risks):
        if r.get("id") == risk_id:
            risks[i]["transcript_excerpt"] = result.get("transcript_excerpt", "")
            risks[i]["suggested_resolutions"] = result.get("suggested_resolutions", [])
            break
    async with database.with_org(org_id) as conn:
        await conn.execute("UPDATE analyses SET risks=$1::jsonb WHERE id=$2", json.dumps(risks), m_row["analysis_id"])
    return result


# ── Workflow ──────────────────────────────────────────────────────────────────

@router.post("/{meeting_id}/mark-reviewed")
async def mark_reviewed(meeting_id: str, current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT * FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = dict(m_row)
    if meeting.get("status") not in ["in_review"]:
        raise HTTPException(status_code=400, detail="Meeting not in review state")

    user_id = current_user["id"]
    now = datetime.now(timezone.utc).isoformat()
    attendees = list(meeting.get("attendees") or [])
    found = False
    for a in attendees:
        if a.get("user_id") == user_id:
            a["reviewed"] = True
            a["reviewed_at"] = now
            found = True
            break
    if not found and meeting.get("created_by") != user_id:
        raise HTTPException(status_code=403, detail="You are not an attendee of this meeting")

    all_reviewed = all(a.get("reviewed", False) for a in attendees) if attendees else True
    new_status = "reviewed" if all_reviewed else "in_review"

    async with database.with_org(org_id) as conn:
        await conn.execute(
            "UPDATE meetings SET attendees=$1::jsonb, status=$2, updated_at=$3 WHERE id=$4",
            json.dumps(attendees), new_status, now, meeting_id,
        )
    return {"message": "Marked as reviewed", "all_reviewed": all_reviewed, "status": new_status}


@router.post("/{meeting_id}/signoff")
async def sign_off(meeting_id: str, background_tasks: BackgroundTasks, current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT * FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = dict(m_row)
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can sign off")
    if meeting.get("sign_off_manager_id") and meeting.get("sign_off_manager_id") != current_user["id"]:
        if current_user["role"] != "admin":
            raise HTTPException(status_code=403, detail="You are not the assigned sign-off manager")
    if meeting.get("status") not in ["reviewed", "in_review"]:
        raise HTTPException(status_code=400, detail="Meeting must be reviewed before sign-off")

    now = datetime.now(timezone.utc).isoformat()
    attendees = list(meeting.get("attendees") or [])
    unreviewed_names = [a["name"] for a in attendees if not a.get("reviewed", False)]
    sign_off_record = {"signed_by": current_user["id"], "signed_by_name": current_user["name"], "signed_at": now}

    async with database.with_org(org_id) as conn:
        await conn.execute(
            """UPDATE meetings SET status='signed_off', sign_off_record=$1::jsonb,
               audio_deletion_status='grace_period', audio_grace_period_started_at=$2, updated_at=$2
               WHERE id=$3""",
            json.dumps(sign_off_record), now, meeting_id,
        )

    background_tasks.add_task(delete_audio_after_grace, meeting_id)
    return {"message": "Meeting signed off successfully", "signed_at": now, "unreviewed_attendees": unreviewed_names}


@router.patch("/{meeting_id}/actions/{action_id}")
async def toggle_action_complete(meeting_id: str, action_id: str, data: dict, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can toggle action completion")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT analysis_id FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row or not m_row["analysis_id"]:
        raise HTTPException(status_code=404, detail="Meeting or analysis not found")

    async with database.with_org(org_id) as conn:
        a_row = await conn.fetchrow("SELECT id, actions FROM analyses WHERE id=$1", m_row["analysis_id"])
    if not a_row:
        raise HTTPException(status_code=404, detail="Analysis not found")

    completed = bool(data.get("completed", False))
    now = datetime.now(timezone.utc).isoformat()
    actions = list(a_row["actions"] or [])
    updated = False
    matched_action = None
    for a in actions:
        if a.get("id") == action_id:
            a["completed"] = completed
            a["completed_at"] = now if completed else None
            updated = True
            matched_action = a
            break
    if not updated:
        raise HTTPException(status_code=404, detail="Action not found")

    async with database.with_org(org_id) as conn:
        await conn.execute("UPDATE analyses SET actions=$1::jsonb WHERE id=$2", json.dumps(actions), a_row["id"])
        action_label = (matched_action.get("text") or matched_action.get("action") or "")[:80]
        status = "Completed" if completed else "Re-opened"
        rolled_note = " (carried-over action)" if matched_action.get("is_rolled_over") else ""
        await _log_edit(conn, meeting_id, org_id, "action_completion",
                        current_user["id"], current_user.get("name", ""),
                        f"{status}: \"{action_label}\"{rolled_note}")

    # Propagate completion back to the original meeting so the action stops rolling forward
    if completed and matched_action and matched_action.get("is_rolled_over"):
        source_meeting_id = matched_action.get("source_meeting_id")
        source_action_id = matched_action.get("source_action_id")
        if source_meeting_id and source_action_id:
            try:
                async with database.with_org(org_id) as conn:
                    src_row = await conn.fetchrow(
                        "SELECT analysis_id FROM meetings WHERE id=$1 AND org_id=$2",
                        source_meeting_id, org_id,
                    )
                if src_row and src_row["analysis_id"]:
                    async with database.with_org(org_id) as conn:
                        src_analysis = await conn.fetchrow(
                            "SELECT id, actions FROM analyses WHERE id=$1", src_row["analysis_id"]
                        )
                    if src_analysis:
                        src_actions = list(src_analysis["actions"] or [])
                        for sa in src_actions:
                            if sa.get("id") == source_action_id:
                                sa["completed"] = True
                                sa["completed_at"] = now
                                break
                        async with database.with_org(org_id) as conn:
                            await conn.execute(
                                "UPDATE analyses SET actions=$1::jsonb WHERE id=$2",
                                json.dumps(src_actions), src_analysis["id"],
                            )
            except Exception as e:
                logger.warning(f"Could not propagate action completion to source meeting {source_meeting_id}: {e}")

    return {"message": "Updated", "completed": completed}


# ── Transcript editing ────────────────────────────────────────────────────────

@router.patch("/{meeting_id}/anonymise")
async def anonymise_transcript(meeting_id: str, data: AnonymiseRequest, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can anonymise transcripts")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT transcript_id, status FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if (m_row["status"] or "") in ["signed_off", "shared"]:
        raise HTTPException(status_code=409, detail="Report is locked. Cannot anonymise transcript after sign-off.")

    transcript_id = m_row["transcript_id"]
    if not transcript_id:
        raise HTTPException(status_code=404, detail="No transcript found for this meeting")

    async with database.with_org(org_id) as conn:
        t_row = await conn.fetchrow("SELECT id, text FROM transcripts WHERE id=$1", transcript_id)
    if not t_row:
        raise HTTPException(status_code=404, detail="Transcript not found")

    phrase = data.phrase.strip()
    if not phrase:
        raise HTTPException(status_code=400, detail="Phrase cannot be empty")

    initial = phrase[0].upper() + "."
    original_text = t_row["text"] or ""
    updated_text = re.sub(re.escape(phrase), initial, original_text, flags=re.IGNORECASE)
    if updated_text == original_text:
        return {"message": "Phrase not found in transcript", "replaced": False}

    now = datetime.now(timezone.utc).isoformat()
    async with database.with_org(org_id) as conn:
        await conn.execute("UPDATE transcripts SET text=$1, updated_at=$2 WHERE id=$3", updated_text, now, transcript_id)
        await _log_edit(conn, meeting_id, org_id, "transcript_anonymise", current_user["id"],
                        current_user.get("name", ""), f"Anonymised '{phrase}' → '{initial}'")
    return {"message": f"'{phrase}' replaced with '{initial}'", "replaced": True}


@router.post("/{meeting_id}/find-replace")
async def find_replace_transcript(meeting_id: str, data: FindReplaceRequest, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can edit the transcript")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT transcript_id, status FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if (m_row["status"] or "") in ["signed_off", "shared"]:
        raise HTTPException(status_code=409, detail="Report is locked. Cannot edit transcript after sign-off.")

    transcript_id = m_row["transcript_id"]
    if not transcript_id:
        raise HTTPException(status_code=404, detail="No transcript found")

    async with database.with_org(org_id) as conn:
        t_row = await conn.fetchrow("SELECT id, text, speaker_text FROM transcripts WHERE id=$1", transcript_id)
    if not t_row:
        raise HTTPException(status_code=404, detail="Transcript not found")

    find = data.find.strip()
    if not find:
        raise HTTPException(status_code=400, detail="Find text cannot be empty")

    flags = 0 if data.case_sensitive else re.IGNORECASE
    pattern = re.compile(re.escape(find), flags)
    updates = {}
    replaced = 0

    for field in ("text", "speaker_text"):
        original = t_row[field] or ""
        if not original:
            continue
        if data.replace_one:
            if field != "text":
                continue
            all_matches = list(pattern.finditer(original))
            idx = data.occurrence_index
            if idx < len(all_matches):
                m = all_matches[idx]
                updates[field] = original[:m.start()] + data.replace + original[m.end():]
                replaced += 1
        else:
            new_val, count = pattern.subn(data.replace, original)
            if count:
                updates[field] = new_val
                replaced += count

    if not replaced:
        return {"replaced_count": 0, "message": "No matches found in transcript"}

    now = datetime.now(timezone.utc).isoformat()
    updates["updated_at"] = now

    set_parts = [f"{k}=${i+1}" for i, k in enumerate(updates.keys())]
    values = list(updates.values())
    values.append(transcript_id)
    async with database.with_org(org_id) as conn:
        await conn.execute(
            f"UPDATE transcripts SET {', '.join(set_parts)} WHERE id=${len(values)}",
            *values,
        )
        await _audit(conn, meeting_id, org_id, "transcript_text_edited", current_user["id"],
                     current_user.get("name", ""),
                     f"Find & Replace: '{find}' → '{data.replace}' ({replaced} occurrence{'s' if replaced != 1 else ''})")

    return {"replaced_count": replaced, "message": f"Replaced {replaced} occurrence{'s' if replaced != 1 else ''}"}


@router.patch("/{meeting_id}/speaker-text")
async def update_speaker_text(meeting_id: str, data: SpeakerTextUpdateRequest, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can edit speaker labels")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT transcript_id, status FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if (m_row["status"] or "") in ["signed_off", "shared"]:
        raise HTTPException(status_code=409, detail="Report is locked. Cannot edit speaker labels after sign-off.")

    transcript_id = m_row["transcript_id"]
    if not transcript_id:
        raise HTTPException(status_code=404, detail="No transcript found")

    async with database.with_org(org_id) as conn:
        existing_t = await conn.fetchrow(
            "SELECT speaker_text, speaker_text_edited_at, speaker_text_edited_by_name FROM transcripts WHERE id=$1",
            transcript_id,
        )
    prev_text = existing_t["speaker_text"] if existing_t else ""

    # Parse turns properly — strips [MM:SS] prefix before comparing
    def _parse_turns(s):
        turns = []
        for ln in (s or "").strip().split("\n"):
            ln = ln.strip()
            if not ln:
                continue
            ln = re.sub(r'^\[\d{1,2}:\d{2}\]\s*', '', ln)  # strip timestamp prefix
            if ':' in ln:
                spk, body = ln.split(':', 1)
                turns.append((spk.strip(), body.strip()))
        return turns

    prev_turns = _parse_turns(prev_text) if prev_text else []
    new_turns = _parse_turns(data.speaker_text)

    # Detect speaker label renames
    speaker_renames = {}
    for p, n in zip(prev_turns, new_turns):
        if p[0] != n[0] and p[0] not in speaker_renames:
            speaker_renames[p[0]] = n[0]

    # Detect turn body text changes
    text_edit_details = []
    for i, (p, n) in enumerate(zip(prev_turns, new_turns)):
        if p[1] != n[1]:
            text_edit_details.append(
                f"Turn {i+1} ({n[0]}): \"{p[1][:80]}\" \u2192 \"{n[1][:80]}\""
            )

    has_speaker_rename = bool(speaker_renames)
    has_text_edit = bool(text_edit_details)

    now = datetime.now(timezone.utc).isoformat()
    set_parts = [
        "speaker_text=$1",
        "speaker_text_edited_by_name=$2",
        "speaker_text_edited_at=$3",
    ]
    values = [data.speaker_text, current_user.get("name", ""), now]
    idx = 4

    if data.speaker_colors is not None:
        set_parts.append(f"speaker_colors=${idx}::jsonb")
        values.append(json.dumps(data.speaker_colors))
        idx += 1

    if existing_t and existing_t["speaker_text"]:
        set_parts.append(f"speaker_text_backup=${idx}")
        values.append(existing_t["speaker_text"])
        idx += 1
        set_parts.append(f"speaker_text_backup_at=${idx}")
        values.append(existing_t.get("speaker_text_edited_at") or "")
        idx += 1
        set_parts.append(f"speaker_text_backup_by=${idx}")
        values.append(existing_t.get("speaker_text_edited_by_name") or "")
        idx += 1

    values.append(transcript_id)
    async with database.with_org(org_id) as conn:
        await conn.execute(f"UPDATE transcripts SET {', '.join(set_parts)} WHERE id=${idx}", *values)

        # Build targeted audit entries with meaningful detail
        audit_logs = []
        if has_speaker_rename:
            rename_detail = "; ".join(f"'{old}' \u2192 '{new}'" for old, new in speaker_renames.items())
            audit_logs.append(("speaker_correction", f"Speaker labels updated: {rename_detail}"))
        if has_text_edit:
            parts = text_edit_details[:3]
            edit_detail = "; ".join(parts)
            if len(text_edit_details) > 3:
                edit_detail += f" (+{len(text_edit_details) - 3} more turns)"
            audit_logs.append(("transcript_text_edited", edit_detail))
        if not audit_logs:
            # Colour-only change or first save
            colour_only = data.speaker_colors is not None and not has_text_edit and not has_speaker_rename
            audit_logs.append(("speaker_correction", "Speaker colours updated" if colour_only else "Speaker labels saved"))

        for action, detail in audit_logs:
            await _audit(conn, meeting_id, org_id, action, current_user["id"], current_user.get("name", ""), detail)

    return {
        "message": "Speaker labels updated",
        "speaker_text": data.speaker_text,
        "speaker_colors": data.speaker_colors,
        "edited_by_name": current_user.get("name", ""),
        "edited_at": now,
        "has_backup": bool(existing_t and existing_t["speaker_text"]),
    }


@router.post("/{meeting_id}/speaker-text/restore-backup")
async def restore_speaker_text_backup(meeting_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can restore speaker labels")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT transcript_id FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row or not m_row["transcript_id"]:
        raise HTTPException(status_code=404, detail="No transcript found")

    async with database.with_org(org_id) as conn:
        t_row = await conn.fetchrow(
            "SELECT id, speaker_text_backup, speaker_text_backup_at, speaker_text_backup_by FROM transcripts WHERE id=$1",
            m_row["transcript_id"],
        )
    if not t_row or not t_row["speaker_text_backup"]:
        raise HTTPException(status_code=404, detail="No backup available")

    backup = t_row["speaker_text_backup"]
    now = datetime.now(timezone.utc).isoformat()
    async with database.with_org(org_id) as conn:
        await conn.execute(
            """UPDATE transcripts SET
               speaker_text=$1, speaker_text_edited_by_name=$2, speaker_text_edited_at=$3,
               speaker_text_backup=NULL, speaker_text_backup_at=NULL, speaker_text_backup_by=NULL
               WHERE id=$4""",
            backup, t_row["speaker_text_backup_by"] or "", t_row["speaker_text_backup_at"] or now,
            t_row["id"],
        )
        await _audit(conn, meeting_id, org_id, "speaker_restore_backup", current_user["id"], current_user.get("name", ""))

    return {
        "message": "Previous speaker labels restored",
        "speaker_text": backup,
        "edited_by_name": t_row["speaker_text_backup_by"] or "",
        "edited_at": t_row["speaker_text_backup_at"] or now,
    }


@router.delete("/{meeting_id}/speaker-text")
async def reset_speaker_text(meeting_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can reset speaker labels")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT transcript_id FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row or not m_row["transcript_id"]:
        raise HTTPException(status_code=404, detail="No transcript found")

    now = datetime.now(timezone.utc).isoformat()
    async with database.with_org(org_id) as conn:
        await conn.execute(
            "UPDATE transcripts SET speaker_text=NULL, speaker_text_edited_by_name=NULL, speaker_text_edited_at=NULL WHERE id=$1",
            m_row["transcript_id"],
        )
        await _audit(conn, meeting_id, org_id, "speaker_reset", current_user["id"], current_user.get("name", ""))
    return {"message": "Speaker labels cleared — transcript restored to full raw text"}


# ── AI operations ─────────────────────────────────────────────────────────────

@router.post("/{meeting_id}/rescan-evidence")
async def rescan_evidence(meeting_id: str, data: RescanRequest, background_tasks: BackgroundTasks, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can re-scan evidence")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT * FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = dict(m_row)
    if (meeting.get("status") or "") in ["signed_off", "shared"]:
        raise HTTPException(status_code=409, detail="Report is locked. Cannot re-scan after sign-off.")
    if not meeting.get("analysis_id"):
        raise HTTPException(status_code=400, detail="No analysis found — run initial processing first")

    transcript_id = meeting.get("transcript_id")
    if not transcript_id:
        raise HTTPException(status_code=404, detail="No transcript found")

    async with database.with_org(org_id) as conn:
        t_row = await conn.fetchrow("SELECT speaker_text, text FROM transcripts WHERE id=$1", transcript_id)
    if not t_row:
        raise HTTPException(status_code=404, detail="Transcript not found")

    transcript_text = (t_row["speaker_text"] or t_row["text"] or "").strip()
    if not transcript_text:
        raise HTTPException(status_code=400, detail="Transcript is empty")

    custom_prompt = (data.custom_prompt or "").strip() or None
    async with database.with_org(org_id) as conn:
        await conn.execute("UPDATE meetings SET rescan_status='processing' WHERE id=$1", meeting_id)

    background_tasks.add_task(
        _run_rescan_background,
        meeting_id, meeting, transcript_text,
        str(current_user["id"]), current_user.get("name", ""), org_id, custom_prompt,
    )
    return {"status": "processing", "message": "Re-scanning evidence in the background — this takes 1–2 minutes."}


async def _run_rescan_background(meeting_id: str, meeting: dict, transcript_text: str,
                                  user_id: str, user_name: str, org_id: str, custom_prompt: str = None):
    from utils.ai import analyze_meeting as _analyze_meeting
    try:
        async with database.with_admin() as conn:
            org_row = await conn.fetchrow("SELECT jurisdiction FROM organisations WHERE id=$1", org_id)
            org_jurisdiction = (org_row["jurisdiction"] if org_row else None) or "england"

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
            else:
                cqc_rows = await conn.fetch(
                    "SELECT * FROM standards_entries WHERE type='cqc' AND is_active=TRUE AND (is_system=TRUE OR org_id=$1)",
                    org_id,
                )
                care_cert_rows = await conn.fetch(
                    "SELECT * FROM standards_entries WHERE type='care_cert' AND is_active=TRUE AND (is_system=TRUE OR org_id=$1)",
                    org_id,
                )
        cqc_standards = [dict(r) for r in cqc_rows]
        care_cert_standards = [dict(r) for r in care_cert_rows]

        async with database.with_org(org_id) as conn:
            custom_rows = await conn.fetch(
                "SELECT * FROM standards_documents WHERE org_id=$1 AND is_active=TRUE AND parse_status='parsed'",
                org_id,
            )
        custom_standards = [dict(r) for r in custom_rows]

        supervision_template = None
        async with database.with_admin() as conn:
            tmpl_row = await conn.fetchrow("SELECT data FROM settings WHERE id=$1", f"supervision_template:{org_id}")
            if not tmpl_row:
                tmpl_row = await conn.fetchrow("SELECT data FROM settings WHERE id='supervision_template'")
        if tmpl_row and (tmpl_row["data"] or {}).get("steps"):
            supervision_template = tmpl_row["data"]

        paused_periods = meeting.get("paused_periods") or []
        analysis_result = await _analyze_meeting(
            transcript_text, cqc_standards, care_cert_standards, paused_periods,
            custom_standards, supervision_template, custom_prompt, jurisdiction=org_jurisdiction,
        )

        cqc_kq_map = {s.get("reference"): s.get("key_questions") or [] for s in cqc_standards}
        for item in analysis_result.get("cqc_mappings", []):
            item.setdefault("status", "pending")
            item.setdefault("edited_evidence_summary", None)
            item.setdefault("notes", "")
            if not item.get("key_questions"):
                item["key_questions"] = cqc_kq_map.get(item.get("regulation_ref", ""), [])
        for item in analysis_result.get("care_cert_mappings", []):
            item.setdefault("status", "pending")
            item.setdefault("edited_evidence_summary", None)
            item.setdefault("notes", "")
        for item in analysis_result.get("custom_mappings", []):
            item.setdefault("status", "pending")
            item.setdefault("edited_evidence_summary", None)
            item.setdefault("notes", "")

        now = datetime.now(timezone.utc).isoformat()
        analysis_id = meeting["analysis_id"]
        async with database.with_org(org_id) as conn:
            await conn.execute(
                """UPDATE analyses SET
                   cqc_mappings=$1::jsonb, care_cert_mappings=$2::jsonb, custom_mappings=$3::jsonb,
                   last_edited_at=$4, last_edited_by=$5, rescanned_at=$4, rescanned_by_name=$6
                   WHERE id=$7""",
                json.dumps(analysis_result.get("cqc_mappings", [])),
                json.dumps(analysis_result.get("care_cert_mappings", [])),
                json.dumps(analysis_result.get("custom_mappings", [])),
                now, user_id, user_name, analysis_id,
            )
            await conn.execute("UPDATE meetings SET rescan_status='done' WHERE id=$1", meeting_id)
            await _log_edit(conn, meeting_id, org_id, "evidence_rescan", user_id, user_name,
                            f"Compliance evidence re-scanned{' with guidance: ' + custom_prompt if custom_prompt else ' from corrected transcript'}")
        logger.info(f"Rescan complete for meeting {meeting_id}")
    except Exception as e:
        logger.error(f"Rescan failed for meeting {meeting_id}: {e}")
        try:
            async with database.with_org(org_id) as conn:
                await conn.execute("UPDATE meetings SET rescan_status='failed' WHERE id=$1", meeting_id)
        except Exception:
            pass


@router.post("/{meeting_id}/regenerate-summary")
async def regenerate_summary(meeting_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers/admins can regenerate summaries")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT analysis_id, transcript_id FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not m_row["analysis_id"]:
        raise HTTPException(status_code=400, detail="No analysis found")
    if not m_row["transcript_id"]:
        raise HTTPException(status_code=404, detail="No transcript found")

    async with database.with_org(org_id) as conn:
        t_row = await conn.fetchrow("SELECT speaker_text, text FROM transcripts WHERE id=$1", m_row["transcript_id"])
    if not t_row:
        raise HTTPException(status_code=404, detail="Transcript not found")
    text = (t_row["speaker_text"] or t_row["text"] or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="No transcript text to summarise")

    from utils.ai import generate_meeting_summary
    new_summary = await generate_meeting_summary(text)
    async with database.with_org(org_id) as conn:
        await conn.execute("UPDATE analyses SET summary=$1 WHERE id=$2", new_summary, m_row["analysis_id"])
        await _log_edit(conn, meeting_id, org_id, "summary_regenerated",
                        current_user["id"], current_user.get("name", ""),
                        "Summary regenerated by AI from current transcript")
    return {"summary": new_summary}


@router.post("/{meeting_id}/scan-pii")
async def scan_pii(meeting_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can scan for PII")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT transcript_id, attendees, created_by_name, sign_off_manager_name FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not m_row["transcript_id"]:
        return {"flags": []}

    async with database.with_org(org_id) as conn:
        t_row = await conn.fetchrow("SELECT speaker_text, text FROM transcripts WHERE id=$1", m_row["transcript_id"])
    if not t_row:
        return {"flags": []}

    text = (t_row["speaker_text"] or t_row["text"] or "").strip()
    if not text:
        return {"flags": []}

    from utils.ai import scan_pii_in_transcript
    attendees = m_row["attendees"] or []
    manager_name = m_row["sign_off_manager_name"] or m_row["created_by_name"] or ""
    flags = await scan_pii_in_transcript(text, attendees, manager_name)
    return {"flags": flags}


@router.post("/{meeting_id}/complete-pii-review")
async def complete_pii_review(meeting_id: str, data: PIIReviewRequest, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can complete PII review")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT id FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")

    now = datetime.now(timezone.utc).isoformat()
    clean_redactions = []
    for r in data.redactions:
        original = r.get("original", "").strip()
        replacement = r.get("replacement", "[Redacted]").strip()
        if original and replacement:
            clean_redactions.append({
                "id": r.get("id", str(uuid.uuid4())[:8]),
                "original": original,
                "replacement": replacement,
                "type": r.get("type", "unknown"),
                "added_at": now,
                "added_by": current_user["id"],
            })

    async with database.with_org(org_id) as conn:
        await conn.execute(
            """UPDATE meetings SET
               pii_review_status='reviewed', pii_reviewed_at=$1, pii_reviewed_by=$2,
               pii_reviewed_by_name=$3, pii_skipped=$4, pii_redactions=$5::jsonb
               WHERE id=$6""",
            now, current_user["id"], current_user.get("name", ""),
            data.skipped, json.dumps(clean_redactions), meeting_id,
        )
        action = "pii_review_skipped" if data.skipped else "pii_review_completed"
        detail = "Acknowledged — no changes made" if data.skipped else f"{len(clean_redactions)} redaction(s) applied"
        await _audit(conn, meeting_id, org_id, action, current_user["id"], current_user.get("name", ""), detail)

    return {"message": "PII review completed", "redactions_applied": len(clean_redactions)}


# ── Sharing & Comments ────────────────────────────────────────────────────────

@router.post("/{meeting_id}/share")
async def share_meeting(meeting_id: str, data: ShareRequest, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can share meetings")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT status, shared_with FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if (m_row["status"] or "") not in ["signed_off", "shared"]:
        raise HTTPException(status_code=400, detail="Meeting must be signed off before sharing")

    now = datetime.now(timezone.utc).isoformat()
    shared_with = list(m_row["shared_with"] or [])
    added = []
    for uid in data.user_ids:
        if not any(s.get("user_id") == uid for s in shared_with):
            async with database.with_org(org_id) as conn:
                u_row = await conn.fetchrow("SELECT id, name, email, role FROM users WHERE id=$1 AND org_id=$2", uid, org_id)
            if u_row and u_row["role"] in ("manager", "admin", "shared_reviewer"):
                entry = {"user_id": uid, "name": u_row["name"], "email": u_row["email"], "shared_at": now}
                shared_with.append(entry)
                added.append(entry)

    async with database.with_org(org_id) as conn:
        await conn.execute(
            "UPDATE meetings SET status='shared', shared_with=$1::jsonb, updated_at=$2 WHERE id=$3",
            json.dumps(shared_with), now, meeting_id,
        )
        await _audit(conn, meeting_id, org_id, "meeting_shared", current_user.get("id", ""), current_user.get("name", ""),
                     f"Report shared with: {', '.join(e['name'] for e in added)}" if added else "No new users added")
    return {"message": f"Report shared with {len(added)} new user(s)", "shared_with": shared_with}


@router.post("/{meeting_id}/comments")
async def add_comment(meeting_id: str, data: CommentRequest, current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT status, analysis_id FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    role = current_user.get("role")
    if role not in ["admin", "manager"] and (m_row["status"] or "") not in ["signed_off", "shared"]:
        raise HTTPException(status_code=400, detail="Comments are only available after sign-off")
    if not m_row["analysis_id"] and role not in ["admin", "manager"]:
        raise HTTPException(status_code=400, detail="Meeting has not been processed yet")

    now = datetime.now(timezone.utc).isoformat()
    comment_id = str(uuid.uuid4())
    async with database.with_org(org_id) as conn:
        await conn.execute(
            "INSERT INTO reviewer_comments (id, meeting_id, org_id, user_id, user_name, role, text, created_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
            comment_id, meeting_id, org_id, current_user["id"],
            current_user.get("name", ""), current_user.get("role", ""), data.text, now,
        )
    return {"id": comment_id, "meeting_id": meeting_id, "user_id": current_user["id"],
            "user_name": current_user.get("name", ""), "text": data.text, "created_at": now}


@router.get("/{meeting_id}/comments")
async def get_comments(meeting_id: str, current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT id FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    async with database.with_org(org_id) as conn:
        rows = await conn.fetch("SELECT * FROM reviewer_comments WHERE meeting_id=$1 ORDER BY created_at ASC", meeting_id)
    return [dict(r) for r in rows]


# ── Audit Trail ───────────────────────────────────────────────────────────────

@router.get("/{meeting_id}/audit-trail")
async def get_audit_trail(meeting_id: str, current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT * FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = dict(m_row)
    events = []

    if meeting.get("created_at"):
        events.append({"type": "meeting_created", "label": "Meeting created",
                       "actor": meeting.get("created_by_name", "Unknown"),
                       "timestamp": meeting["created_at"], "detail": meeting.get("title", "")})

    def _jlist(val):
        if val is None: return []
        if isinstance(val, str):
            try: parsed = json.loads(val); return parsed if isinstance(parsed, list) else []
            except Exception: return []
        return val if isinstance(val, list) else []

    def _jobj(val):
        if val is None: return {}
        if isinstance(val, str):
            try: parsed = json.loads(val); return parsed if isinstance(parsed, dict) else {}
            except Exception: return {}
        return val if isinstance(val, dict) else {}

    rec_user_ids = list({ev.get("user_id") for ev in _jlist(meeting.get("recording_events")) if ev.get("user_id")})
    rec_users = {}
    for uid in rec_user_ids:
        try:
            async with database.with_org(org_id) as conn:
                u_row = await conn.fetchrow("SELECT id, name FROM users WHERE id=$1", uid)
            if u_row:
                rec_users[uid] = u_row["name"]
        except Exception:
            pass

    label_map_rec = {"notice_acknowledged": "Recording notice acknowledged", "started": "Recording started",
                     "paused": "Recording paused", "resumed": "Recording resumed", "stopped": "Recording stopped"}
    for ev in _jlist(meeting.get("recording_events")):
        ev_type = ev.get("type") or ev.get("event_type", "unknown")
        actor = rec_users.get(ev.get("user_id", ""), ev.get("user_name", "System"))
        events.append({"type": f"recording_{ev_type}", "label": label_map_rec.get(ev_type, f"Recording {ev_type}"),
                       "actor": actor, "timestamp": ev.get("timestamp", ""), "detail": None})

    if meeting.get("transcript_id"):
        try:
            async with database.with_org(org_id) as conn:
                t_row = await conn.fetchrow("SELECT created_at FROM transcripts WHERE id=$1", meeting["transcript_id"])
            if t_row and t_row["created_at"]:
                events.append({"type": "transcribed", "label": "Audio transcribed", "actor": "1two.one",
                               "timestamp": t_row["created_at"], "detail": None})
        except Exception:
            pass

    if meeting.get("analysis_id"):
        try:
            async with database.with_org(org_id) as conn:
                a_row = await conn.fetchrow("SELECT created_at FROM analyses WHERE id=$1", meeting["analysis_id"])
            if a_row and a_row["created_at"]:
                events.append({"type": "analyzed", "label": "AI analysis completed", "actor": "1two.one",
                               "timestamp": a_row["created_at"], "detail": None})
        except Exception:
            pass

    label_map_edit = {"summary": "Summary edited", "actions": "Action items updated",
                      "evidence": "Evidence item updated", "transcript_anonymise": "Transcript anonymised (manual)",
                      "evidence_rescan": "Evidence re-scanned", "post_signoff_evidence_edit": "Evidence edited after sign-off",
                      "risk": "Risk item updated", "action_completion": "Action item updated",
                      "summary_regenerated": "Summary regenerated (AI)"}
    async with database.with_org(org_id) as conn:
        edit_rows = await conn.fetch(
            "SELECT * FROM review_edits WHERE meeting_id=$1 ORDER BY timestamp ASC", meeting_id,
        )
    for edit in edit_rows:
        edit = dict(edit)
        edit_type = edit.get("action", "unknown")
        is_post_signoff = edit_type == "post_signoff_evidence_edit"
        events.append({"type": f"edit_{edit_type}", "label": label_map_edit.get(edit_type, f"'{edit_type}' edited"),
                       "actor": edit.get("user_name", "Unknown"), "timestamp": edit.get("timestamp", ""),
                       "detail": edit.get("detail"), "flagged": is_post_signoff})

    for a in _jlist(meeting.get("attendees")):
        if a.get("reviewed") and a.get("reviewed_at"):
            events.append({"type": "mark_reviewed", "label": "Marked as reviewed",
                           "actor": a.get("name", "Unknown"), "timestamp": a["reviewed_at"], "detail": None})

    sign_off = _jobj(meeting.get("sign_off_record"))
    if sign_off:
        events.append({"type": "signed_off", "label": "Meeting signed off",
                       "actor": sign_off.get("signed_by_name", "Unknown"),
                       "timestamp": sign_off.get("signed_at", ""), "detail": None})

    async with database.with_org(org_id) as conn:
        c_rows = await conn.fetch("SELECT * FROM reviewer_comments WHERE meeting_id=$1 ORDER BY created_at ASC", meeting_id)
    for c in c_rows:
        c = dict(c)
        text = c.get("text", "")
        events.append({"type": "comment_added", "label": "Comment added", "actor": c.get("user_name", "Unknown"),
                       "timestamp": c.get("created_at", ""), "detail": text[:100] + ("…" if len(text) > 100 else "")})

    label_map_audit = {"speaker_correction": "Speaker labels edited", "transcript_text_edited": "Transcript text edited",
                       "speaker_reset": "Speaker labels reset to raw transcript",
                       "speaker_restore_backup": "Speaker labels restored from backup",
                       "speaker_diarize": "Speaker identification (AI)",
                       "pii_review_completed": "Confidentiality review completed",
                       "pii_review_skipped": "Confidentiality review skipped (acknowledged)",
                       "report_emailed": "Report emailed to recipients",
                       "reopen_requested": "Re-open requested",
                       "reopen_approved": "Re-open approved",
                       "meeting_shared": "Meeting shared with reviewer"}
    async with database.with_org(org_id) as conn:
        log_rows = await conn.fetch("SELECT * FROM audit_logs WHERE meeting_id=$1 ORDER BY timestamp ASC", meeting_id)
    for log in log_rows:
        log = dict(log)
        action = log.get("action", "unknown")
        events.append({"type": action, "label": label_map_audit.get(action, action.replace("_", " ").title()),
                       "actor": log.get("user_name", "System"), "timestamp": log.get("timestamp", ""),
                       "detail": log.get("detail")})

    if (meeting.get("audio_deletion_status") == "deleted") and meeting.get("audio_deleted_at"):
        events.append({"type": "audio_deleted", "label": "Raw audio deleted (GDPR)", "actor": "System",
                       "timestamp": meeting["audio_deleted_at"], "detail": "Audio file removed after sign-off grace period"})

    events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)
    return {"events": events}


# ── Email ─────────────────────────────────────────────────────────────────────

async def _send_email_background(params: dict, meeting_id: str):
    import resend
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        logger.error(f"Email background task skipped for {meeting_id} — RESEND_API_KEY missing")
        return
    resend.api_key = api_key
    try:
        await asyncio.to_thread(resend.Emails.send, params)
        logger.info(f"Background email sent for meeting {meeting_id}")
    except Exception as e:
        logger.error(f"Background email failed for meeting {meeting_id}: {e}")


@router.post("/{meeting_id}/send-email")
async def send_email_report(meeting_id: str, data: EmailRequest, background_tasks: BackgroundTasks, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can email meeting reports")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT title, date, status FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if (m_row["status"] or "") not in ["signed_off", "shared"]:
        raise HTTPException(status_code=400, detail="Meeting must be signed off")

    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="Email service not configured — RESEND_API_KEY is missing.")

    frontend_url = os.environ.get("FRONTEND_URL", "")
    raw_date = m_row["date"] or ""
    try:
        from datetime import datetime as _dt
        _d = _dt.fromisoformat(str(raw_date).replace("Z", "+00:00"))
        friendly_date = _d.strftime("%-d %b %Y")
    except Exception:
        friendly_date = str(raw_date)

    html = f"""<html><body style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
<h2 style="color: #1E3A8A;">Supervision Meeting Report</h2>
<p><strong>Meeting:</strong> {m_row['title']}</p>
<p><strong>Date:</strong> {friendly_date}</p>
<p><strong>Status:</strong> Signed Off</p>
<p>{data.message or 'Please review the meeting report linked below.'}</p>
<p><a href="{frontend_url}/meetings/{meeting_id}/report" style="background:#1E3A8A;color:white;padding:10px 20px;text-decoration:none;border-radius:4px;">View Report</a></p>
<hr/><p style="color:#666;font-size:12px;">Supervision 2.0 - Compliance Evidence Platform</p>
</body></html>"""

    params = {"from": "Supervision 2.0 <noreply@notify.1two.one>", "to": data.recipients,
               "subject": f"Meeting Report: {m_row['title']}", "html": html}
    async with database.with_org(org_id) as conn:
        await _audit(conn, meeting_id, org_id, "report_emailed",
                     current_user["id"], current_user.get("name", ""),
                     f"Report emailed to: {', '.join(data.recipients)}")
    background_tasks.add_task(_send_email_background, params, meeting_id)
    return {"message": f"Email sending to {len(data.recipients)} recipient(s) — this may take a moment."}


# ── PDF Export ────────────────────────────────────────────────────────────────

@router.get("/{meeting_id}/export-pdf")
async def export_pdf(meeting_id: str, include_transcript: bool = False, current_user=Depends(get_current_user)):
    from fastapi.responses import Response
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT * FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = dict(m_row)
    if (meeting.get("status") or "") not in ["signed_off", "shared"]:
        raise HTTPException(status_code=400, detail="PDF export is only available for signed-off meetings")

    # Fetch org jurisdiction to drive dynamic section labels
    async with database.with_admin() as conn:
        org_row = await conn.fetchrow(
            "SELECT jurisdiction, service_type FROM organisations WHERE id=$1", org_id
        )
    org_jurisdiction = (org_row["jurisdiction"] if org_row else None) or "england"
    org_service_type = (org_row["service_type"] if org_row else None) or ""

    analysis = {}
    if meeting.get("analysis_id"):
        async with database.with_org(org_id) as conn:
            a_row = await conn.fetchrow("SELECT * FROM analyses WHERE id=$1", meeting["analysis_id"])
        if a_row:
            analysis = dict(a_row)

    transcript_text = ""
    speaker_text = ""
    if meeting.get("transcript_id"):
        async with database.with_org(org_id) as conn:
            t_row = await conn.fetchrow("SELECT speaker_text, text FROM transcripts WHERE id=$1", meeting["transcript_id"])
        if t_row:
            speaker_text = t_row["speaker_text"] or ""
            if include_transcript:
                transcript_text = t_row["text"] or ""

    redactions = meeting.get("pii_redactions") or []
    if redactions:
        user_id = current_user.get("id", "")
        privileged = _has_privileged_access(meeting, user_id)
        if speaker_text:
            speaker_text = _apply_redactions_to_text(speaker_text, redactions)
        if not privileged and transcript_text:
            transcript_text = _apply_redactions_to_text(transcript_text, redactions)
        if analysis:
            analysis = _apply_redactions_deep(analysis, redactions)

    pdf_bytes = _generate_pdf(meeting, analysis, transcript_text, speaker_text,
                              jurisdiction=org_jurisdiction, service_type=org_service_type)
    safe_title = "".join(c for c in (meeting.get("title") or "report") if c.isalnum() or c in " _-")
    filename = f"supervision_{safe_title[:40].strip().replace(' ', '_')}.pdf"
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _generate_pdf(meeting: dict, analysis: dict, transcript_text: str, speaker_text: str = "",
                  jurisdiction: str = "england", service_type: str = "") -> bytes:
    from io import BytesIO
    from xml.sax.saxutils import escape as _xe
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable

    # ── Jurisdiction-aware section labels ─────────────────────────────────────
    if jurisdiction == "wales":
        reg_section_label = "CIW Regulatory Evidence"
        cert_section_label = "AWIF / Social Care Wales Evidence"
    elif jurisdiction == "scotland":
        reg_section_label = "Care Inspectorate Scotland Evidence"
        cert_section_label = "SSSC Code of Practice Evidence"
    elif jurisdiction == "northern_ireland":
        if service_type == "domiciliary":
            reg_section_label = "RQIA Domiciliary Standards Evidence"
        else:
            reg_section_label = "RQIA Residential Standards Evidence"
        cert_section_label = "NISCC Code & Induction Evidence"
    else:  # england (default)
        reg_section_label = "CQC Regulatory Evidence"
        cert_section_label = "Care Certificate Evidence"


    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)

    NAVY = colors.HexColor("#1E3A8A")
    PURPLE_BG = colors.HexColor("#EDE9FE")
    BLUE_BG = colors.HexColor("#EFF6FF")
    TEAL_BG = colors.HexColor("#F0FDF4")
    LIGHT_GRAY = colors.HexColor("#F8FAFC")
    MID_GRAY = colors.HexColor("#6B7280")
    CONFIDENCE_COLORS = {
        "likely_evidence": colors.HexColor("#059669"),
        "needs_review": colors.HexColor("#D97706"),
        "not_enough_evidence": colors.HexColor("#9CA3AF"),
    }

    title_style = ParagraphStyle("Title", fontName="Helvetica-Bold", fontSize=18, textColor=NAVY, spaceAfter=4)
    body_style = ParagraphStyle("Body", fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#374151"), spaceAfter=3, leading=13)
    small_style = ParagraphStyle("Small", fontName="Helvetica", fontSize=8, textColor=MID_GRAY, spaceAfter=2, leading=11)
    mono_style = ParagraphStyle("Mono", fontName="Courier", fontSize=8, textColor=colors.HexColor("#374151"), leading=12, spaceAfter=4)

    def e(t): return _xe(str(t or ""))

    def section_header(title, bg=NAVY):
        data = [[Paragraph(f'<font color="white"><b>{title}</b></font>', ParagraphStyle("SH", fontName="Helvetica-Bold", fontSize=10, textColor=colors.white))]]
        t = Table(data, colWidths=[170*mm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
        return t

    def evidence_card(ref, name, badge_text, evidence_summary, excerpt, confidence, bg):
        conf_label = {"likely_evidence": "Likely Evidence", "needs_review": "Needs Review", "not_enough_evidence": "Not Enough Evidence"}.get(confidence, confidence)
        conf_color = CONFIDENCE_COLORS.get(confidence, MID_GRAY)
        rows = [[Paragraph(f'<b>{e(ref)}</b> — {e(name)}', body_style), Paragraph(f'<font color="{conf_color.hexval()}"><b>{e(conf_label)}</b></font>', small_style)]]
        if badge_text:
            rows.append([Paragraph(f'<i>{e(badge_text)}</i>', small_style), ""])
        if evidence_summary:
            rows.append([Paragraph(e(evidence_summary), small_style), ""])
        if excerpt:
            rows.append([Paragraph(f'<i>&#34;{e(excerpt)}&#34;</i>', small_style), ""])
        t = Table(rows, colWidths=[130*mm, 40*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("SPAN", (0, 1), (1, 1)), ("SPAN", (0, 2), (1, 2)), ("SPAN", (0, 3), (1, 3)),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
        ]))
        return t

    story = []
    story.append(Paragraph("Supervision 2.0", ParagraphStyle("App", fontName="Helvetica", fontSize=9, textColor=MID_GRAY)))
    story.append(Paragraph(e(meeting.get("title", "Meeting Report")), title_style))
    story.append(HRFlowable(width="100%", thickness=2, color=NAVY, spaceAfter=6))

    sign_off = meeting.get("sign_off_record") or {}
    meta_rows = [
        ["Date", meeting.get("date", "—"), "Status", (meeting.get("status") or "—").replace("_", " ").title()],
        ["Manager", meeting.get("sign_off_manager_name", "—"), "Signed off by", sign_off.get("signed_by_name", "—")],
        ["Attendees", ", ".join([a.get("name", "") for a in (meeting.get("attendees") or [])]), "Signed at", sign_off.get("signed_at", "—")[:16] if sign_off.get("signed_at") else "—"],
    ]
    meta_table = Table(meta_rows, colWidths=[28*mm, 57*mm, 28*mm, 57*mm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), MID_GRAY), ("TEXTCOLOR", (2, 0), (2, -1), MID_GRAY),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GRAY), ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 6*mm))
    story.append(section_header("Meeting Summary"))
    summary = (analysis.get("edited_summary") or analysis.get("summary") or "No summary available.")
    story.append(Spacer(1, 2*mm))

    bullet_style = ParagraphStyle("Bullet", fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#374151"), spaceAfter=3, leading=13, leftIndent=12, bulletIndent=0)
    sections = [s.strip() for s in summary.split("\n\n") if s.strip()]
    for section in sections:
        lines = section.splitlines()
        bullet_lines = [l for l in lines if l.strip().startswith("- ")]
        non_bullet_lines = [l for l in lines if not l.strip().startswith("- ")]
        if bullet_lines and len(bullet_lines) >= len(lines) // 2:
            for bl in bullet_lines:
                text = bl.lstrip("- ").strip()
                story.append(Paragraph(f"\u2022  {e(text)}", bullet_style))
        else:
            full_text = " ".join(l.strip() for l in lines if l.strip())
            story.append(Paragraph(e(full_text), body_style))

    actions = analysis.get("actions") or []
    if actions:
        story.append(Spacer(1, 4*mm))
        story.append(section_header("Action Items"))
        story.append(Spacer(1, 2*mm))
        cell_style = ParagraphStyle("Cell", fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#374151"), leading=12)
        done_style = ParagraphStyle("Done", fontName="Helvetica", fontSize=9, textColor=MID_GRAY, leading=12)
        hdr_style = ParagraphStyle("Hdr", fontName="Helvetica-Bold", fontSize=9, textColor=colors.white, leading=12)
        action_rows = [[Paragraph("#", hdr_style), Paragraph("Action", hdr_style), Paragraph("Assigned To", hdr_style), Paragraph("Due Date", hdr_style), Paragraph("Done", hdr_style)]]
        for i, a in enumerate(actions, 1):
            completed = a.get("completed", False)
            st = done_style if completed else cell_style
            tick = "\u2713" if completed else ""
            action_rows.append([Paragraph(str(i), st), Paragraph(e(a.get("text", "")), st), Paragraph(e(a.get("assigned_to") or "\u2014"), st), Paragraph(e(a.get("due_date") or "\u2014"), st), Paragraph(tick, st)])
        at = Table(action_rows, colWidths=[8*mm, 93*mm, 38*mm, 24*mm, 7*mm])
        at.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(at)

    risks = analysis.get("risks") or []
    if risks:
        story.append(Spacer(1, 4*mm))
        story.append(section_header("Risks & Concerns", bg=colors.HexColor("#7F1D1D")))
        story.append(Spacer(1, 2*mm))
        for r in risks:
            sev = r.get("severity", "").upper()
            sev_color = {"HIGH": "#DC2626", "MEDIUM": "#D97706", "LOW": "#6B7280"}.get(sev, "#6B7280")
            story.append(Paragraph(f'<font color="{sev_color}"><b>[{sev}]</b></font> {e(r.get("text", ""))}', body_style))

    cqc_maps = analysis.get("cqc_mappings") or []
    if cqc_maps:
        story.append(Spacer(1, 4*mm))
        story.append(section_header(reg_section_label, bg=colors.HexColor("#4C1D95")))
        story.append(Spacer(1, 2*mm))
        for m in cqc_maps:
            kq = ", ".join(m.get("key_questions") or [])
            badge = f"Key Questions: {kq}" if kq else ""
            story.append(evidence_card(m.get("regulation_ref", ""), m.get("regulation_name", ""), badge, m.get("evidence_summary", ""), m.get("transcript_excerpt", ""), m.get("confidence", ""), PURPLE_BG))
            story.append(Spacer(1, 2*mm))

    cc_maps = analysis.get("care_cert_mappings") or []
    if cc_maps:
        story.append(Spacer(1, 4*mm))
        story.append(section_header(cert_section_label, bg=colors.HexColor("#1E40AF")))
        story.append(Spacer(1, 2*mm))
        for m in cc_maps:
            badge = f"Outcome {m['outcome_ref']}: {m['outcome_name']}" if m.get("outcome_ref") else ""
            story.append(evidence_card(m.get("standard_ref", ""), m.get("standard_name", ""), badge, m.get("evidence_summary", ""), m.get("transcript_excerpt", ""), m.get("confidence", ""), BLUE_BG))
            story.append(Spacer(1, 2*mm))

    custom_maps = analysis.get("custom_mappings") or []
    if custom_maps:
        story.append(Spacer(1, 4*mm))
        story.append(section_header("Organisational Standards Evidence", bg=colors.HexColor("#065F46")))
        story.append(Spacer(1, 2*mm))
        for m in custom_maps:
            badge = m.get("document_name", "")
            story.append(evidence_card(m.get("criterion_ref", ""), m.get("criterion_name", ""), badge, m.get("evidence_summary", ""), m.get("transcript_excerpt", ""), m.get("confidence", ""), TEAL_BG))
            story.append(Spacer(1, 2*mm))

    if transcript_text or speaker_text:
        import re as _re
        story.append(Spacer(1, 4*mm))
        story.append(section_header("Meeting Transcript (Anonymised)", bg=colors.HexColor("#374151")))
        story.append(Spacer(1, 2*mm))
        MGMT_NAVY = colors.HexColor("#1E3A8A")
        WORKER_GREEN = colors.HexColor("#065F46")
        label_text_style = ParagraphStyle("LabelTxt", fontName="Helvetica-Bold", fontSize=7, textColor=colors.white, leading=9)
        turn_text_style = ParagraphStyle("TurnTxt", fontName="Helvetica", fontSize=8, textColor=colors.HexColor("#374151"), leading=12)

        if speaker_text:
            story.append(Paragraph("Speaker turns identified by AI. Names replaced with initials where anonymised.", small_style))
            story.append(Spacer(1, 2*mm))
            manager_name = meeting.get("sign_off_manager_name", "")
            manager_words = [w.lower() for w in manager_name.split() if len(w) > 2] if manager_name else []
            turns = []
            for line in speaker_text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                m = _re.match(r'^([^:]{1,50}):\s*(.+)', line)
                if m:
                    turns.append([m.group(1).strip(), m.group(2).strip()])
                elif turns:
                    turns[-1][1] += " " + line
                else:
                    turns.append(["Speaker", line])
            for speaker, text in turns:
                sl = speaker.lower()
                is_manager = (sl in ("manager", "supervisor") or any(w in sl for w in manager_words))
                label_color = MGMT_NAVY if is_manager else WORKER_GREEN
                row = [[Paragraph(e(speaker.upper()), label_text_style), Paragraph(e(text), turn_text_style)]]
                t = Table(row, colWidths=[22*mm, 148*mm])
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (0, 0), label_color),
                    ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#F9FAFB")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (0, 0), 4), ("RIGHTPADDING", (0, 0), (0, 0), 4),
                    ("LEFTPADDING", (1, 0), (1, 0), 6), ("RIGHTPADDING", (1, 0), (1, 0), 6),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
                ]))
                story.append(t)
                story.append(Spacer(1, 1*mm))
        else:
            story.append(Paragraph("Names in this transcript have been replaced with initials.", small_style))
            for chunk in transcript_text.split("\n"):
                if chunk.strip():
                    story.append(Paragraph(e(chunk.strip()), mono_style))

    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MID_GRAY))
    from datetime import datetime as _dt
    story.append(Paragraph(f"Generated by Supervision 2.0 on {_dt.now().strftime('%d %b %Y %H:%M')} UTC. This document is confidential.", small_style))

    doc.build(story)
    return buf.getvalue()


@router.get("/{meeting_id}/export-transcript")
async def export_transcript(meeting_id: str, current_user=Depends(get_current_user)):
    from fastapi.responses import Response
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT * FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = dict(m_row)
    if (meeting.get("status") or "") != "signed_off":
        raise HTTPException(status_code=400, detail="Transcript export only available for signed-off meetings")
    if not meeting.get("transcript_id"):
        raise HTTPException(status_code=404, detail="No transcript found for this meeting")

    async with database.with_org(org_id) as conn:
        t_row = await conn.fetchrow("SELECT speaker_text, text FROM transcripts WHERE id=$1", meeting["transcript_id"])
    if not t_row:
        raise HTTPException(status_code=404, detail="Transcript record missing")

    speaker_text = t_row["speaker_text"] or ""
    transcript_text = t_row["text"] or ""
    redactions = meeting.get("pii_redactions") or []
    if redactions:
        if speaker_text:
            speaker_text = _apply_redactions_to_text(speaker_text, redactions)
        if transcript_text:
            transcript_text = _apply_redactions_to_text(transcript_text, redactions)

    pdf_bytes = _generate_transcript_pdf(meeting, speaker_text, transcript_text)
    safe_title = "".join(c for c in (meeting.get("title") or "transcript") if c.isalnum() or c in " _-")
    filename = f"transcript_{safe_title[:40].strip().replace(' ', '_')}.pdf"
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _generate_transcript_pdf(meeting: dict, speaker_text: str, transcript_text: str) -> bytes:
    import re as _re
    from io import BytesIO
    from xml.sax.saxutils import escape as _xe
    from datetime import datetime as _dt
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)

    NAVY = colors.HexColor("#1E3A8A")
    MID_GRAY = colors.HexColor("#6B7280")
    MGMT_NAVY = colors.HexColor("#1E3A8A")
    WORKER_GREEN = colors.HexColor("#065F46")

    title_s = ParagraphStyle("T", fontName="Helvetica-Bold", fontSize=16, textColor=NAVY, spaceAfter=4, leading=20)
    meta_r_s = ParagraphStyle("MR", fontName="Helvetica", fontSize=8, textColor=MID_GRAY, leading=12, alignment=2)
    small_s = ParagraphStyle("S", fontName="Helvetica", fontSize=8, textColor=MID_GRAY, spaceAfter=1, leading=11)
    label_s = ParagraphStyle("L", fontName="Helvetica-Bold", fontSize=7, textColor=colors.white, leading=9)
    turn_s = ParagraphStyle("TT", fontName="Helvetica", fontSize=8.5, textColor=colors.HexColor("#1F2937"), leading=13)
    mono_s = ParagraphStyle("M", fontName="Courier", fontSize=8, textColor=colors.HexColor("#374151"), leading=12, spaceAfter=3)

    def e(t): return _xe(str(t or ""))

    story = []
    hdr = Table(
        [[Paragraph(e(meeting.get("title", "Meeting")), title_s),
          Paragraph(f"Generated {_dt.now().strftime('%d %b %Y %H:%M')} UTC", meta_r_s)]],
        colWidths=[120*mm, 50*mm],
    )
    hdr.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(hdr)

    sign_off_mgr_id = str(meeting.get("sign_off_manager_id") or "")
    supervisees = [a.get("name", "") for a in (meeting.get("attendees") or []) if a.get("user_id") != sign_off_mgr_id]
    if supervisees:
        name_s = ParagraphStyle("SN", fontName="Helvetica-Bold", fontSize=13, textColor=NAVY, spaceAfter=2, leading=17)
        story.append(Paragraph(", ".join(supervisees), name_s))

    meta_parts = [f"Date: {e((meeting.get('date') or '')[:10])}", f"Manager: {e(meeting.get('sign_off_manager_name', '—'))}"]
    story.append(Paragraph("  ·  ".join(meta_parts), small_s))
    story.append(HRFlowable(width="100%", thickness=2, color=NAVY, spaceAfter=6))

    manager_name = meeting.get("sign_off_manager_name", "")
    manager_words = [w.lower() for w in manager_name.split() if len(w) > 2] if manager_name else []

    if speaker_text:
        turns = []
        for line in speaker_text.split("\n"):
            line = line.strip()
            if not line:
                continue
            m = _re.match(r'^([^:]{1,50}):\s*(.+)', line)
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
            row = [[Paragraph(e(speaker.upper()), label_s), Paragraph(e(text), turn_s)]]
            t = Table(row, colWidths=[22*mm, 148*mm])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (0, 0), color), ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#F9FAFB")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (0, 0), 4), ("RIGHTPADDING", (0, 0), (0, 0), 4),
                ("LEFTPADDING", (1, 0), (1, 0), 6), ("RIGHTPADDING", (1, 0), (1, 0), 6),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
            ]))
            story.append(t)
            story.append(Spacer(1, 1*mm))
    elif transcript_text:
        for chunk in transcript_text.split("\n"):
            if chunk.strip():
                story.append(Paragraph(e(chunk.strip()), mono_s))
    else:
        story.append(Paragraph("No transcript available for this meeting.", small_s))

    story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MID_GRAY))
    story.append(Paragraph("1two.one — Transcript — Confidential", small_s))
    doc.build(story)
    return buf.getvalue()


# ── Report re-open ────────────────────────────────────────────────────────────

@router.post("/{meeting_id}/request-reopen")
async def request_reopen(meeting_id: str, data: ReopenRequest, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can request a re-open")
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT status, reopen_requested FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if (m_row["status"] or "") not in ["signed_off", "shared"]:
        raise HTTPException(status_code=400, detail="Meeting is not signed off")
    if m_row["reopen_requested"]:
        raise HTTPException(status_code=409, detail="A re-open request is already pending — awaiting attendee approval")

    now = datetime.now(timezone.utc).isoformat()
    async with database.with_org(org_id) as conn:
        await conn.execute(
            """UPDATE meetings SET
               reopen_requested=TRUE, reopen_requested_by=$1, reopen_requested_by_name=$2,
               reopen_requested_at=$3, reopen_reason=$4
               WHERE id=$5""",
            current_user.get("id", ""), current_user.get("name", ""), now, data.reason.strip(), meeting_id,
        )
        await _audit(conn, meeting_id, org_id, "reopen_requested", current_user.get("id", ""), current_user.get("name", ""),
                     f"Re-open requested. Reason: {data.reason.strip()}")
    return {"message": "Re-open requested — awaiting attendee approval"}


@router.post("/{meeting_id}/approve-reopen")
async def approve_reopen(meeting_id: str, current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT * FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = dict(m_row)
    if not meeting.get("reopen_requested"):
        raise HTTPException(status_code=400, detail="No re-open request is pending for this meeting")

    user_id = current_user.get("id", "")
    attendee_ids = [a.get("user_id", "") for a in (meeting.get("attendees") or [])]
    requester_id = meeting.get("reopen_requested_by", "")
    is_attendee = user_id in attendee_ids and user_id != requester_id
    is_different_manager = current_user["role"] in ["manager", "admin"] and user_id != requester_id
    if not (is_attendee or is_different_manager):
        raise HTTPException(status_code=403, detail="Only meeting attendees or a different manager can approve the re-open request")

    now = datetime.now(timezone.utc).isoformat()
    reopen_reason = meeting.get("reopen_reason", "")
    async with database.with_org(org_id) as conn:
        await conn.execute(
            """UPDATE meetings SET
               status='reviewed', reopen_requested=FALSE,
               reopen_approved_by=$1, reopen_approved_by_name=$2, reopen_approved_at=$3,
               reopen_requested_by=NULL, reopen_requested_by_name=NULL,
               reopen_requested_at=NULL, reopen_reason=NULL,
               updated_at=$3
               WHERE id=$4""",
            user_id, current_user.get("name", ""), now, meeting_id,
        )
        await _audit(conn, meeting_id, org_id, "reopen_approved", user_id, current_user.get("name", ""),
                     f"Re-open approved. Report unlocked for editing. Original reason: {reopen_reason}")
    return {"message": "Re-open approved — report is now unlocked for editing"}
