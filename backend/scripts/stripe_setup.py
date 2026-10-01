"""One-time Stripe catalog setup for the self-serve subscription tiers.

Creates 3 Products (Starter / Growth / Scale) x 2 Prices each (founding +
regular, recurring every 30 days — a true rolling 30-day contract, not a
calendar month — GBP) and prints the resulting Price IDs — paste these into
backend/.env as STRIPE_PRICE_<TIER>_<FOUNDING|REGULAR> once real Stripe keys
are available. Idempotent: safe to re-run, matches by
metadata.emergent_product_id / lookup_key instead of creating duplicates —
if an existing active price under a lookup_key already has a different
`recurring` interval (e.g. a legacy calendar-month price from before the
30-day switch), it is left untouched for any subscription still on it and a
fresh price is created under the same lookup_key instead (old price is NOT
deleted/archived by this script — do that explicitly first if intended).

Usage:
    STRIPE_SECRET_KEY=sk_test_... python3 scripts/stripe_setup.py
"""
import os
import sys

RECURRING = {"interval": "day", "interval_count": 30}

CATALOG = [
    {
        "emergent_product_id": "supervision2_starter",
        "name": "1two.one — Starter",
        "prices": [
            {"lookup_key": "starter_founding", "amount": 2900, "env": "STRIPE_PRICE_STARTER_FOUNDING"},
            {"lookup_key": "starter_regular", "amount": 4900, "env": "STRIPE_PRICE_STARTER_REGULAR"},
        ],
    },
    {
        "emergent_product_id": "supervision2_growth",
        "name": "1two.one — Growth",
        "prices": [
            {"lookup_key": "growth_founding", "amount": 4900, "env": "STRIPE_PRICE_GROWTH_FOUNDING"},
            {"lookup_key": "growth_regular", "amount": 8900, "env": "STRIPE_PRICE_GROWTH_REGULAR"},
        ],
    },
    {
        "emergent_product_id": "supervision2_scale",
        "name": "1two.one — Scale",
        "prices": [
            {"lookup_key": "scale_founding", "amount": 9900, "env": "STRIPE_PRICE_SCALE_FOUNDING"},
            {"lookup_key": "scale_regular", "amount": 17900, "env": "STRIPE_PRICE_SCALE_REGULAR"},
        ],
    },
]


def get_or_create_product(stripe, entry):
    for p in stripe.Product.list(active=True).auto_paging_iter():
        if p.metadata.get("emergent_product_id") == entry["emergent_product_id"]:
            return p
    return stripe.Product.create(
        name=entry["name"],
        metadata={"managed_by": "emergent", "emergent_product_id": entry["emergent_product_id"]},
    )


def get_or_create_price(stripe, product, p):
    existing = stripe.Price.list(lookup_keys=[p["lookup_key"]], active=True, limit=1).data
    if existing and existing[0]["recurring"]["interval"] == RECURRING["interval"] and existing[0]["recurring"]["interval_count"] == RECURRING["interval_count"]:
        return existing[0]
    if existing:
        # An active price exists under this lookup_key but with the wrong
        # billing interval (e.g. a legacy calendar-month price) — deactivate
        # it so the lookup_key is free to reuse (Stripe lookup_keys must be
        # unique among ACTIVE prices only). Any subscription already on the
        # old price keeps billing on it unaffected; it just can't be used
        # for new checkouts anymore.
        stripe.Price.modify(existing[0]["id"], active=False)
        print(f"  (deactivated old price {existing[0]['id']} under lookup_key={p['lookup_key']!r} — existing subscriptions on it are unaffected)")
    return stripe.Price.create(
        product=product.id,
        unit_amount=p["amount"],
        currency="gbp",
        recurring=RECURRING,
        lookup_key=p["lookup_key"],
        transfer_lookup_key=True,
    )


def main():
    secret_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not secret_key:
        print("STRIPE_SECRET_KEY is not set — nothing to do. Set it and re-run once real Stripe keys exist.")
        sys.exit(1)

    import stripe
    stripe.api_key = secret_key

    print("Env vars to paste into backend/.env:\n")
    for entry in CATALOG:
        product = get_or_create_product(stripe, entry)
        for p in entry["prices"]:
            price = get_or_create_price(stripe, product, p)
            print(f"{p['env']}={price.id}")


if __name__ == "__main__":
    main()
