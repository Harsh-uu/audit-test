"""Backend tests for the new Super Admin billing/usage features (iteration 143).

Covers:
- GET /api/super-admin/orgs enrichment (tier, stripe fields, usage rollups)
- GET /api/super-admin/orgs/{id}/usage-history (12-cycle history)
- PATCH /api/super-admin/orgs/{id}/billing (validation, clearing behaviour, tier auto-fill)
- Access control (non super_admin -> 403)
"""
import os
import asyncio
from datetime import datetime, timezone, timedelta

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

_be = dotenv_values("/app/backend/.env")
_fe = dotenv_values("/app/frontend/.env")
BASE = _fe["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = _be["DATABASE_URL"]


def _mfa_login(email: str, pw: str) -> requests.Session:
    async def _override():
        conn = await asyncpg.connect(DSN, ssl="require")
        h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
        exp = datetime.now(timezone.utc) + timedelta(minutes=10)
        await conn.execute(
            "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
            h, exp, email,
        )
        await conn.close()

    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": pw}, timeout=60)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text[:200]}"
    data = r.json()
    if data.get("requires_mfa"):
        asyncio.run(_override())
        r2 = s.post(
            f"{BASE}/auth/verify-mfa",
            json={"mfa_session": data["mfa_session"], "code": "123456"},
            timeout=60,
        )
        assert r2.status_code == 200, f"MFA verify failed {r2.status_code} {r2.text[:200]}"
    return s


@pytest.fixture(scope="module")
def sa_session():
    return _mfa_login("superadmin@1two.one", "TestPass123!")


@pytest.fixture(scope="module")
def admin_session():
    return _mfa_login("admin@supervision.com", "Admin123!X")


@pytest.fixture(scope="module")
def any_org(sa_session):
    r = sa_session.get(f"{BASE}/super-admin/orgs", timeout=30)
    assert r.status_code == 200
    orgs = r.json()
    assert orgs, "expected at least one org seeded"
    return orgs[0]


# ─── GET /orgs enrichment ─────────────────────────────────────────────
class TestListOrgsEnrichment:
    def test_list_orgs_200_and_new_fields(self, sa_session):
        r = sa_session.get(f"{BASE}/super-admin/orgs", timeout=30)
        assert r.status_code == 200
        orgs = r.json()
        assert isinstance(orgs, list) and orgs
        keys = {
            "pricing_tier", "included_hours_monthly", "is_trial", "trial_ends_at",
            "stripe_customer_id", "stripe_subscription_status", "stripe_current_period_end",
            "billing_notes", "current_period_start", "current_period_end",
            "current_period_hours", "cumulative_hours", "hours_overage",
        }
        missing = keys - orgs[0].keys()
        assert not missing, f"missing enriched fields: {missing}"

    def test_hours_overage_flag_is_bool(self, sa_session):
        r = sa_session.get(f"{BASE}/super-admin/orgs", timeout=30)
        for o in r.json():
            assert isinstance(o["hours_overage"], bool)
            assert isinstance(o["current_period_hours"], (int, float))
            assert isinstance(o["cumulative_hours"], (int, float))

    def test_non_super_admin_forbidden(self, admin_session):
        r = admin_session.get(f"{BASE}/super-admin/orgs", timeout=30)
        assert r.status_code == 403


# ─── PATCH /orgs/{id}/billing ─────────────────────────────────────────
class TestUpdateOrgBilling:
    def test_update_and_persist(self, sa_session, any_org):
        oid = any_org["id"]
        payload = {
            "pricing_tier": "growth",
            "included_hours_monthly": 30,
            "is_trial": True,
            "trial_ends_at": "2027-01-01",
            "stripe_customer_id": "cus_TEST_SA_BILL",
            "stripe_subscription_status": "past_due",
            "stripe_current_period_end": "2020-01-15",  # in the past
            "billing_notes": "TEST_ notes from pytest",
        }
        r = sa_session.patch(f"{BASE}/super-admin/orgs/{oid}/billing", json=payload, timeout=30)
        assert r.status_code == 200, r.text

        # verify persisted via GET
        r2 = sa_session.get(f"{BASE}/super-admin/orgs", timeout=30)
        org = next(o for o in r2.json() if o["id"] == oid)
        assert org["pricing_tier"] == "growth"
        assert float(org["included_hours_monthly"]) == 30.0
        assert org["is_trial"] is True
        assert org["stripe_customer_id"] == "cus_TEST_SA_BILL"
        assert org["stripe_subscription_status"] == "past_due"
        assert org["billing_notes"] == "TEST_ notes from pytest"

    def test_invalid_tier_silently_nulled(self, sa_session, any_org):
        oid = any_org["id"]
        # First set a valid tier
        sa_session.patch(f"{BASE}/super-admin/orgs/{oid}/billing",
                         json={"pricing_tier": "scale"}, timeout=30)
        # Now send an invalid tier; router treats invalid as None
        r = sa_session.patch(f"{BASE}/super-admin/orgs/{oid}/billing",
                             json={"pricing_tier": "bogus_tier"}, timeout=30)
        assert r.status_code == 200
        r2 = sa_session.get(f"{BASE}/super-admin/orgs", timeout=30)
        org = next(o for o in r2.json() if o["id"] == oid)
        assert org["pricing_tier"] is None

    def test_invalid_stripe_status_nulled(self, sa_session, any_org):
        oid = any_org["id"]
        r = sa_session.patch(f"{BASE}/super-admin/orgs/{oid}/billing",
                             json={"stripe_subscription_status": "totally_fake"}, timeout=30)
        assert r.status_code == 200
        r2 = sa_session.get(f"{BASE}/super-admin/orgs", timeout=30)
        org = next(o for o in r2.json() if o["id"] == oid)
        assert org["stripe_subscription_status"] is None

    def test_clear_notes_via_empty_string(self, sa_session, any_org):
        oid = any_org["id"]
        sa_session.patch(f"{BASE}/super-admin/orgs/{oid}/billing",
                         json={"billing_notes": "TEST_ temporary"}, timeout=30)
        r = sa_session.patch(f"{BASE}/super-admin/orgs/{oid}/billing",
                             json={"billing_notes": ""}, timeout=30)
        assert r.status_code == 200
        r2 = sa_session.get(f"{BASE}/super-admin/orgs", timeout=30)
        org = next(o for o in r2.json() if o["id"] == oid)
        assert org["billing_notes"] in (None, "")

    def test_empty_body_400(self, sa_session, any_org):
        r = sa_session.patch(f"{BASE}/super-admin/orgs/{any_org['id']}/billing",
                             json={}, timeout=30)
        assert r.status_code == 400

    def test_unknown_org_404(self, sa_session):
        r = sa_session.patch(f"{BASE}/super-admin/orgs/00000000-0000-0000-0000-000000000000/billing",
                             json={"billing_notes": "x"}, timeout=30)
        assert r.status_code == 404

    def test_non_super_admin_forbidden(self, admin_session, any_org):
        r = admin_session.patch(f"{BASE}/super-admin/orgs/{any_org['id']}/billing",
                                json={"billing_notes": "hack"}, timeout=30)
        assert r.status_code == 403


# ─── GET /orgs/{id}/usage-history ─────────────────────────────────────
class TestUsageHistory:
    def test_returns_up_to_12_cycles(self, sa_session, any_org):
        r = sa_session.get(f"{BASE}/super-admin/orgs/{any_org['id']}/usage-history", timeout=30)
        assert r.status_code == 200
        cycles = r.json()
        assert isinstance(cycles, list)
        assert 1 <= len(cycles) <= 12
        for c in cycles:
            assert "period_start" in c and "period_end" in c and "hours" in c
            assert isinstance(c["hours"], (int, float))

    def test_unknown_org_404(self, sa_session):
        r = sa_session.get(
            f"{BASE}/super-admin/orgs/00000000-0000-0000-0000-000000000000/usage-history",
            timeout=30,
        )
        assert r.status_code == 404

    def test_non_super_admin_forbidden(self, admin_session, any_org):
        r = admin_session.get(
            f"{BASE}/super-admin/orgs/{any_org['id']}/usage-history", timeout=30
        )
        assert r.status_code == 403


# ─── audio_duration_seconds column exists on meetings (schema smoke test) ─
class TestSchema:
    def test_meetings_has_audio_duration_seconds(self):
        async def _check():
            conn = await asyncpg.connect(DSN, ssl="require")
            row = await conn.fetchrow(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='meetings' AND column_name='audio_duration_seconds'"
            )
            await conn.close()
            return row is not None

        assert asyncio.run(_check()), "meetings.audio_duration_seconds column missing"

    def test_orgs_has_billing_columns(self):
        async def _check():
            conn = await asyncpg.connect(DSN, ssl="require")
            cols = [r["column_name"] for r in await conn.fetch(
                "SELECT column_name FROM information_schema.columns WHERE table_name='organisations'"
            )]
            await conn.close()
            return cols

        cols = asyncio.run(_check())
        required = [
            "pricing_tier", "included_hours_monthly", "is_trial", "trial_ends_at",
            "stripe_customer_id", "stripe_subscription_status",
            "stripe_current_period_end", "billing_notes",
        ]
        missing = [c for c in required if c not in cols]
        assert not missing, f"organisations table missing columns: {missing}"
