"""Cron endpoints for the self-serve Stripe signup flow, invoked by the
Emergent platform scheduler per .emergent/crons.yml:
  - founding-reminder:    daily, month-11 founding-price-increase email
  - provisioning-retry:   every 15-30 min, retries any org/invite creation
                          that failed after Stripe payment already succeeded
  - abandoned-signup:     daily, alerts Super Admin about paid-but-never-
                          onboarded checkout sessions older than 48h

Each handler authenticates via WEBHOOK_CRON_SECRET, acks 2xx immediately,
and hands the real work to a BackgroundTask.
"""
import os
import hmac
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks

import database
from utils.stripe_helpers import TIER_CONFIG
from utils.org_provisioning import create_org_core, invite_user_core, send_invite_email, validate_jurisdiction_service_type
from utils.billing_emails import send_founding_reminder_email, notify_super_admin

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_PROVISIONING_ATTEMPTS = 5


def _check_cron_secret(request: Request):
    secret = os.environ.get("WEBHOOK_CRON_SECRET", "")
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else ""
    if not secret or not token or not hmac.compare_digest(token, secret):
        raise HTTPException(status_code=401, detail="Unauthorized")


# ── Daily: founding-member month-11 reminder ────────────────────────────────

async def _founding_reminder_sweep():
    now = datetime.now(timezone.utc)
    window_start = now + timedelta(days=29)
    window_end = now + timedelta(days=30)
    async with database.with_admin() as conn:
        rows = await conn.fetch(
            """SELECT ps.id, ps.founding_price_lock_until, ps.tier, o.name AS org_name,
                      u.email AS admin_email, u.name AS admin_name
               FROM pending_signups ps
               JOIN organisations o ON o.id = ps.org_id
               JOIN users u ON u.org_id = o.id AND u.role = 'admin'
               WHERE ps.founding_price_lock_until BETWEEN $1 AND $2 AND ps.reminder_sent_at IS NULL""",
            window_start, window_end,
        )
        for r in rows:
            sent = await send_founding_reminder_email(
                r["admin_email"], r["admin_name"], r["org_name"], r["tier"], r["founding_price_lock_until"],
            )
            if sent:
                await conn.execute("UPDATE pending_signups SET reminder_sent_at=now() WHERE id=$1", r["id"])


@router.post("/cron/founding-reminder")
async def founding_reminder_cron(request: Request, background_tasks: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    _check_cron_secret(request)
    background_tasks.add_task(_founding_reminder_sweep)
    return {"status": "accepted"}


# ── Every 15-30 min: provisioning retry ─────────────────────────────────────

async def _retry_one_provisioning_failure(pf: dict):
    org = None
    invite_result = None
    payload = pf["payload"] or {}
    async with database.with_admin() as conn:
        signup = await conn.fetchrow("SELECT * FROM pending_signups WHERE id=$1 FOR UPDATE", pf["pending_signup_id"])
        if not signup or signup["org_id"]:
            await conn.execute("UPDATE provisioning_failures SET resolved=TRUE WHERE id=$1", pf["id"])
            return
        try:
            jurisdiction, service_type = validate_jurisdiction_service_type(
                payload.get("jurisdiction", "england"), payload.get("service_type"),
            )
            org = await create_org_core(
                conn, name=payload.get("organisation_name", "Unnamed Org"), jurisdiction=jurisdiction, service_type=service_type,
                pricing_tier=signup["tier"], included_hours_monthly=TIER_CONFIG.get(signup["tier"], {}).get("included_hours"),
                is_trial=False, stripe_customer_id=signup["stripe_customer_id"], stripe_subscription_id=signup["stripe_subscription_id"],
                stripe_subscription_status="active", is_founding_member=bool(signup["is_founding"]),
                founding_price_lock_until=signup["founding_price_lock_until"], on_slug_conflict="suffix",
            )
            invite_result = await invite_user_core(
                conn, org_id=org["id"], org_name=org["name"], email=payload.get("email", ""), name=payload.get("name", ""),
            )
            await conn.execute(
                "UPDATE pending_signups SET org_id=$1, status='consumed', updated_at=now() WHERE id=$2",
                org["id"], signup["id"],
            )
            await conn.execute("UPDATE provisioning_failures SET resolved=TRUE, last_attempted_at=now() WHERE id=$1", pf["id"])
        except Exception as e:
            attempts = pf["attempt_count"] + 1
            await conn.execute(
                "UPDATE provisioning_failures SET attempt_count=$1, last_attempted_at=now(), error=$2 WHERE id=$3",
                attempts, str(e), pf["id"],
            )
            if attempts >= MAX_PROVISIONING_ATTEMPTS:
                await notify_super_admin(
                    f"Provisioning permanently failed for pending_signup {pf['pending_signup_id']} "
                    f"after {attempts} attempts: {e}",
                )
            return

    if org and invite_result:
        await send_invite_email(payload.get("email", ""), payload.get("name", ""), org["name"], invite_result["invite_link"])


async def _provisioning_retry_sweep():
    async with database.with_admin() as conn:
        pf_rows = await conn.fetch(
            "SELECT * FROM provisioning_failures WHERE resolved=FALSE AND attempt_count < $1 ORDER BY created_at ASC LIMIT 20",
            MAX_PROVISIONING_ATTEMPTS,
        )
    for pf in pf_rows:
        await _retry_one_provisioning_failure(dict(pf))


@router.post("/cron/provisioning-retry")
async def provisioning_retry_cron(request: Request, background_tasks: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    _check_cron_secret(request)
    background_tasks.add_task(_provisioning_retry_sweep)
    return {"status": "accepted"}


# ── Daily: abandoned-signup sweep ───────────────────────────────────────────

async def _abandoned_signup_sweep():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    async with database.with_admin() as conn:
        rows = await conn.fetch(
            "SELECT * FROM pending_signups WHERE status='paid' AND org_id IS NULL AND created_at < $1 AND alerted_at IS NULL",
            cutoff,
        )
        for r in rows:
            await notify_super_admin(
                f"Abandoned signup: tier={r['tier']} stripe_customer_id={r['stripe_customer_id']} "
                f"checkout_session={r['stripe_checkout_session_id']} paid at {r['created_at']} "
                "but never completed onboarding (48h+)."
            )
            await conn.execute("UPDATE pending_signups SET alerted_at=now() WHERE id=$1", r["id"])


@router.post("/cron/abandoned-signup")
async def abandoned_signup_cron(request: Request, background_tasks: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    _check_cron_secret(request)
    background_tasks.add_task(_abandoned_signup_sweep)
    return {"status": "accepted"}
