"""Shared Stripe helpers for the public self-serve checkout flow
(routers/public_signup.py, routers/cron_jobs.py) — tier/price-id lookups
and the founding-price Subscription Schedule logic, kept in one place so
checkout-creation and webhook-consumption never read tier config from two
different sources.

Per the product spec: real Stripe Price IDs do not exist yet. Every lookup
here reads from os.environ and degrades to None/"not configured" rather
than raising at import time, so the rest of the app boots fine with these
env vars empty until real keys/price ids are supplied.
"""
import os
import logging
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta

logger = logging.getLogger(__name__)

TIER_CONFIG = {
    "starter": {"label": "Starter", "included_hours": 10, "founding_env": "STRIPE_PRICE_STARTER_FOUNDING", "regular_env": "STRIPE_PRICE_STARTER_REGULAR"},
    "growth":  {"label": "Growth",  "included_hours": 30, "founding_env": "STRIPE_PRICE_GROWTH_FOUNDING",  "regular_env": "STRIPE_PRICE_GROWTH_REGULAR"},
    "scale":   {"label": "Scale",   "included_hours": 70, "founding_env": "STRIPE_PRICE_SCALE_FOUNDING",   "regular_env": "STRIPE_PRICE_SCALE_REGULAR"},
}


def stripe_configured() -> bool:
    return bool(os.environ.get("STRIPE_SECRET_KEY"))


def get_stripe_module():
    """Lazily import + configure the stripe SDK. Deliberately not imported
    at module scope so this file itself never requires STRIPE_SECRET_KEY to
    exist just to be imported elsewhere in the app."""
    import stripe
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    return stripe


def get_price_id(tier: str, founding: bool):
    cfg = TIER_CONFIG.get(tier)
    if not cfg:
        return None
    env_key = cfg["founding_env"] if founding else cfg["regular_env"]
    return os.environ.get(env_key) or None


def tier_from_price_id(price_id: str):
    """Reverse lookup used by customer.subscription.updated to re-derive
    (tier, is_founding) from whichever price id the subscription now carries
    — covers a manual Stripe Dashboard price change, not just our own
    scheduled founding->regular flip."""
    if not price_id:
        return None, False
    for tier, cfg in TIER_CONFIG.items():
        if price_id == os.environ.get(cfg["founding_env"]):
            return tier, True
        if price_id == os.environ.get(cfg["regular_env"]):
            return tier, False
    return None, False


def create_founding_price_schedule(stripe, subscription_id: str, tier: str, founding_price_id: str):
    """Attach a 2-phase Subscription Schedule to a just-created subscription
    so the founding->regular price flip happens automatically in Stripe at
    the 12-month mark — no custom cron needed for the flip itself (the
    month-11 reminder EMAIL is a separate cron, see routers/cron_jobs.py)."""
    regular_price_id = get_price_id(tier, founding=False)
    if not regular_price_id:
        logger.warning("No regular price id configured for tier=%s — skipping founding->regular schedule", tier)
        return None
    schedule = stripe.SubscriptionSchedule.create(from_subscription=subscription_id)
    start_date = schedule["phases"][0]["start_date"]
    flip_date = int((datetime.fromtimestamp(start_date, tz=timezone.utc) + relativedelta(months=12)).timestamp())
    stripe.SubscriptionSchedule.modify(
        schedule["id"],
        phases=[
            {"items": [{"price": founding_price_id, "quantity": 1}], "start_date": start_date, "end_date": flip_date},
            {"items": [{"price": regular_price_id, "quantity": 1}]},
        ],
    )
    return schedule["id"]
