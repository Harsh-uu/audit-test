"""HR-system webhook integration (MVP).

Pushes a limited-field payload (summary, achievements, actions, learning
needs + which staff member it's about) to an org's configured URL whenever
a meeting is signed off. Deliberately excludes transcript/audio/risk/CQC
mapping content — only the 4 fields the user explicitly asked to share.
Fire-once, best-effort: every attempt (success or failure) is logged to
webhook_deliveries so an admin can see failures and manually Resend from
Settings > Integrations.
"""
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx

import database

logger = logging.getLogger(__name__)


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


def sign_payload(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def build_payload(meeting: dict, analysis: dict, signed_off_at: str) -> dict:
    staff = [
        {"name": a.get("name", ""), "email": a.get("email", "")}
        for a in _ensure_list(meeting.get("attendees"))
        if a.get("role") not in ("manager", "admin")
    ]
    return {
        "event": "meeting.signed_off",
        "meeting_id": meeting.get("id", ""),
        "meeting_title": meeting.get("title", ""),
        "meeting_date": meeting.get("date", ""),
        "signed_off_at": signed_off_at,
        "staff": staff,
        "summary": analysis.get("edited_summary") or analysis.get("summary") or "",
        "achievements": [a.get("text", "") for a in _ensure_list(analysis.get("achievements"))],
        "actions": [
            {
                "text": a.get("text", ""),
                "type": a.get("action_type", "task"),
                "due_date": a.get("due_date"),
                "trigger": a.get("trigger"),
                "completed": bool(a.get("completed")),
            }
            for a in _ensure_list(analysis.get("actions"))
        ],
        "learning_needs": [ln.get("text", "") for ln in _ensure_list(analysis.get("learning_needs"))],
    }


async def _send_and_log(org_id: str, meeting_id: str, url: str, secret: str, payload: dict):
    body = json.dumps(payload, default=str).encode()
    signature = sign_payload(secret, body)
    success, http_status, error_message = False, None, None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url, content=body,
                headers={"Content-Type": "application/json", "X-Webhook-Signature": signature},
            )
        http_status = resp.status_code
        success = 200 <= resp.status_code < 300
        if not success:
            error_message = f"HTTP {resp.status_code}: {resp.text[:300]}"
    except Exception as e:
        error_message = str(e)[:300]

    async with database.with_org(org_id) as conn:
        await conn.execute(
            """INSERT INTO webhook_deliveries (org_id, meeting_id, event, payload, success, http_status, error_message)
               VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7)""",
            org_id, meeting_id, payload.get("event", "meeting.signed_off"),
            payload, success, http_status, error_message,
        )


async def deliver_meeting_signed_off(meeting_id: str, org_id: str):
    """Background task fired from the sign-off endpoint. Never raises —
    a webhook failure must not affect the sign-off flow itself."""
    try:
        async with database.with_org(org_id) as conn:
            cfg = await conn.fetchrow("SELECT url, secret, enabled FROM webhook_configs WHERE org_id=$1", org_id)
        if not cfg or not cfg["enabled"] or not cfg["url"]:
            return

        async with database.with_org(org_id) as conn:
            m_row = await conn.fetchrow(
                "SELECT id, title, date, attendees, analysis_id, sign_off_record FROM meetings WHERE id=$1", meeting_id
            )
        if not m_row:
            return
        meeting = dict(m_row)
        sign_off_record = _ensure_dict(meeting.get("sign_off_record"))
        signed_off_at = sign_off_record.get("signed_at") or datetime.now(timezone.utc).isoformat()

        analysis = {}
        if meeting.get("analysis_id"):
            async with database.with_org(org_id) as conn:
                a_row = await conn.fetchrow(
                    "SELECT summary, edited_summary, achievements, actions, learning_needs FROM analyses WHERE id=$1",
                    meeting["analysis_id"],
                )
            if a_row:
                analysis = dict(a_row)

        payload = build_payload(meeting, analysis, signed_off_at)
        await _send_and_log(org_id, meeting_id, cfg["url"], cfg["secret"], payload)
    except Exception:
        logger.exception("Webhook delivery failed for meeting %s", meeting_id)


async def resend_delivery(delivery_id: str, org_id: str):
    """Manual Resend from Settings — replays the exact original payload
    (not a fresh re-fetch), so what the admin sees in the log is what's sent."""
    async with database.with_org(org_id) as conn:
        d_row = await conn.fetchrow("SELECT meeting_id, payload FROM webhook_deliveries WHERE id=$1 AND org_id=$2", delivery_id, org_id)
        cfg = await conn.fetchrow("SELECT url, secret, enabled FROM webhook_configs WHERE org_id=$1", org_id)
    if not d_row or not cfg or not cfg["enabled"] or not cfg["url"]:
        return
    payload = _ensure_dict(d_row["payload"])
    await _send_and_log(org_id, d_row["meeting_id"], cfg["url"], cfg["secret"], payload)
