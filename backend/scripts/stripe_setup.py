"""One-time Stripe catalog setup for the self-serve subscription tiers.

Creates 3 Products (Starter / Growth / Scale) x 2 Prices each (founding +
regular, recurring monthly, GBP) and prints the resulting Price IDs — paste
these into backend/.env as STRIPE_PRICE_<TIER>_<FOUNDING|REGULAR> once real
Stripe keys are available. Idempotent: safe to re-run, matches by
metadata.emergent_product_id / lookup_key instead of creating duplicates.

Usage:
    STRIPE_SECRET_KEY=sk_test_... python3 scripts/stripe_setup.py
"""
import os
import sys

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
    if existing:
        return existing[0]
    return stripe.Price.create(
        product=product.id,
        unit_amount=p["amount"],
        currency="gbp",
        recurring={"interval": "month"},
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
