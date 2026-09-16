from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from typing import Optional, List, Literal
import asyncio
import json
import logging
import os
import re
import uuid

from deps import get_current_user, get_manager_scope, get_scoped_staff_ids
import database
from utils.redaction import apply_redactions_to_text as _apply_redactions_to_text
from utils.redaction import apply_redactions_deep as _apply_redactions_deep
from utils.need_reviewer import process_need_review_signals
from utils.supabase_storage import delete_audio
from routers.admin import _stats_cache as _admin_stats_cache

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


def _parse_std_row(r) -> dict:
    """Normalize standards_entries JSONB columns (sub_outcomes, key_questions, keywords)."""
    s = dict(r)
    for f in ("sub_outcomes", "key_questions", "keywords"):
        if isinstance(s.get(f), str):
            try: s[f] = json.loads(s[f])
            except Exception: s[f] = []
        elif s.get(f) is None:
            s[f] = []
    return s


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
    for field in ("actions", "risks", "cqc_mappings", "care_cert_mappings", "custom_mappings", "pii_redactions", "achievements", "learning_needs"):
        a[field] = _ensure_list(a.get(field))
    return a


# Full detail-view column lists — spelled out explicitly (instead of SELECT *)
# so the query is self-documenting and immune to surprise columns from a
# future migration. get_review_data() feeds the whole report page, so it
# needs every column; narrower endpoints (export-pdf) select a trimmed set.
_MEETING_DETAIL_COLS = (
    "id, org_id, title, date, location, meeting_type, meeting_type_id, "
    "created_by, created_by_name, sign_off_manager_id, sign_off_manager_name, "
    "attendees, team_id, setting_id, schedule_id, status, "
    "recording_events, paused_periods, total_paused_duration_seconds, recording_notice_shown_at, "
    "audio_file_id, transcript_id, analysis_id, sign_off_record, "
    "pii_redactions, pii_review_status, pii_reviewed_at, pii_reviewed_by, pii_reviewed_by_name, pii_skipped, "
    "shared_with, audio_deletion_status, audio_grace_period_started_at, audio_deleted_at, "
    "transcript_has_warnings, diarize_status, reopen_record, "
    "reopen_requested, reopen_requested_by, reopen_requested_by_name, reopen_requested_at, reopen_reason, "
    "reopen_approved_by, reopen_approved_by_name, reopen_approved_at, "
    "rescan_status, retranscribed_at, processing_error, notes, created_at, updated_at"
)

_TRANSCRIPT_DETAIL_COLS = (
    "id, meeting_id, org_id, text, speaker_text, safety_warnings, speaker_colors, "
    "speaker_text_backup, speaker_text_backup_at, speaker_text_backup_by, "
    "speaker_text_edited_by_name, speaker_text_edited_at, retranscribed_at, created_at, updated_at"
)

_ANALYSIS_DETAIL_COLS = (
    "id, meeting_id, org_id, summary, edited_summary, achievements, actions, learning_needs, risks, "
    "cqc_mappings, care_cert_mappings, custom_mappings, pii_redactions, "
    "last_edited_by, last_edited_at, rescanned_at, rescanned_by_name, created_at"
)


# ── Pydantic models ───────────────────────────────────────────────────────────

class UpdateSummaryRequest(BaseModel):
    summary: str = Field(max_length=10_000)

class UpdateActionsRequest(BaseModel):
    actions: List[dict]

class UpdateEvidenceRequest(BaseModel):
    edited_evidence_summary: Optional[str] = Field(None, max_length=2_000)
    notes: Optional[str] = Field(None, max_length=2_000)
    status: Optional[str] = None

class BulkEvidenceActionRequest(BaseModel):
    confidence: Literal["likely_evidence", "possible_evidence"]
    status: Literal["accepted", "rejected", "needs_followup"] = "accepted"

class UpdateRiskRequest(BaseModel):
    is_resolved: Optional[bool] = None
    notes: Optional[str] = Field(None, max_length=2_000)

class ShareRequest(BaseModel):
    user_ids: List[str]

class CommentRequest(BaseModel):
    text: str = Field(max_length=2_000)

class PIIReviewRequest(BaseModel):
    redactions: List[dict] = []
    skipped: bool = False

class FindReplaceRequest(BaseModel):
    find: str = Field(max_length=500)
    replace: str = Field(max_length=1_000)
    case_sensitive: bool = False
    replace_one: bool = False
    occurrence_index: int = 0

class AnonymiseRequest(BaseModel):
    phrase: str

class SpeakerTextUpdateRequest(BaseModel):
    speaker_text: str
    speaker_colors: Optional[dict] = None
    edit_note: Optional[str] = None

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
            meeting_row = await conn.fetchrow("SELECT status, audio_file_id FROM meetings WHERE id=$1", meeting_id)
        if not meeting_row or meeting_row["status"] != "signed_off":
            return
        meeting = dict(meeting_row)
        audio_file_id = meeting.get("audio_file_id")
        now = datetime.now(timezone.utc).isoformat()
        if audio_file_id:
            async with database.with_admin() as conn:
                audio_row = await conn.fetchrow("SELECT storage_path FROM audio_files WHERE id=$1", audio_file_id)
            storage_path = audio_row["storage_path"] if audio_row else None
            if storage_path:
                # Delete the actual recording from Supabase Storage first. If this raises,
                # the exception below leaves audio_deletion_status='grace_period' so the
                # job_worker recovery sweep retries it on its next pass — we only mark the
                # row 'deleted' once the file is genuinely gone.
                await delete_audio(storage_path)
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

async def _check_meeting_access(meeting: dict, current_user: dict, org_id: str):
    """Raise 404 if current_user is not entitled to view this meeting.
    Shared by get_review_data, export-pdf, export-transcript and the audit
    trail — every endpoint that returns meeting content must call this."""
    user_id = current_user.get("id", "")
    role = current_user.get("role")

    if role not in ["admin", "manager"]:
        # Non-privileged: must be attendee, creator, or shared reviewer
        attendee_ids = [a.get("user_id", "") for a in meeting.get("attendees", [])]
        shared_with = meeting.get("shared_with", [])
        if (user_id not in attendee_ids
                and not any(s.get("user_id") == user_id for s in shared_with if isinstance(s, dict))
                and user_id != meeting.get("created_by", "")):
            raise HTTPException(status_code=404, detail="Meeting not found")
    elif role == "manager":
        # SEC-003: branch/team-scoped managers must only read meetings where at least
        # one attendee (or the creator) is within their assigned scope.
        mgr_scope = get_manager_scope(current_user)
        if mgr_scope["level"] != "org":
            async with database.with_org(org_id) as _conn:
                scoped_ids = await get_scoped_staff_ids(_conn, org_id, mgr_scope) or []
            attendee_ids = [a.get("user_id", "") for a in meeting.get("attendees", [])]
            if (user_id != meeting.get("created_by", "")
                    and not any(aid in scoped_ids for aid in attendee_ids)):
                raise HTTPException(status_code=404, detail="Meeting not found")


@router.get("/{meeting_id}")
async def get_review_data(meeting_id: str, current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        row = await conn.fetchrow(f"SELECT {_MEETING_DETAIL_COLS} FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = _parse_meeting_row(dict(row))

    user_id = current_user.get("id", "")

    await _check_meeting_access(meeting, current_user, org_id)

    if meeting.get("transcript_id"):
        try:
            async with database.with_org(org_id) as conn:
                t_row = await conn.fetchrow(f"SELECT {_TRANSCRIPT_DETAIL_COLS} FROM transcripts WHERE id=$1", meeting["transcript_id"])
            if t_row:
                t = dict(t_row)
                t["safety_warnings"] = _ensure_list(t.get("safety_warnings"))
                t["speaker_colors"] = _ensure_dict(t.get("speaker_colors"))
                # Raw text (~50 KB) is superseded by speaker_text in the UI.
                # Find-replace has its own focused SELECT; no need to ship text here.
                if t.get("speaker_text"):
                    t.pop("text", None)
                meeting["transcript"] = t
        except Exception:
            pass

    if meeting.get("analysis_id"):
        try:
            async with database.with_org(org_id) as conn:
                a_row = await conn.fetchrow(f"SELECT {_ANALYSIS_DETAIL_COLS} FROM analyses WHERE id=$1", meeting["analysis_id"])
            if a_row:
                meeting["analysis"] = _parse_analysis_row(dict(a_row))
        except Exception:
            pass

    async with database.with_org(org_id) as conn:
        c_rows = await conn.fetch(
            "SELECT id, user_id, user_name, role, text, created_at FROM reviewer_comments WHERE meeting_id=$1 ORDER BY created_at ASC",
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
            data.actions, now, current_user["id"], analysis_id,
        )
        n = len(data.actions)
        completed_count = sum(1 for a in data.actions if a.get("completed"))
        await _log_edit(conn, meeting_id, org_id, "actions", current_user["id"], current_user.get("name", ""),
                        f"{n} action item{'s' if n != 1 else ''} saved; {completed_count} completed")
    return {"message": "Actions updated"}


@router.put("/{meeting_id}/learning_needs")
async def update_learning_needs(meeting_id: str, data: dict, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can edit learning needs")
    org_id = current_user.get("org_id", "")
    learning_needs = data.get("learning_needs", [])
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
            "UPDATE analyses SET learning_needs=$1::jsonb, last_edited_at=$2, last_edited_by=$3 WHERE id=$4",
            learning_needs, now, current_user["id"], analysis_id,
        )
        n = len(learning_needs)
        await _log_edit(conn, meeting_id, org_id, "learning_needs", current_user["id"], current_user.get("name", ""),
                        f"{n} learning need{'s' if n != 1 else ''} saved")
    return {"message": "Learning needs updated"}


@router.put("/{meeting_id}/evidence/{evidence_id}")
async def update_evidence(meeting_id: str, evidence_id: str, data: UpdateEvidenceRequest, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can edit evidence items")
    org_id = current_user.get("org_id", "")

    # Single transaction: SELECT analyses FOR UPDATE serialises concurrent evidence
    # edits so two managers reviewing the same meeting simultaneously cannot
    # overwrite each other's changes.
    update_cols = {}
    changed_fields = []
    is_finalised = False
    old_status_by_type = {}

    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow(
            "SELECT analysis_id, status FROM meetings WHERE id=$1 AND org_id=$2",
            meeting_id, org_id,
        )
        if not m_row:
            raise HTTPException(status_code=404, detail="Meeting not found")

        meeting_status = m_row["status"] or ""
        is_finalised = meeting_status in ["signed_off", "shared"]
        analysis_id = m_row["analysis_id"]
        if not analysis_id:
            raise HTTPException(status_code=400, detail="No analysis found")

        # Lock the analyses row — held until this transaction commits
        a_row = await conn.fetchrow(
            "SELECT cqc_mappings, care_cert_mappings, custom_mappings FROM analyses WHERE id=$1 FOR UPDATE", analysis_id
        )
        if not a_row:
            raise HTTPException(status_code=404, detail="Analysis not found")
        analysis = dict(a_row)

        for mapping_type in ["cqc_mappings", "care_cert_mappings", "custom_mappings"]:
            mappings = _ensure_list(analysis.get(mapping_type))
            for i, m in enumerate(mappings):
                if m.get("id") == evidence_id:
                    if is_finalised:
                        if data.edited_evidence_summary is not None:
                            raise HTTPException(409, "Report is locked. Cannot edit evidence wording after sign-off.")
                        if data.notes is not None:
                            raise HTTPException(409, "Report is locked. Cannot edit evidence notes after sign-off.")
                    old_status_by_type[mapping_type] = m.get("status")
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
                values.append(val)
                idx += 1
            values.append(analysis_id)
            await conn.execute(
                f"UPDATE analyses SET {', '.join(set_parts)} WHERE id=${idx}",
                *values,
            )
            edit_type = "post_signoff_evidence_edit" if is_finalised else "evidence"
            detail = "; ".join(changed_fields) if changed_fields else "evidence updated"
            await _log_edit(conn, meeting_id, org_id, edit_type, current_user["id"], current_user.get("name", ""), detail)

    # Training data — separate admin connection intentionally outside the main transaction
    for mapping_type, mappings in update_cols.items():
        type_label = {"cqc_mappings": "cqc", "care_cert_mappings": "care_cert", "custom_mappings": "custom"}.get(mapping_type, mapping_type)
        for item in mappings:
            if item.get("id") != evidence_id:
                continue
            action = data.status if data.status and data.status != old_status_by_type.get(mapping_type) else ("edited_summary" if data.edited_evidence_summary is not None else "viewed")
            ref = item.get("regulation_ref") or item.get("standard_ref") or item.get("criterion_ref") or ""
            name = item.get("regulation_name") or item.get("standard_name") or item.get("criterion_name") or ""
            try:
                # evidence_item_id stays TEXT (never UUID): it's the AI's own prompt-generated
                # id like "cqc_69"/"cc_26"/"custom_3" (see utils/ai.py's mapping prompts),
                # matched against the mapping JSON's own "id" field — not a foreign key to
                # any UUID-keyed table.
                async with database.with_admin() as fb_conn:
                    await fb_conn.execute(
                        """INSERT INTO evidence_feedback
                           (id, meeting_id, org_id, user_id, user_name, evidence_item_id,
                            evidence_type, standard_ref, standard_name, ai_confidence,
                            manager_action, evidence_summary, edited_summary,
                            transcript_excerpt, timestamp)
                           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)""",
                        str(uuid.uuid4()), meeting_id, org_id,
                        current_user["id"], current_user.get("name", ""),
                        evidence_id, type_label, ref, name,
                        item.get("confidence", ""), action,
                        item.get("evidence_summary", ""),
                        data.edited_evidence_summary,
                        item.get("transcript_excerpt", ""),
                        datetime.now(timezone.utc).isoformat(),
                    )
            except Exception as _fb_err:
                logger.warning(f"evidence_feedback insert skipped: {_fb_err}")

    return {"message": "Evidence updated"}


# Legacy confidence values pre-date the likely/possible rename — treat them as
# "possible" so bulk-accept still works on older analyses.
_CONFIDENCE_ALIASES = {
    "likely_evidence": {"likely_evidence"},
    "possible_evidence": {"possible_evidence", "needs_review", "not_enough_evidence"},
}


@router.post("/{meeting_id}/evidence/bulk-action")
async def bulk_update_evidence(meeting_id: str, data: BulkEvidenceActionRequest, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can edit evidence items")
    org_id = current_user.get("org_id", "")
    confidence_set = _CONFIDENCE_ALIASES.get(data.confidence, {data.confidence})

    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow(
            "SELECT analysis_id, status FROM meetings WHERE id=$1 AND org_id=$2",
            meeting_id, org_id,
        )
        if not m_row:
            raise HTTPException(status_code=404, detail="Meeting not found")
        if (m_row["status"] or "") in ["signed_off", "shared"]:
            raise HTTPException(409, "Report is locked. Cannot bulk-edit evidence after sign-off.")
        analysis_id = m_row["analysis_id"]
        if not analysis_id:
            raise HTTPException(status_code=400, detail="No analysis found")

        a_row = await conn.fetchrow("SELECT cqc_mappings, care_cert_mappings, custom_mappings FROM analyses WHERE id=$1 FOR UPDATE", analysis_id)
        if not a_row:
            raise HTTPException(status_code=404, detail="Analysis not found")
        analysis = dict(a_row)

        all_mappings = {}
        update_cols = {}
        changed_count = 0
        changed_items = []
        for mapping_type in ["cqc_mappings", "care_cert_mappings", "custom_mappings"]:
            mappings = _ensure_list(analysis.get(mapping_type))
            changed = False
            for i, m in enumerate(mappings):
                if m.get("confidence") in confidence_set and (m.get("status") or "pending") == "pending":
                    changed_items.append((mapping_type, dict(m)))
                    mappings[i]["status"] = data.status
                    changed = True
                    changed_count += 1
            all_mappings[mapping_type] = mappings
            if changed:
                update_cols[mapping_type] = mappings

        if update_cols:
            now = datetime.now(timezone.utc).isoformat()
            set_parts = ["last_edited_at=$1", "last_edited_by=$2"]
            values = [now, current_user["id"]]
            idx = 3
            for field, val in update_cols.items():
                set_parts.append(f"{field}=${idx}::jsonb")
                values.append(val)
                idx += 1
            values.append(analysis_id)
            await conn.execute(f"UPDATE analyses SET {', '.join(set_parts)} WHERE id=${idx}", *values)
            confidence_label = "likely evidence" if data.confidence == "likely_evidence" else "possible evidence"
            await _log_edit(conn, meeting_id, org_id, "evidence", current_user["id"], current_user.get("name", ""),
                            f"{changed_count} {confidence_label} item{'s' if changed_count != 1 else ''} bulk-accepted")

    type_label_map = {"cqc_mappings": "cqc", "care_cert_mappings": "care_cert", "custom_mappings": "custom"}
    if changed_items:
        # PERF-003: build all evidence_feedback rows up front and insert them
        # in one connection + one batched executemany, instead of opening a
        # brand new pooled connection and doing one INSERT per item.
        now_ts = datetime.now(timezone.utc).isoformat()
        feedback_rows = []
        for mapping_type, item in changed_items:
            ref = item.get("regulation_ref") or item.get("standard_ref") or item.get("criterion_ref") or ""
            name = item.get("regulation_name") or item.get("standard_name") or item.get("criterion_name") or ""
            feedback_rows.append((
                str(uuid.uuid4()), meeting_id, org_id,
                current_user["id"], current_user.get("name", ""),
                item.get("id", ""), type_label_map.get(mapping_type, mapping_type), ref, name,
                item.get("confidence", ""), data.status,
                item.get("evidence_summary", ""),
                None,
                item.get("transcript_excerpt", ""),
                now_ts,
            ))
        try:
            async with database.with_admin() as fb_conn:
                await fb_conn.executemany(
                    """INSERT INTO evidence_feedback
                       (id, meeting_id, org_id, user_id, user_name, evidence_item_id,
                        evidence_type, standard_ref, standard_name, ai_confidence,
                        manager_action, evidence_summary, edited_summary,
                        transcript_excerpt, timestamp)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)""",
                    feedback_rows,
                )
        except Exception as _fb_err:
            logger.warning(f"evidence_feedback insert skipped (bulk): {_fb_err}")

    return {"message": f"{changed_count} items updated", "updated_count": changed_count, **all_mappings}


# ── Risk management ───────────────────────────────────────────────────────────

@router.patch("/{meeting_id}/risks/{risk_id}")
async def update_risk(meeting_id: str, risk_id: str, data: UpdateRiskRequest, current_user=Depends(get_current_user)):
    # SEC-004: Attendees must not resolve risks or add notes
    if current_user.get("role") not in ("manager", "admin"):
        raise HTTPException(status_code=403, detail="Only managers can update risks")
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

    risks = _ensure_list(a_row["risks"])
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
        await conn.execute("UPDATE analyses SET risks=$1::jsonb WHERE id=$2", risks, a_row["id"])
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
    # SEC-004: Prevent attendees from triggering paid AI calls
    if current_user.get("role") not in ("manager", "admin"):
        raise HTTPException(status_code=403, detail="Only managers can request risk suggestions")

    # Rate limit: 30 AI calls per user per hour
    from utils.rate_limit import check_rate_limit
    async with database.with_admin() as rl_conn:
        await check_rate_limit(
            rl_conn,
            identifier=f"ai_sug:{current_user['id']}",
            max_attempts=30,
            window_minutes=60,
            error_detail="Too many AI requests. Please wait before requesting more suggestions.",
        )

    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow("SELECT analysis_id FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id)
    if not m_row or not m_row["analysis_id"]:
        raise HTTPException(status_code=404, detail="Meeting not found")

    async with database.with_org(org_id) as conn:
        a_row = await conn.fetchrow("SELECT risks FROM analyses WHERE id=$1", m_row["analysis_id"])
    if not a_row:
        raise HTTPException(status_code=404, detail="Analysis not found")
    analysis = dict(a_row)
    risk = next((r for r in _ensure_list(analysis.get("risks")) if r.get("id") == risk_id), None)
    if not risk:
        raise HTTPException(status_code=404, detail="Risk not found")

    if risk.get("suggested_resolutions") and risk.get("transcript_excerpt"):
        return {"transcript_excerpt": risk["transcript_excerpt"], "suggested_resolutions": risk["suggested_resolutions"]}

    async with database.with_org(org_id) as conn:
        t_row = await conn.fetchrow("SELECT speaker_text, text FROM transcripts WHERE meeting_id=$1", meeting_id)
    transcript_text = (t_row["speaker_text"] or t_row["text"] or "") if t_row else ""

    from utils.ai import generate_risk_suggestions
    result = await generate_risk_suggestions(risk["text"], risk.get("severity", "medium"), transcript_text[:6000])

    risks = _ensure_list(analysis.get("risks"))
    for i, r in enumerate(risks):
        if r.get("id") == risk_id:
            risks[i]["transcript_excerpt"] = result.get("transcript_excerpt", "")
            risks[i]["suggested_resolutions"] = result.get("suggested_resolutions", [])
            break
    async with database.with_org(org_id) as conn:
        await conn.execute("UPDATE analyses SET risks=$1::jsonb WHERE id=$2", risks, m_row["analysis_id"])
    return result


# ── Workflow ──────────────────────────────────────────────────────────────────

@router.post("/{meeting_id}/mark-reviewed")
async def mark_reviewed(meeting_id: str, current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    user_id = current_user["id"]
    now = datetime.now(timezone.utc).isoformat()

    # Single transaction: SELECT FOR UPDATE locks the row so concurrent
    # mark-reviewed calls are serialised — each reads the other's change
    # before writing, preventing the lost-update race.
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow(
            "SELECT status, attendees, created_by FROM meetings WHERE id=$1 AND org_id=$2 FOR UPDATE",
            meeting_id, org_id,
        )
        if not m_row:
            raise HTTPException(status_code=404, detail="Meeting not found")
        meeting = dict(m_row)
        if meeting.get("status") not in ["in_review"]:
            raise HTTPException(status_code=400, detail="Meeting not in review state")

        attendees = _ensure_list(meeting.get("attendees"))
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

        await conn.execute(
            "UPDATE meetings SET attendees=$1::jsonb, status=$2, updated_at=$3 WHERE id=$4",
            attendees, new_status, now, meeting_id,
        )

    _admin_stats_cache.pop(org_id, None)
    return {"message": "Marked as reviewed", "all_reviewed": all_reviewed, "status": new_status}


@router.post("/{meeting_id}/signoff")
async def sign_off(meeting_id: str, background_tasks: BackgroundTasks, current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow(
            "SELECT sign_off_manager_id, status, attendees FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id
        )
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = dict(m_row)
    if current_user["role"] not in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Only managers can sign off")
    if meeting.get("sign_off_manager_id") and meeting.get("sign_off_manager_id") != current_user["id"]:
        if current_user["role"] != "admin":
            raise HTTPException(status_code=403, detail="You are not the assigned sign-off manager")
    if meeting.get("status") not in ["reviewed", "in_review"]:
        raise HTTPException(status_code=400, detail="Meeting must be in review state before sign-off")

    now = datetime.now(timezone.utc).isoformat()
    attendees = _ensure_list(meeting.get("attendees"))

    # P3c: All attendees must have reviewed before sign-off is permitted.
    # This prevents regulated supervision records being signed off prematurely.
    if meeting.get("status") == "in_review":
        unreviewed = [a.get("name", "Unknown") for a in attendees if not a.get("reviewed", False)]
        names = ", ".join(unreviewed) if unreviewed else "some attendees"
        raise HTTPException(
            status_code=400,
            detail=f"All attendees must mark the meeting as reviewed before sign-off. Pending: {names}",
        )

    unreviewed_names: list = []  # status == "reviewed" means all have reviewed
    sign_off_record = {"signed_by": current_user["id"], "signed_by_name": current_user["name"], "signed_at": now}

    async with database.with_org(org_id) as conn:
        await conn.execute(
            """UPDATE meetings SET status='signed_off', sign_off_record=$1::jsonb,
               audio_deletion_status='grace_period', audio_grace_period_started_at=$2, updated_at=$2
               WHERE id=$3""",
            sign_off_record, now, meeting_id,
        )

    _admin_stats_cache.pop(org_id, None)
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
    actions = _ensure_list(a_row["actions"])
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
        await conn.execute("UPDATE analyses SET actions=$1::jsonb WHERE id=$2", actions, a_row["id"])
        action_label = (matched_action.get("text") or matched_action.get("action") or "")[:80]
        status = "Completed" if completed else "Re-opened"
        rolled_note = " (carried-over action)" if matched_action.get("is_rolled_over") else ""
        detail_str = f"{status}: \"{action_label}\"{rolled_note}"
        try:
            await _log_edit(conn, meeting_id, org_id, "action_completion",
                            current_user["id"], current_user.get("name", ""),
                            detail_str)
        except Exception as _e:
            logger.error(f"[AUDIT] _log_edit failed for action_completion meeting={meeting_id}: {_e}")
        try:
            await _audit(conn, meeting_id, org_id, "action_status_changed",
                         current_user["id"], current_user.get("name", ""),
                         detail_str)
        except Exception as _e:
            logger.error(f"[AUDIT] _audit failed for action_status_changed meeting={meeting_id}: {_e}")

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
                        src_actions = _ensure_list(src_analysis["actions"])
                        for sa in src_actions:
                            if sa.get("id") == source_action_id:
                                sa["completed"] = True
                                sa["completed_at"] = now
                                break
                        async with database.with_org(org_id) as conn:
                            await conn.execute(
                                "UPDATE analyses SET actions=$1::jsonb WHERE id=$2",
                                src_actions, src_analysis["id"],
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
        m_row = await conn.fetchrow(
            "SELECT transcript_id, status, pii_redactions FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id
        )
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

    # Redactions are applied on top at read-time (never persisted back into the
    # transcript row), so the DB's "previous" text can still contain names a
    # manager already redacted in an earlier confidentiality review. Without
    # this, that redaction shows up here as a fabricated "text edited" entry
    # attributed to whoever next saves speaker labels — even if all they did
    # was flip two speakers and never touched the wording.
    existing_redactions = m_row.get("pii_redactions")
    if isinstance(existing_redactions, str):
        try:
            existing_redactions = json.loads(existing_redactions)
        except Exception:
            existing_redactions = []
    if not isinstance(existing_redactions, list):
        existing_redactions = []
    if existing_redactions and prev_text:
        prev_text = _apply_redactions_to_text(prev_text, existing_redactions)

    # Parse turns properly — strips [MM:SS] prefix before comparing.
    # Continuation lines (no speaker colon) are appended to the previous turn
    # so this matches the frontend parseSpeakerText() behaviour and avoids
    # false-positive "text edited" audit entries when GPT-4o wraps long turns.
    def _parse_turns(s):
        turns = []
        for ln in (s or "").strip().split("\n"):
            ln = ln.strip()
            if not ln:
                continue
            ln = re.sub(r'^\[\d{1,3}:\d{2}\]\s*', '', ln)  # strip [MM:SS] or [MMM:SS]
            if ':' in ln:
                spk, body = ln.split(':', 1)
                # Treat as a new turn only when the speaker label is ≤50 chars,
                # matching the frontend's ^([^:]{1,50}): regex constraint.
                if len(spk.strip()) <= 50:
                    turns.append((spk.strip(), body.strip()))
                elif turns:
                    # Colon is inside the body (e.g. "He said: come back")
                    turns[-1] = (turns[-1][0], (turns[-1][1] + " " + ln).strip())
            elif turns:
                # Continuation line — append to the previous turn's body
                turns[-1] = (turns[-1][0], (turns[-1][1] + " " + ln).strip())
        return turns

    prev_turns = _parse_turns(prev_text) if prev_text else []
    new_turns = _parse_turns(data.speaker_text)

    # Detect speaker label renames
    speaker_renames = {}
    for p, n in zip(prev_turns, new_turns):
        if p[0] != n[0] and p[0] not in speaker_renames:
            speaker_renames[p[0]] = n[0]

    # Detect turn body text changes
    def _clip(s, limit=80):
        """Truncate on a word boundary so audit-log excerpts never cut mid-word."""
        if len(s) <= limit:
            return s
        clipped = s[:limit].rsplit(" ", 1)[0]
        return (clipped or s[:limit]) + "…"

    text_edit_details = []
    for i, (p, n) in enumerate(zip(prev_turns, new_turns)):
        if p[1] != n[1]:
            text_edit_details.append(
                f"Turn {i+1} ({n[0]}): \"{_clip(p[1])}\" \u2192 \"{_clip(n[1])}\""
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
        values.append(data.speaker_colors)
        idx += 1

    if existing_t and existing_t["speaker_text"]:
        set_parts.append(f"speaker_text_backup=${idx}")
        values.append(existing_t["speaker_text"])
        idx += 1
        set_parts.append(f"speaker_text_backup_at=${idx}")
        values.append(existing_t.get("speaker_text_edited_at") or None)
        idx += 1
        set_parts.append(f"speaker_text_backup_by=${idx}")
        values.append(existing_t.get("speaker_text_edited_by_name") or "")
        idx += 1

    values.append(transcript_id)
    async with database.with_org(org_id) as conn:
        result = await conn.execute(f"UPDATE transcripts SET {', '.join(set_parts)} WHERE id=${idx} AND org_id=${idx+1}", *values, org_id)
        affected = int(result.split(" ")[-1]) if result else 0
        if affected == 0:
            raise HTTPException(status_code=500, detail="Speaker labels could not be saved — transcript not found or access denied. Please refresh and try again.")

        # Build targeted audit entries with meaningful detail
        audit_logs = []
        if data.edit_note:
            # Frontend knows exactly what UI action was performed (e.g. "Flip
            # From Here", "Split Turn") — use that verbatim instead of
            # reverse-engineering it from a position-by-position text diff.
            # That diff is unreliable whenever the action changes the turn
            # count (a split shifts every later turn by one position), so it
            # must not run alongside an explicit edit_note — both the
            # rename AND text-edit inference are skipped in that case.
            audit_logs.append(("speaker_correction", data.edit_note))
        else:
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
        m_row = await conn.fetchrow(
            "SELECT status, analysis_id, transcript_id, paused_periods, attendees, sign_off_manager_name, "
            "created_by_name, meeting_type FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id
        )
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
    from utils import standards_cache as sc
    try:
        # Org jurisdiction — from cache, no DB hit if already seen
        cached_org = sc.get_org_info(org_id)
        if cached_org:
            org_jurisdiction = cached_org["jurisdiction"]
            org_service_type = cached_org["service_type"]
        else:
            async with database.with_admin() as conn:
                org_row = await conn.fetchrow("SELECT jurisdiction, service_type FROM organisations WHERE id=$1", org_id)
            org_jurisdiction = (org_row["jurisdiction"] if org_row else None) or "england"
            org_service_type = (org_row["service_type"] if org_row else None) or ""
            sc.set_org_info(org_id, org_jurisdiction, org_service_type)

        # System standards — from in-process cache, zero DB hits
        if org_jurisdiction == "wales":
            cqc_rows       = sc.get_system("ciw", "wales")
            care_cert_rows = sc.get_system("awif", "wales") + sc.get_system("scw", "wales")
        elif org_jurisdiction == "scotland":
            cqc_rows       = sc.get_system("ci", "scotland")
            care_cert_rows = sc.get_system("sssc", "scotland")
        elif org_jurisdiction == "northern_ireland":
            rqia_type      = "rqia_dom" if org_service_type == "domiciliary" else "rqia_res"
            cqc_rows       = sc.get_system(rqia_type, "northern_ireland")
            care_cert_rows = (sc.get_system("niscc_code", "northern_ireland") +
                              sc.get_system("niscc_induction", "northern_ireland"))
        elif org_jurisdiction == "ofsted":
            ofsted_reg_type  = {"school": "eif", "early_years": "eyfs_safeguarding", "childrens_home": "chqs"}.get(org_service_type, "eif")
            ofsted_cert_type = {"school": "teachers_standards", "early_years": "eyfs_learning", "childrens_home": "l3_residential"}.get(org_service_type, "teachers_standards")
            cqc_rows       = sc.get_system(ofsted_reg_type, "ofsted")
            care_cert_rows = sc.get_system(ofsted_cert_type, "ofsted")
        else:
            cqc_rows       = sc.get_system("cqc")
            care_cert_rows = sc.get_system("care_cert")

        # Custom standards — cached per org
        custom_standards = sc.get_custom_docs(org_id)
        if custom_standards is None:
            async with database.with_org(org_id) as conn:
                custom_rows = await conn.fetch(
                    "SELECT id, label, filename, extracted_criteria FROM standards_documents "
                    "WHERE org_id=$1 AND is_active=TRUE AND parse_status='parsed'",
                    org_id,
                )
            custom_standards = [dict(r) for r in custom_rows]
            sc.set_custom_docs(org_id, custom_standards)

        cqc_standards = [_parse_std_row(r) for r in cqc_rows]
        care_cert_standards = [_parse_std_row(r) for r in care_cert_rows]

        supervision_template = None
        async with database.with_admin() as conn:
            tmpl_row = await conn.fetchrow("SELECT data FROM settings WHERE id=$1", f"supervision_template:{org_id}")
            if not tmpl_row:
                tmpl_row = await conn.fetchrow("SELECT data FROM settings WHERE id='supervision_template'")
        if tmpl_row and _ensure_dict(tmpl_row["data"]).get("steps"):
            supervision_template = _ensure_dict(tmpl_row["data"])

        paused_periods = meeting.get("paused_periods") or []
        rescan_attendees = _ensure_list(meeting.get("attendees"))
        rescan_manager_name = meeting.get("sign_off_manager_name") or meeting.get("created_by_name") or ""
        rescan_supervisee_names = [a.get("name") for a in rescan_attendees if a.get("name")]
        rescan_meeting_type = (meeting.get("meeting_type") or "supervision").replace("_", " ").title()
        # Build effective jurisdiction for NI/Ofsted prompt routing (BUGFIX: previously this
        # rescan path passed the plain jurisdiction, so NI rescans always fell through to the
        # CQC/England prompt branch instead of correctly distinguishing residential/domiciliary —
        # matches the same effective_jurisdiction pattern already used by the main pipeline).
        effective_jurisdiction = org_jurisdiction
        if org_jurisdiction == "northern_ireland":
            effective_jurisdiction = f"northern_ireland_{org_service_type or 'domiciliary'}"
        elif org_jurisdiction == "ofsted":
            effective_jurisdiction = f"ofsted_{org_service_type or 'school'}"
        analysis_result = await _analyze_meeting(
            transcript_text, cqc_standards, care_cert_standards, paused_periods,
            custom_standards, supervision_template, custom_prompt, jurisdiction=effective_jurisdiction,
            manager_name=rescan_manager_name, attendee_names=rescan_supervisee_names, meeting_type=rescan_meeting_type,
        )

        async with database.with_admin() as conn:
            await process_need_review_signals(conn, org_id, meeting_id, analysis_result, effective_jurisdiction)
        # Rescan deliberately never overwrites `risks` (only re-scans compliance mappings) —
        # but if a Need Reviewer threshold was JUST reached, merge that one flag in by id.
        new_need_review_risks = [r for r in analysis_result.get("risks", []) if str(r.get("id", "")).startswith("needreview_")]

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

        # Merge with existing mappings — keep anything the re-scan didn't re-find
        # so that a focused re-scan never silently loses previously found evidence.
        now = datetime.now(timezone.utc).isoformat()
        analysis_id = meeting["analysis_id"]
        async with database.with_org(org_id) as conn:
            existing_row = await conn.fetchrow("SELECT cqc_mappings, care_cert_mappings, custom_mappings, risks FROM analyses WHERE id=$1", analysis_id)

        def _jlist_local(val):
            if val is None: return []
            if isinstance(val, str):
                try: return json.loads(val)
                except Exception: return []
            return val if isinstance(val, list) else []

        def _merge(existing, fresh, key_field):
            """Keep existing items not covered by fresh; fresh items take precedence for shared keys."""
            fresh_keys = {item.get(key_field) for item in fresh if item.get(key_field)}
            kept = [item for item in existing if item.get(key_field) not in fresh_keys]
            return fresh + kept

        existing_cqc = _jlist_local(existing_row["cqc_mappings"] if existing_row else [])
        existing_cc  = _jlist_local(existing_row["care_cert_mappings"] if existing_row else [])
        existing_cu  = _jlist_local(existing_row["custom_mappings"] if existing_row else [])

        merged_cqc = _merge(existing_cqc, analysis_result.get("cqc_mappings", []), "regulation_ref")
        merged_cc  = _merge(existing_cc,  analysis_result.get("care_cert_mappings", []), "outcome_ref")
        merged_cu  = _merge(existing_cu,  analysis_result.get("custom_mappings", []), "criterion_ref")

        existing_risks = _jlist_local(existing_row["risks"] if existing_row else [])
        if new_need_review_risks:
            # Fresh Need Reviewer entries win on id collision (e.g. "3 times" -> "4 times")
            new_ids = {r.get("id") for r in new_need_review_risks}
            merged_risks = [r for r in existing_risks if r.get("id") not in new_ids] + new_need_review_risks
        else:
            merged_risks = existing_risks

        async with database.with_org(org_id) as conn:
            await conn.execute(
                """UPDATE analyses SET
                   cqc_mappings=$1::jsonb, care_cert_mappings=$2::jsonb, custom_mappings=$3::jsonb, risks=$8::jsonb,
                   last_edited_at=$4, last_edited_by=$5, rescanned_at=$4, rescanned_by_name=$6
                   WHERE id=$7""",
                merged_cqc,
                merged_cc,
                merged_cu,
                now, user_id, user_name, analysis_id, merged_risks,
            )
            # Also update achievements from the fresh analysis (safe — falls through gracefully if column absent)
            try:
                await conn.execute(
                    "UPDATE analyses SET achievements=$1::jsonb WHERE id=$2",
                    analysis_result.get("achievements", []), analysis_id,
                )
            except Exception as _ach_err:
                logger.warning(f"achievements rescan update skipped: {_ach_err}")
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
        m_row = await conn.fetchrow(
            "SELECT analysis_id, transcript_id, attendees, sign_off_manager_name, created_by_name FROM meetings WHERE id=$1 AND org_id=$2",
            meeting_id, org_id,
        )
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

    regen_attendees = _ensure_list(m_row["attendees"])
    regen_manager_name = m_row["sign_off_manager_name"] or m_row["created_by_name"] or ""
    regen_supervisee_names = [a.get("name") for a in regen_attendees if a.get("name")]

    async with database.with_org(org_id) as conn:
        org_row = await conn.fetchrow("SELECT jurisdiction, service_type FROM organisations WHERE id=$1", org_id)
    regen_jurisdiction = ""
    if org_row and org_row["jurisdiction"] == "ofsted":
        regen_jurisdiction = f"ofsted_{org_row['service_type'] or 'school'}"

    from utils.ai import generate_meeting_summary
    new_summary = await generate_meeting_summary(text, manager_name=regen_manager_name, attendee_names=regen_supervisee_names, jurisdiction=regen_jurisdiction)
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
    attendees = _ensure_list(m_row["attendees"])
    manager_name = m_row["sign_off_manager_name"] or m_row["created_by_name"] or ""
    async with database.with_org(org_id) as conn:
        org_row = await conn.fetchrow("SELECT jurisdiction, service_type FROM organisations WHERE id=$1", org_id)
    scan_jurisdiction = ""
    if org_row and org_row["jurisdiction"] == "ofsted":
        scan_jurisdiction = f"ofsted_{org_row['service_type'] or 'school'}"
    flags = await scan_pii_in_transcript(text, attendees, manager_name, jurisdiction=scan_jurisdiction)
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
        aliases = [a.strip() for a in (r.get("aliases") or []) if isinstance(a, str) and a.strip()]
        if original and replacement:
            clean_redactions.append({
                "id": r.get("id", str(uuid.uuid4())[:8]),
                "original": original,
                "aliases": aliases,
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
            data.skipped, clean_redactions, meeting_id,
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
    shared_with = _ensure_list(m_row["shared_with"])
    already_shared = {s.get("user_id") for s in shared_with}
    new_uids = list(dict.fromkeys(uid for uid in data.user_ids if uid not in already_shared))

    # Batched: one query for all new recipients instead of one per user_id.
    users_by_id = {}
    if new_uids:
        async with database.with_org(org_id) as conn:
            u_rows = await conn.fetch(
                "SELECT id, name, email, role FROM users WHERE id = ANY($1::uuid[]) AND org_id=$2", new_uids, org_id,
            )
        users_by_id = {r["id"]: r for r in u_rows}

    added = []
    for uid in new_uids:
        u_row = users_by_id.get(uid)
        if u_row and u_row["role"] in ("manager", "admin", "shared_reviewer"):
            entry = {"user_id": uid, "name": u_row["name"], "email": u_row["email"], "shared_at": now}
            shared_with.append(entry)
            added.append(entry)

    async with database.with_org(org_id) as conn:
        await conn.execute(
            "UPDATE meetings SET status='shared', shared_with=$1::jsonb, updated_at=$2 WHERE id=$3",
            shared_with, now, meeting_id,
        )
        await _audit(conn, meeting_id, org_id, "meeting_shared", current_user.get("id", ""), current_user.get("name", ""),
                     f"Report shared with: {', '.join(e['name'] for e in added)}" if added else "No new users added")
    return {"message": f"Report shared with {len(added)} new user(s)", "shared_with": shared_with}


@router.post("/{meeting_id}/comments")
async def add_comment(meeting_id: str, data: CommentRequest, current_user=Depends(get_current_user)):
    org_id = current_user.get("org_id", "")
    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow(
            "SELECT status, analysis_id, attendees, shared_with, created_by FROM meetings WHERE id=$1 AND org_id=$2",
            meeting_id, org_id,
        )
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    role = current_user.get("role")
    user_id = current_user.get("id", "")

    # Non-admin/manager callers must be an attendee, creator, or shared reviewer
    if role not in ["admin", "manager"]:
        attendee_ids = [a.get("user_id", "") for a in _ensure_list(m_row["attendees"])]
        shared_with_list = _ensure_list(m_row["shared_with"])
        if (user_id not in attendee_ids
                and not any(s.get("user_id") == user_id for s in shared_with_list if isinstance(s, dict))
                and user_id != (m_row.get("created_by") or "")):
            raise HTTPException(status_code=404, detail="Meeting not found")

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
        m_row = await conn.fetchrow(
            "SELECT id, attendees, shared_with, created_by FROM meetings WHERE id=$1 AND org_id=$2",
            meeting_id, org_id,
        )
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")

    meeting_for_check = {
        "attendees": _ensure_list(m_row["attendees"]),
        "shared_with": _ensure_list(m_row["shared_with"]),
        "created_by": m_row["created_by"],
    }
    await _check_meeting_access(meeting_for_check, current_user, org_id)

    async with database.with_org(org_id) as conn:
        rows = await conn.fetch(
            "SELECT id, user_id, user_name, role, text, created_at FROM reviewer_comments WHERE meeting_id=$1 ORDER BY created_at ASC",
            meeting_id,
        )
    return [dict(r) for r in rows]


# ── Audit Trail ───────────────────────────────────────────────────────────────

@router.get("/{meeting_id}/audit-trail")
async def get_audit_trail(meeting_id: str, current_user=Depends(get_current_user)):
    import logging as _log, traceback as _tb
    _logger = _log.getLogger(__name__)
    try:
        return await _audit_trail_inner(meeting_id, current_user, _logger)
    except HTTPException:
        raise
    except Exception as _top_err:
        _logger.error(f"[AUDIT] UNHANDLED 500 meeting={meeting_id}: {_top_err}\n{_tb.format_exc()}")
        return {"events": []}


async def _audit_trail_inner(meeting_id: str, current_user: dict, _logger):
    org_id = current_user.get("org_id", "")
    _logger.info(f"[AUDIT] start meeting={meeting_id} org={org_id!r}")

    # ── Helpers (defined once, used in the assembly step below) ─────────────
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

    def _normalize_rec_events(raw):
        result = []
        for item in _jlist(raw):
            if isinstance(item, dict):
                result.append(item)
            elif isinstance(item, str):
                try:
                    parsed = json.loads(item)
                    if isinstance(parsed, dict): result.append(parsed)
                    elif isinstance(parsed, list): result.extend(e for e in parsed if isinstance(e, dict))
                except Exception: pass
            elif isinstance(item, list):
                result.extend(e for e in item if isinstance(e, dict))
        return result

    # ── ALL database work in ONE connection = one RLS round-trip ─────────────
    # Previously this opened 8+ separate connections (one per query), each
    # requiring a Supabase RLS context setup (~500 ms each → 4-8 s total).
    # Now: one connection, all queries run sequentially on it.
    try:
        async with database.with_org(org_id) as conn:
            # 1. Meeting row — all columns in one query (was two separate queries)
            m_row = await conn.fetchrow(
                "SELECT id, org_id, title, created_at, created_by_name, created_by, shared_with, "
                "transcript_id, analysis_id, recording_events, attendees, sign_off_record "
                "FROM meetings WHERE id=$1 AND org_id=$2", meeting_id, org_id
            )
            if not m_row:
                _logger.warning(f"[AUDIT] meeting NOT FOUND id={meeting_id} org={org_id!r}")
                raise HTTPException(status_code=404, detail="Meeting not found")
            meeting = dict(m_row)
            await _check_meeting_access(
                {**meeting, "attendees": _jlist(meeting.get("attendees")), "shared_with": _jlist(meeting.get("shared_with"))},
                current_user, org_id,
            )
            _logger.info(f"[AUDIT] meeting ok tid={meeting.get('transcript_id')!r} aid={meeting.get('analysis_id')!r}")

            # 2. Transcript timestamp
            t_row = None
            if meeting.get("transcript_id"):
                t_row = await conn.fetchrow("SELECT created_at FROM transcripts WHERE id=$1", meeting["transcript_id"])

            # 3. Analysis timestamp
            a_row = None
            if meeting.get("analysis_id"):
                a_row = await conn.fetchrow("SELECT created_at FROM analyses WHERE id=$1", meeting["analysis_id"])

            # 4. Batch user lookup for recording events — was N+1, now 1 query
            rec_events = _normalize_rec_events(meeting.get("recording_events"))
            rec_user_ids = list({ev.get("user_id") for ev in rec_events if ev.get("user_id")})
            rec_users = {}
            if rec_user_ids:
                try:
                    user_rows = await conn.fetch(
                        "SELECT id, name FROM users WHERE id = ANY($1::uuid[])", rec_user_ids
                    )
                    rec_users = {r["id"]: r["name"] for r in user_rows}
                except Exception:
                    pass

            # 5. Review edits
            try:
                edit_rows = await conn.fetch(
                    "SELECT action, timestamp, user_name, detail FROM review_edits "
                    "WHERE meeting_id=$1 ORDER BY timestamp ASC", meeting_id
                )
            except Exception:
                edit_rows = []

            # 6. Comments
            try:
                comment_rows = await conn.fetch(
                    "SELECT text, user_name, created_at FROM reviewer_comments "
                    "WHERE meeting_id=$1 ORDER BY created_at ASC", meeting_id
                )
            except Exception:
                comment_rows = []

            # 7. Audit logs
            try:
                log_rows = await conn.fetch(
                    "SELECT action, timestamp, user_name, detail FROM audit_logs "
                    "WHERE meeting_id=$1 ORDER BY timestamp ASC", meeting_id
                )
                _logger.info(f"[AUDIT] audit_logs rows={len(log_rows)} meeting={meeting_id}")
            except Exception as e:
                _logger.warning(f"[AUDIT] audit_logs fetch FAILED meeting={meeting_id}: {e}")
                log_rows = []

    except HTTPException:
        raise
    except Exception as e:
        _logger.error(f"[AUDIT] DB fetch FAILED meeting={meeting_id}: {e}")
        return {"events": []}

    # ── Assemble events in memory (no more DB calls below this line) ─────────
    events = []

    if meeting.get("created_at"):
        events.append({"type": "meeting_created", "label": "Meeting created",
                       "actor": meeting.get("created_by_name", "Unknown"),
                       "timestamp": meeting["created_at"], "detail": meeting.get("title", "")})

    label_map_rec = {"notice_acknowledged": "Recording notice acknowledged", "started": "Recording started",
                     "paused": "Recording paused", "resumed": "Recording resumed", "stopped": "Recording stopped"}
    for ev in rec_events:
        ev_type = ev.get("type") or ev.get("event_type", "unknown")
        actor = rec_users.get(ev.get("user_id", ""), ev.get("user_name", "System"))
        events.append({"type": f"recording_{ev_type}", "label": label_map_rec.get(ev_type, f"Recording {ev_type}"),
                       "actor": actor, "timestamp": ev.get("timestamp", ""), "detail": None})

    if t_row and t_row["created_at"]:
        events.append({"type": "transcribed", "label": "Audio transcribed", "actor": "1two.one",
                       "timestamp": t_row["created_at"], "detail": None})

    if a_row and a_row["created_at"]:
        events.append({"type": "analyzed", "label": "AI analysis completed", "actor": "1two.one",
                       "timestamp": a_row["created_at"], "detail": None})

    label_map_edit = {"summary": "Summary edited", "actions": "Action items updated",
                      "evidence": "Evidence item updated", "transcript_anonymise": "Transcript anonymised (manual)",
                      "evidence_rescan": "Evidence re-scanned", "post_signoff_evidence_edit": "Evidence edited after sign-off",
                      "risk": "Risk item updated", "action_completion": "Action item updated",
                      "summary_regenerated": "Summary regenerated (AI)"}
    for edit in edit_rows:
        edit = dict(edit)
        edit_type = edit.get("action", "unknown")
        events.append({"type": f"edit_{edit_type}", "label": label_map_edit.get(edit_type, f"'{edit_type}' edited"),
                       "actor": edit.get("user_name", "Unknown"), "timestamp": edit.get("timestamp", ""),
                       "detail": edit.get("detail"), "flagged": edit_type == "post_signoff_evidence_edit"})

    for a in _jlist(meeting.get("attendees")):
        if a.get("reviewed") and a.get("reviewed_at"):
            events.append({"type": "mark_reviewed", "label": "Marked as reviewed",
                           "actor": a.get("name", "Unknown"), "timestamp": a["reviewed_at"], "detail": None})

    sign_off = _jobj(meeting.get("sign_off_record"))
    if sign_off:
        events.append({"type": "signed_off", "label": "Meeting signed off",
                       "actor": sign_off.get("signed_by_name", "Unknown"),
                       "timestamp": sign_off.get("signed_at", ""), "detail": None})

    for c in comment_rows:
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
                       "meeting_shared": "Meeting shared with reviewer",
                       "recording_started": "Recording started",
                       "recording_stopped": "Recording stopped",
                       "recording_paused": "Recording paused",
                       "recording_resumed": "Recording resumed",
                       "action_status_changed": "Action item updated",
                       "learning_need_status_changed": "Learning need updated",
                       "achievement_acknowledged": "Achievement acknowledged",
                       "pdf_exported": "Report PDF exported",
                       "transcript_exported": "Transcript PDF exported",
                       "meeting_backdated": "Meeting date flagged"}
    for log in log_rows:
        log = dict(log)
        action = log.get("action", "unknown")
        events.append({"type": action, "label": label_map_audit.get(action, action.replace("_", " ").title()),
                       "actor": log.get("user_name", "System"), "timestamp": log.get("timestamp", ""),
                       "detail": log.get("detail"), "flagged": action == "meeting_backdated"})

    if (meeting.get("audio_deletion_status") == "deleted") and meeting.get("audio_deleted_at"):
        events.append({"type": "audio_deleted", "label": "Raw audio deleted (GDPR)", "actor": "System",
                       "timestamp": meeting["audio_deleted_at"], "detail": "Audio file removed after sign-off grace period"})

    events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)
    _logger.info(f"[AUDIT] returning {len(events)} events for meeting={meeting_id}")
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

    # SEC-003: Validate all recipients are active members of the org — prevents
    # using the platform to relay branded emails to arbitrary external addresses.
    async with database.with_admin() as conn:
        org_user_rows = await conn.fetch(
            "SELECT email FROM users WHERE org_id=$1 AND is_active=TRUE", org_id
        )
    allowed_emails = {r["email"].lower() for r in org_user_rows}
    invalid = [r for r in data.recipients if r.lower() not in allowed_emails]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail="All recipients must be active members of your organisation",
        )

    async with database.with_org(org_id) as conn:
        m_row = await conn.fetchrow(
            "SELECT title, date, status, attendees, shared_with, created_by FROM meetings WHERE id=$1 AND org_id=$2",
            meeting_id, org_id,
        )
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    await _check_meeting_access(
        {"attendees": _ensure_list(m_row["attendees"]), "shared_with": _ensure_list(m_row["shared_with"]), "created_by": m_row["created_by"]},
        current_user, org_id,
    )
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

    import html as _html
    html = f"""<html><body style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
<h2 style="color: #1E3A8A;">Supervision Meeting Report</h2>
<p><strong>Meeting:</strong> {_html.escape(str(m_row['title'] or ''))}</p>
<p><strong>Date:</strong> {friendly_date}</p>
<p><strong>Status:</strong> Signed Off</p>
<p>{_html.escape(str(data.message or 'Please review the meeting report linked below.'))}</p>
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
        m_row = await conn.fetchrow(
            "SELECT title, date, status, transcript_id, analysis_id, pii_redactions, attendees, shared_with, "
            "created_by, sign_off_manager_id, sign_off_manager_name, sign_off_record FROM meetings WHERE id=$1 AND org_id=$2",
            meeting_id, org_id,
        )
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = _parse_meeting_row(dict(m_row))
    await _check_meeting_access(meeting, current_user, org_id)
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
            a_row = await conn.fetchrow(
                "SELECT summary, edited_summary, achievements, actions, learning_needs, risks, "
                "cqc_mappings, care_cert_mappings, custom_mappings FROM analyses WHERE id=$1",
                meeting["analysis_id"],
            )
        if a_row:
            analysis = _parse_analysis_row(dict(a_row))

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

    # SEC-PII-001: attendee/manager names are printed in the PDF metadata
    # table, so redact them the same as the transcript body/analysis
    # (unconditionally — this mirrors speaker_text/analysis above, not the
    # privileged-only exception which applies solely to the raw transcript).
    pdf_meeting = meeting
    if redactions:
        pdf_meeting = dict(meeting)
        pdf_meeting["attendees"] = _apply_redactions_deep(meeting.get("attendees") or [], redactions)
        if meeting.get("sign_off_manager_name"):
            pdf_meeting["sign_off_manager_name"] = _apply_redactions_to_text(meeting["sign_off_manager_name"], redactions)
        if meeting.get("sign_off_record"):
            pdf_meeting["sign_off_record"] = _apply_redactions_deep(meeting["sign_off_record"], redactions)

    pdf_bytes = await asyncio.to_thread(_generate_pdf, pdf_meeting, analysis, transcript_text, speaker_text,
                              jurisdiction=org_jurisdiction, service_type=org_service_type)
    async with database.with_org(org_id) as conn:
        await _audit(conn, meeting_id, org_id, "pdf_exported", current_user["id"], current_user.get("name", ""),
                    "Includes transcript" if include_transcript else "Summary only")
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
    elif jurisdiction == "ofsted":
        if service_type == "early_years":
            reg_section_label = "EYFS Safeguarding & Welfare Evidence"
            cert_section_label = "EYFS Learning & Development Evidence"
        elif service_type == "childrens_home":
            reg_section_label = "Children's Homes Quality Standards Evidence"
            cert_section_label = "L3 Residential Childcare Diploma Evidence"
        else:
            reg_section_label = "Ofsted EIF Evidence"
            cert_section_label = "Teachers' Standards Evidence"
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
        "possible_evidence": colors.HexColor("#D97706"),
        "needs_review": colors.HexColor("#D97706"),       # legacy
        "not_enough_evidence": colors.HexColor("#D97706"), # legacy
    }

    title_style = ParagraphStyle("Title", fontName="Helvetica-Bold", fontSize=18, textColor=NAVY, spaceAfter=4)
    body_style = ParagraphStyle("Body", fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#374151"), spaceAfter=3, leading=13)
    small_style = ParagraphStyle("Small", fontName="Helvetica", fontSize=8, textColor=MID_GRAY, spaceAfter=2, leading=11)
    mono_style = ParagraphStyle("Mono", fontName="Courier", fontSize=8, textColor=colors.HexColor("#374151"), leading=12, spaceAfter=4)

    def e(t): return _xe(str(t or ""))

    def fmt_uk(raw, with_time=False):
        if not raw:
            return "—"
        try:
            d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return d.strftime("%d/%m/%Y %H:%M") if with_time else d.strftime("%d/%m/%Y")
        except Exception:
            return str(raw)

    def section_header(title, bg=NAVY):
        data = [[Paragraph(f'<font color="white"><b>{title}</b></font>', ParagraphStyle("SH", fontName="Helvetica-Bold", fontSize=10, textColor=colors.white))]]
        t = Table(data, colWidths=[170*mm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
        return t

    def evidence_card(ref, name, badge_text, evidence_summary, excerpt, confidence, bg):
        conf_label = {
            "likely_evidence": "Likely Evidence",
            "possible_evidence": "Possible Evidence",
            "needs_review": "Possible Evidence",          # legacy
            "not_enough_evidence": "Possible Evidence",   # legacy
        }.get(confidence, confidence)
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
        ["Date", fmt_uk(meeting.get("date")), "Status", (meeting.get("status") or "—").replace("_", " ").title()],
        ["Manager", meeting.get("sign_off_manager_name", "—"), "Signed off by", sign_off.get("signed_by_name", "—")],
        ["Attendees", ", ".join([a.get("name", "") for a in (meeting.get("attendees") or [])]), "Signed at", fmt_uk(sign_off.get("signed_at"), with_time=True)],
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

    achievements = analysis.get("achievements") or []
    if achievements:
        EMERALD_HDR = colors.HexColor("#065F46")
        EMERALD_BG  = colors.HexColor("#F0FDF4")
        story.append(Spacer(1, 4*mm))
        story.append(section_header("Achievements", bg=EMERALD_HDR))
        story.append(Spacer(1, 2*mm))
        ach_style = ParagraphStyle("Ach", fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#374151"), spaceAfter=3, leading=13, leftIndent=12, bulletIndent=0)
        for ach in achievements:
            desc = ach.get("description", "")
            if desc:
                row = [[Paragraph(f"\u2605  {e(desc)}", ach_style)]]
                ach_t = Table(row, colWidths=[170*mm])
                ach_t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), EMERALD_BG),
                    ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#A7F3D0")),
                ]))
                story.append(ach_t)
                story.append(Spacer(1, 1.5*mm))

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
            mark = "\u2713" if completed else "\u2717"
            action_rows.append([Paragraph(str(i), st), Paragraph(e(a.get("text", "")), st), Paragraph(e(a.get("assigned_to") or "\u2014"), st), Paragraph(e(a.get("due_date") or "\u2014"), st), Paragraph(mark, st)])
        at = Table(action_rows, colWidths=[8*mm, 88*mm, 36*mm, 22*mm, 16*mm])
        at.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(at)

    learning_needs = analysis.get("learning_needs") or []
    if learning_needs:
        story.append(Spacer(1, 4*mm))
        story.append(section_header("Learning Needs", bg=colors.HexColor("#0F766E")))
        story.append(Spacer(1, 2*mm))
        cell_style = ParagraphStyle("Cell", fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#374151"), leading=12)
        done_style = ParagraphStyle("Done", fontName="Helvetica", fontSize=9, textColor=MID_GRAY, leading=12)
        hdr_style = ParagraphStyle("Hdr", fontName="Helvetica-Bold", fontSize=9, textColor=colors.white, leading=12)
        ln_rows = [[Paragraph("#", hdr_style), Paragraph("Learning Need", hdr_style), Paragraph("Assigned To", hdr_style), Paragraph("Due Date", hdr_style), Paragraph("Done", hdr_style)]]
        for i, ln in enumerate(learning_needs, 1):
            completed = ln.get("completed", False)
            st = done_style if completed else cell_style
            mark = "\u2713" if completed else "\u2717"
            ln_rows.append([Paragraph(str(i), st), Paragraph(e(ln.get("text", "")), st), Paragraph(e(ln.get("assigned_to") or "\u2014"), st), Paragraph(e(ln.get("due_date") or "\u2014"), st), Paragraph(mark, st)])
        lnt = Table(ln_rows, colWidths=[8*mm, 88*mm, 36*mm, 22*mm, 16*mm])
        lnt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F766E")), ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(lnt)

    risks = analysis.get("risks") or []
    if risks:
        story.append(Spacer(1, 4*mm))
        story.append(section_header("Areas for Attention", bg=colors.HexColor("#7F1D1D")))
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
                ts = _re.match(r'^(\[[\d:]+\]\s*)(.*)', line)
                prefix, rest = (ts.group(1), ts.group(2)) if ts else ("", line)
                m = _re.match(r'^([^:]{1,50}):\s*(.+)', rest)
                if m:
                    turns.append([m.group(1).strip(), (prefix + m.group(2).strip()).strip()])
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
        m_row = await conn.fetchrow(
            "SELECT title, date, status, transcript_id, pii_redactions, attendees, shared_with, "
            "created_by, sign_off_manager_id, sign_off_manager_name FROM meetings WHERE id=$1 AND org_id=$2",
            meeting_id, org_id,
        )
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = _parse_meeting_row(dict(m_row))
    await _check_meeting_access(meeting, current_user, org_id)
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

    # SEC-PII-001: attendee/manager names are printed in the PDF header, so
    # redact them the same as the transcript body.
    pdf_meeting = meeting
    if redactions:
        pdf_meeting = dict(meeting)
        pdf_meeting["attendees"] = _apply_redactions_deep(meeting.get("attendees") or [], redactions)
        if meeting.get("sign_off_manager_name"):
            pdf_meeting["sign_off_manager_name"] = _apply_redactions_to_text(meeting["sign_off_manager_name"], redactions)

    pdf_bytes = await asyncio.to_thread(_generate_transcript_pdf, pdf_meeting, speaker_text, transcript_text)
    async with database.with_org(org_id) as conn:
        await _audit(conn, meeting_id, org_id, "transcript_exported", current_user["id"], current_user.get("name", ""), "")
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

    def fmt_uk(raw, with_time=False):
        if not raw:
            return "—"
        try:
            d = _dt.fromisoformat(str(raw).replace("Z", "+00:00"))
            return d.strftime("%d/%m/%Y %H:%M") if with_time else d.strftime("%d/%m/%Y")
        except Exception:
            return str(raw)

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

    meta_parts = [f"Date: {fmt_uk(meeting.get('date'))}", f"Manager: {e(meeting.get('sign_off_manager_name', '—'))}"]
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
            ts = _re.match(r'^(\[[\d:]+\]\s*)(.*)', line)
            prefix, rest = (ts.group(1), ts.group(2)) if ts else ("", line)
            m = _re.match(r'^([^:]{1,50}):\s*(.+)', rest)
            if m:
                turns.append([m.group(1).strip(), (prefix + m.group(2).strip()).strip()])
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
        m_row = await conn.fetchrow(
            "SELECT reopen_requested, attendees, reopen_requested_by, reopen_reason FROM meetings WHERE id=$1 AND org_id=$2",
            meeting_id, org_id,
        )
    if not m_row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = dict(m_row)
    if not meeting.get("reopen_requested"):
        raise HTTPException(status_code=400, detail="No re-open request is pending for this meeting")

    user_id = current_user.get("id", "")
    attendee_ids = [a.get("user_id", "") for a in _ensure_list(meeting.get("attendees"))]
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
    _admin_stats_cache.pop(org_id, None)
    return {"message": "Re-open approved — report is now unlocked for editing"}
