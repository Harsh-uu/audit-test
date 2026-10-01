"""Public, unauthenticated self-serve Stripe subscription checkout flow.

Flow: marketing site -> POST /api/public/checkout -> Stripe Checkout ->
GET /api/public/checkout/verify (on /onboard) -> POST
/api/public/onboarding/complete -> existing admin-invite email ->
/accept-invite (unchanged). Stripe webhooks land on POST /api/stripe/webhook
(separate router below, registered at the API root — not under /public).

Deliberately reuses utils/org_provisioning.py's create_org_core/
invite_admin_core so a self-serve org is structurally identical to a
manually-created one, and never touches/breaks the existing manual
Super Admin flows in routers/super_admin.py.
"""
import os
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr

import database
from utils.stripe_helpers import (
    TIER_CONFIG, stripe_configured, get_stripe_module, get_price_id,
    tier_from_price_id, create_founding_price_schedule,
)
from utils.org_provisioning import (
    create_org_core, invite_admin_core, send_invite_email,
    validate_jurisdiction_service_type,
)
from utils.billing_emails import send_payment_failed_email, notify_super_admin

logger = logging.getLogger(__name__)

router = APIRouter()          # mounted at /api/public
webhook_router = APIRouter()  # mounted at /api (no extra prefix)


# ── Shared idempotency + upsert helpers ─────────────────────────────────────

async def _mark_event_processed_or_skip(conn, event_id: str) -> bool:
    """Returns True if this is a genuinely new Stripe event id (caller should
    process it), False if we've already processed it (safe no-op replay)."""
    result = await conn.execute(
        "INSERT INTO stripe_events_processed (stripe_event_id) VALUES ($1) ON CONFLICT DO NOTHING",
        event_id,
    )
    return result == "INSERT 0 1"


async def _upsert_pending_signup_from_session(conn, session, stripe_mod=None) -> dict:
    """Idempotent — called from BOTH the webhook (checkout.session.completed)
    AND the /checkout/verify fallback path (webhook race). Whichever fires
    first wins the INSERT; the other is a no-op. Only the actual winner
    attaches the founding->regular Subscription Schedule (guarded by the
    INSERT's own RETURNING, not just ON CONFLICT, since schedule creation is
    a separate Stripe API call outside the DB statement)."""
    session_id = session["id"]
    metadata = session.get("metadata") or {}
    tier = metadata.get("tier")
    is_founding = metadata.get("is_founding") == "true"
    customer_id = session.get("customer")
    subscription_id = session.get("subscription")
    now = datetime.now(timezone.utc)
    lock_until = None
    if is_founding:
        from dateutil.relativedelta import relativedelta
        lock_until = now + relativedelta(months=12)

    row = await conn.fetchrow(
        """INSERT INTO pending_signups
           (stripe_checkout_session_id, stripe_customer_id, stripe_subscription_id,
            tier, is_founding, founding_price_lock_until, status)
           VALUES ($1,$2,$3,$4,$5,$6,'paid')
           ON CONFLICT (stripe_checkout_session_id) DO NOTHING
           RETURNING *""",
        session_id, customer_id, subscription_id, tier, is_founding, lock_until,
    )
    if row is None:
        row = await conn.fetchrow(
            "SELECT * FROM pending_signups WHERE stripe_checkout_session_id=$1", session_id,
        )
        return dict(row)

    if is_founding and subscription_id and tier:
        try:
            stripe = stripe_mod or get_stripe_module()
            founding_price_id = get_price_id(tier, founding=True)
            if founding_price_id:
                create_founding_price_schedule(stripe, subscription_id, tier, founding_price_id)
        except Exception:
            logger.exception("Failed to create founding-price Subscription Schedule for session %s", session_id)
    return dict(row)


# ── /api/public/checkout ─────────────────────────────────────────────────────

class PublicCheckoutRequest(BaseModel):
    tier: str


@router.post("/checkout")
async def create_public_checkout(data: PublicCheckoutRequest):
    tier = data.tier
    if tier not in TIER_CONFIG:
        raise HTTPException(status_code=400, detail=f"Invalid tier. Must be one of: {', '.join(TIER_CONFIG)}")
    if not stripe_configured():
        raise HTTPException(status_code=503, detail="Payments are not yet configured — please try again shortly.")
    price_id = get_price_id(tier, founding=True)
    if not price_id:
        raise HTTPException(status_code=503, detail=f"Pricing for '{tier}' is not yet configured.")

    stripe = get_stripe_module()
    frontend_url = os.environ.get("FRONTEND_URL", "")
    tax_enabled = os.environ.get("STRIPE_TAX_ENABLED", "false").lower() == "true"
    kwargs = dict(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        metadata={"tier": tier, "is_founding": "true"},
        success_url=f"{frontend_url}/onboard?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{frontend_url}/checkout-cancelled?tier={tier}",
    )
    if tax_enabled:
        kwargs["automatic_tax"] = {"enabled": True}
    try:
        session = stripe.checkout.Session.create(**kwargs)
    except Exception as e:
        logger.error("Stripe checkout session creation failed for tier=%s: %s", tier, e)
        raise HTTPException(status_code=502, detail="Could not start checkout — please try again.")
    return {"url": session.url}


# ── /api/public/checkout/verify ─────────────────────────────────────────────

@router.get("/checkout/verify")
async def verify_public_checkout(session_id: str):
    stripe_session = None
    if stripe_configured():
        try:
            stripe = get_stripe_module()
            stripe_session = stripe.checkout.Session.retrieve(session_id)
        except Exception:
            stripe_session = None

    async with database.with_admin() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM pending_signups WHERE stripe_checkout_session_id=$1", session_id,
        )
        if not row:
            if not stripe_session:
                raise HTTPException(status_code=404, detail="Checkout session not found.")
            if stripe_session.get("payment_status") != "paid":
                raise HTTPException(status_code=400, detail="Payment has not completed for this session.")
            row = await _upsert_pending_signup_from_session(
                conn, stripe_session, get_stripe_module() if stripe_configured() else None,
            )
        else:
            row = dict(row)

    if row.get("org_id"):
        return {"status": "already_used"}

    prefill_email = None
    if stripe_session:
        prefill_email = (stripe_session.get("customer_details") or {}).get("email")
    return {"status": "ok", "tier": row["tier"], "prefill_email": prefill_email, "founding": bool(row["is_founding"])}


# ── /api/public/onboarding/complete ─────────────────────────────────────────

class OnboardingCompleteRequest(BaseModel):
    session_id: str
    name: str
    email: EmailStr
    organisation_name: str
    jurisdiction: str
    service_type: Optional[str] = None


@router.post("/onboarding/complete")
async def complete_onboarding(data: OnboardingCompleteRequest):
    try:
        jurisdiction, service_type = validate_jurisdiction_service_type(data.jurisdiction, data.service_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    async with database.with_admin() as conn:
        # SELECT ... FOR UPDATE: prevents a double-submit (double-click, or a
        # retry racing the provisioning-retry cron) from creating two orgs
        # off a single Stripe payment.
        signup = await conn.fetchrow(
            "SELECT * FROM pending_signups WHERE stripe_checkout_session_id=$1 FOR UPDATE",
            data.session_id,
        )
        if not signup:
            raise HTTPException(status_code=404, detail="Checkout session not found — please restart checkout.")
        if signup["org_id"]:
            raise HTTPException(status_code=400, detail="This checkout link has already been used.")
        if signup["status"] != "paid":
            raise HTTPException(status_code=400, detail="Payment for this session has not completed yet.")

        tier = signup["tier"]
        tier_cfg = TIER_CONFIG.get(tier, {})
        org = None
        invite_result = None
        try:
            org = await create_org_core(
                conn, name=data.organisation_name, jurisdiction=jurisdiction, service_type=service_type,
                pricing_tier=tier, included_hours_monthly=tier_cfg.get("included_hours"),
                is_trial=False, stripe_customer_id=signup["stripe_customer_id"],
                stripe_subscription_id=signup["stripe_subscription_id"], stripe_subscription_status="active",
                is_founding_member=bool(signup["is_founding"]), founding_price_lock_until=signup["founding_price_lock_until"],
                on_slug_conflict="suffix",
            )
            invite_result = await invite_admin_core(
                conn, org_id=org["id"], org_name=org["name"], email=data.email, name=data.name,
            )
        except Exception as e:
            # Something failed AFTER Stripe already took payment (validation
            # error, DB hiccup, network blip — doesn't matter which) — never
            # tell the customer "your payment failed"; log for the retry cron.
            logger.error("Onboarding provisioning failed for session %s: %s", data.session_id, e)
            await conn.execute(
                "INSERT INTO provisioning_failures (pending_signup_id, error, payload) VALUES ($1,$2,$3)",
                signup["id"], str(e),
                {"name": data.name, "email": data.email, "organisation_name": data.organisation_name,
                 "jurisdiction": jurisdiction, "service_type": service_type},
            )
            return JSONResponse(status_code=202, content={
                "success": False, "provisioning": True,
                "message": "We're finishing setting up your account — you'll receive an email shortly.",
            })

        await conn.execute(
            "UPDATE pending_signups SET org_id=$1, status='consumed', updated_at=now() WHERE id=$2",
            org["id"], signup["id"],
        )

    email_sent = await send_invite_email(data.email, data.name, org["name"], invite_result["invite_link"])
    return {"success": True, "organisation_name": org["name"], "email_sent": email_sent}


# ── /api/stripe/webhook ──────────────────────────────────────────────────────

@webhook_router.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not webhook_secret or not stripe_configured():
        logger.error("Stripe webhook received but Stripe is not configured — rejecting.")
        raise HTTPException(status_code=503, detail="Webhook not configured")

    stripe = get_stripe_module()
    try:
        event = stripe.Webhook.construct_event(payload, sig, webhook_secret)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_id = event["id"]
    event_type = event["type"]
    obj = event["data"]["object"]

    async with database.with_admin() as conn:
        is_new = await _mark_event_processed_or_skip(conn, event_id)
        if not is_new:
            return {"status": "already_processed"}

        if event_type == "checkout.session.completed":
            await _upsert_pending_signup_from_session(conn, obj, stripe)

        elif event_type == "invoice.payment_failed":
            customer_id = obj.get("customer")
            subscription_id = obj.get("subscription")
            org = await conn.fetchrow(
                "SELECT id, name FROM organisations WHERE stripe_customer_id=$1 OR stripe_subscription_id=$2",
                customer_id, subscription_id,
            )
            if org:
                await conn.execute(
                    "UPDATE organisations SET stripe_subscription_status='past_due', updated_at=now() WHERE id=$1",
                    org["id"],
                )
                admin = await conn.fetchrow(
                    "SELECT email, name FROM users WHERE org_id=$1 AND role='admin' ORDER BY created_at ASC LIMIT 1",
                    org["id"],
                )
                if admin:
                    await send_payment_failed_email(admin["email"], admin["name"], org["name"])

        elif event_type == "customer.subscription.updated":
            subscription_id = obj.get("id")
            status = obj.get("status")
            # Stripe moved `current_period_end`/`current_period_start` off the
            # top-level Subscription object onto each subscription item (as
            # part of flexible/multi-item billing) — the object's own
            # top-level field is now always None. Fall back to the top-level
            # field only for safety in case an older API-version event ever
            # still carries it.
            price_id = None
            period_end = None
            try:
                first_item = obj["items"]["data"][0]
                price_id = first_item["price"]["id"]
                period_end = first_item.get("current_period_end")
            except (KeyError, IndexError, TypeError):
                pass
            if period_end is None:
                period_end = obj.get("current_period_end")
            tier, _is_founding = tier_from_price_id(price_id) if price_id else (None, False)
            updates = {"stripe_subscription_status": status}
            if period_end:
                updates["stripe_current_period_end"] = datetime.fromtimestamp(period_end, tz=timezone.utc).isoformat()
            if tier:
                updates["pricing_tier"] = tier
            set_clause = ", ".join(f"{k}=${i + 2}" for i, k in enumerate(updates.keys()))
            await conn.execute(
                f"UPDATE organisations SET {set_clause}, updated_at=now() WHERE stripe_subscription_id=$1",
                subscription_id, *updates.values(),
            )

        elif event_type == "customer.subscription.deleted":
            subscription_id = obj.get("id")
            org = await conn.fetchrow(
                "SELECT id, name FROM organisations WHERE stripe_subscription_id=$1", subscription_id,
            )
            if org:
                # Access is NOT revoked here — this app has no subscription-status
                # feature-gating today, so "canceled but before period end" already
                # behaves identically to "active" (nothing currently checks this field
                # to block access). Just record it + alert Super Admin for follow-up.
                await conn.execute(
                    "UPDATE organisations SET stripe_subscription_status='canceled', updated_at=now() WHERE id=$1",
                    org["id"],
                )
                await notify_super_admin(f"Subscription canceled for org '{org['name']}' (id={org['id']}).")

    return {"status": "ok"}
