"""Regression tests for the new Stripe self-serve signup flow + existing
Super Admin org/invite flow. Since STRIPE_SECRET_KEY is empty, we simulate
"paid" Stripe sessions by directly calling _upsert_pending_signup_from_session()
against the DB, then exercise the /api/public/checkout/verify,
/api/public/onboarding/complete, and cron endpoints via HTTP.
"""
import os
import sys
import uuid
import asyncio
import pytest
import requests
import bcrypt
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/app/backend")

from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")

import database  # noqa: E402
from routers.public_signup import _upsert_pending_signup_from_session  # noqa: E402


async def _ensure_pool():
    # Reset stale pool from a closed loop (each _run() creates a new loop)
    if database.admin_pool is not None:
        try:
            await database.admin_pool.close()
        except Exception:
            pass
        database.admin_pool = None
        database.pool = None
    await database.create_pool()


def _run(coro):
    async def _wrap():
        try:
            return await coro
        finally:
            if database.admin_pool is not None:
                await database.admin_pool.close()
                database.admin_pool = None
            if database.pool is not None:
                await database.pool.close()
                database.pool = None
    return asyncio.new_event_loop().run_until_complete(_wrap())

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://supervision-preview.preview.emergentagent.com").rstrip("/")
CRON_SECRET = os.environ.get("WEBHOOK_CRON_SECRET") or open("/app/backend/.env").read().split("WEBHOOK_CRON_SECRET=")[1].split("\n")[0].strip().strip('"')

SUPER_ADMIN_EMAIL = "superadmin@1two.one"
SUPER_ADMIN_PASSWORD = "TestPass123!"

# Track created rows for teardown
_CREATED = {"pending_signups": [], "orgs": [], "users": []}


# ── helpers ────────────────────────────────────────────────────────────────

def _fake_session(session_id=None, tier="starter"):
    session_id = session_id or f"cs_test_{uuid.uuid4().hex[:16]}"
    return {
        "id": session_id,
        "customer": f"cus_fake_{uuid.uuid4().hex[:8]}",
        "subscription": f"sub_fake_{uuid.uuid4().hex[:8]}",
        "metadata": {"tier": tier, "is_founding": "true"},
        "payment_status": "paid",
    }


async def _create_pending_signup(tier="starter"):
    await _ensure_pool()
    session = _fake_session(tier=tier)
    async with database.with_admin() as conn:
        row = await _upsert_pending_signup_from_session(conn, session, stripe_mod=None)
    _CREATED["pending_signups"].append(session["id"])
    return session["id"], row


def _super_admin_login():
    # Clear MFA-send rate limit for super_admin before login
    async def _clear_rl():
        await _ensure_pool()
        async with database.with_admin() as conn:
            u = await conn.fetchrow("SELECT id FROM users WHERE email=$1", SUPER_ADMIN_EMAIL)
            if u:
                await conn.execute(
                    "DELETE FROM login_attempts WHERE identifier=$1",
                    f"mfa_send:{u['id']}",
                )
                await conn.execute(
                    "DELETE FROM login_attempts WHERE identifier=$1",
                    f"login:{SUPER_ADMIN_EMAIL}",
                )
    _run(_clear_rl())

    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": SUPER_ADMIN_EMAIL, "password": SUPER_ADMIN_PASSWORD})
    if r.status_code != 200:
        pytest.skip(f"super_admin login failed: {r.status_code} {r.text[:200]}")
    data = r.json()
    if not data.get("requires_mfa"):
        return s
    # MFA required — DB-override the OTP
    mfa_session = data["mfa_session"]

    async def _set_mfa_code():
        await _ensure_pool()
        code_hash = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
        expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        async with database.with_admin() as conn:
            await conn.execute(
                "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2 WHERE email=$3",
                code_hash, expires, SUPER_ADMIN_EMAIL,
            )
    _run(_set_mfa_code())
    r2 = s.post(f"{BASE_URL}/api/auth/verify-mfa", json={"mfa_session": mfa_session, "code": "123456"})
    if r2.status_code != 200:
        pytest.skip(f"MFA verify failed: {r2.status_code} {r2.text[:200]}")
    return s


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def super_admin_session():
    return _super_admin_login()


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    async def _clean():
        await _ensure_pool()
        async with database.with_admin() as conn:
            if _CREATED["users"]:
                await conn.execute("DELETE FROM invitations WHERE user_id = ANY($1::uuid[])", _CREATED["users"])
                await conn.execute("DELETE FROM users WHERE id = ANY($1::uuid[])", _CREATED["users"])
            if _CREATED["orgs"]:
                # cascade: also cleanup invitations/users/settings tied to org
                await conn.execute("DELETE FROM invitations WHERE org_id = ANY($1::uuid[])", _CREATED["orgs"])
                await conn.execute("DELETE FROM users WHERE org_id = ANY($1::uuid[])", _CREATED["orgs"])
                await conn.execute("DELETE FROM settings WHERE org_id = ANY($1::uuid[])", _CREATED["orgs"])
                await conn.execute("DELETE FROM organisations WHERE id = ANY($1::uuid[])", _CREATED["orgs"])
            if _CREATED["pending_signups"]:
                await conn.execute(
                    "DELETE FROM provisioning_failures WHERE pending_signup_id IN (SELECT id FROM pending_signups WHERE stripe_checkout_session_id = ANY($1))",
                    _CREATED["pending_signups"],
                )
                await conn.execute(
                    "DELETE FROM pending_signups WHERE stripe_checkout_session_id = ANY($1)",
                    _CREATED["pending_signups"],
                )
    try:
        _run(_clean())
    except Exception as e:
        print(f"Cleanup error: {e}")


# ── Tests: pending_signups upsert helper ────────────────────────────────────

class TestPendingSignupUpsert:
    def test_creates_row_with_founding_lock(self):
        sid, row = _run(_create_pending_signup(tier="starter"))
        assert row["tier"] == "starter"
        assert row["is_founding"] is True
        assert row["status"] == "paid"
        assert row["org_id"] is None
        assert row["founding_price_lock_until"] is not None
        # ~12 months out
        lock = row["founding_price_lock_until"]
        if isinstance(lock, str):
            lock = datetime.fromisoformat(lock)
        delta = lock - datetime.now(timezone.utc)
        assert 360 < delta.days < 370, f"Expected ~365 days, got {delta.days}"


# ── Tests: /api/public/checkout/verify ──────────────────────────────────────

class TestCheckoutVerify:
    def test_verify_ok_for_pending_signup(self):
        sid, _ = _run(_create_pending_signup(tier="growth"))
        r = requests.get(f"{BASE_URL}/api/public/checkout/verify", params={"session_id": sid})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "ok"
        assert data["tier"] == "growth"
        assert data["founding"] is True

    def test_verify_unknown_session_404(self):
        r = requests.get(
            f"{BASE_URL}/api/public/checkout/verify",
            params={"session_id": f"cs_test_bogus_{uuid.uuid4().hex}"},
        )
        assert r.status_code == 404, r.text


# ── Tests: /api/public/onboarding/complete ──────────────────────────────────

class TestOnboardingComplete:
    def test_complete_onboarding_creates_org_and_user(self):
        sid, _ = _run(_create_pending_signup(tier="starter"))
        org_name = f"TEST_SelfServe_{uuid.uuid4().hex[:8]}"
        email = f"test-{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(
            f"{BASE_URL}/api/public/onboarding/complete",
            json={
                "session_id": sid, "name": "Test Admin", "email": email,
                "organisation_name": org_name, "jurisdiction": "england",
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["success"] is True
        assert data["organisation_name"].startswith("TEST_SelfServe_")

        # Verify DB state
        async def _check():
            await _ensure_pool()
            async with database.with_admin() as conn:
                ps = await conn.fetchrow(
                    "SELECT * FROM pending_signups WHERE stripe_checkout_session_id=$1", sid
                )
                assert ps["status"] == "consumed"
                assert ps["org_id"] is not None
                org = await conn.fetchrow("SELECT * FROM organisations WHERE id=$1", ps["org_id"])
                assert org["pricing_tier"] == "starter"
                assert org["is_founding_member"] is True
                assert org["founding_price_lock_until"] is not None
                assert org["stripe_customer_id"] is not None
                assert org["stripe_subscription_id"] is not None
                assert org["stripe_subscription_status"] == "active"
                user = await conn.fetchrow("SELECT * FROM users WHERE email=$1", email)
                assert user["role"] == "admin"
                assert user["is_active"] is False
                assert user["org_id"] == org["id"]
                inv = await conn.fetchrow("SELECT * FROM invitations WHERE user_id=$1", user["id"])
                assert inv is not None
                _CREATED["orgs"].append(org["id"])
                _CREATED["users"].append(user["id"])
        _run(_check())

        # verify now returns already_used
        r2 = requests.get(f"{BASE_URL}/api/public/checkout/verify", params={"session_id": sid})
        assert r2.status_code == 200
        assert r2.json()["status"] == "already_used"

        # second complete attempt should 400
        r3 = requests.post(
            f"{BASE_URL}/api/public/onboarding/complete",
            json={
                "session_id": sid, "name": "Test Admin", "email": email,
                "organisation_name": org_name, "jurisdiction": "england",
            },
        )
        assert r3.status_code == 400, r3.text
        assert "already been used" in r3.json()["detail"].lower()

    def test_complete_unknown_session_404(self):
        r = requests.post(
            f"{BASE_URL}/api/public/onboarding/complete",
            json={
                "session_id": f"cs_test_ghost_{uuid.uuid4().hex}",
                "name": "X", "email": "x@example.com",
                "organisation_name": "TEST_Ghost", "jurisdiction": "england",
            },
        )
        assert r.status_code == 404

    def test_northern_ireland_requires_service_type(self):
        sid, _ = _run(_create_pending_signup(tier="starter"))
        r = requests.post(
            f"{BASE_URL}/api/public/onboarding/complete",
            json={
                "session_id": sid, "name": "NI Admin",
                "email": f"ni-{uuid.uuid4().hex[:8]}@example.com",
                "organisation_name": f"TEST_NI_{uuid.uuid4().hex[:6]}",
                "jurisdiction": "northern_ireland",
            },
        )
        assert r.status_code == 400
        assert "service_type" in r.json()["detail"].lower()

    def test_ofsted_requires_service_type(self):
        sid, _ = _run(_create_pending_signup(tier="starter"))
        r = requests.post(
            f"{BASE_URL}/api/public/onboarding/complete",
            json={
                "session_id": sid, "name": "Ofsted Admin",
                "email": f"ofs-{uuid.uuid4().hex[:8]}@example.com",
                "organisation_name": f"TEST_Ofsted_{uuid.uuid4().hex[:6]}",
                "jurisdiction": "ofsted",
            },
        )
        assert r.status_code == 400
        assert "service_type" in r.json()["detail"].lower()

    def test_ofsted_with_valid_service_type_ok(self):
        sid, _ = _run(_create_pending_signup(tier="scale"))
        email = f"ofsokay-{uuid.uuid4().hex[:8]}@example.com"
        org_name = f"TEST_OfstedOK_{uuid.uuid4().hex[:6]}"
        r = requests.post(
            f"{BASE_URL}/api/public/onboarding/complete",
            json={
                "session_id": sid, "name": "Ofsted Admin", "email": email,
                "organisation_name": org_name,
                "jurisdiction": "ofsted", "service_type": "childrens_home",
            },
        )
        assert r.status_code == 200, r.text
        async def _grab():
            await _ensure_pool()
            async with database.with_admin() as conn:
                org = await conn.fetchrow("SELECT id, service_type FROM organisations WHERE name=$1", org_name)
                user = await conn.fetchrow("SELECT id FROM users WHERE email=$1", email)
                assert org["service_type"] == "childrens_home"
                _CREATED["orgs"].append(org["id"])
                _CREATED["users"].append(user["id"])
        _run(_grab())


# ── Tests: cron endpoints ──────────────────────────────────────────────────

class TestCronAuth:
    @pytest.mark.parametrize("path", [
        "/api/cron/founding-reminder",
        "/api/cron/provisioning-retry",
        "/api/cron/abandoned-signup",
    ])
    def test_no_auth_401(self, path):
        r = requests.post(f"{BASE_URL}{path}")
        assert r.status_code == 401

    @pytest.mark.parametrize("path", [
        "/api/cron/founding-reminder",
        "/api/cron/provisioning-retry",
        "/api/cron/abandoned-signup",
    ])
    def test_wrong_token_401(self, path):
        r = requests.post(f"{BASE_URL}{path}", headers={"Authorization": "Bearer wrong-token"})
        assert r.status_code == 401

    @pytest.mark.parametrize("path", [
        "/api/cron/founding-reminder",
        "/api/cron/provisioning-retry",
        "/api/cron/abandoned-signup",
    ])
    def test_correct_token_200_accepted(self, path):
        r = requests.post(f"{BASE_URL}{path}", headers={"Authorization": f"Bearer {CRON_SECRET}"})
        assert r.status_code == 200, r.text
        assert r.json().get("status") == "accepted"


# ── Tests: /api/public/checkout create (Stripe not configured) ──────────────

class TestPublicCheckoutCreate:
    def test_missing_keys_returns_503(self):
        r = requests.post(f"{BASE_URL}/api/public/checkout", json={"tier": "starter"})
        assert r.status_code == 503, r.text

    def test_bogus_tier_400(self):
        r = requests.post(f"{BASE_URL}/api/public/checkout", json={"tier": "bogus"})
        assert r.status_code == 400


# ── Tests: super_admin manual regression ───────────────────────────────────

class TestSuperAdminRegression:
    def test_create_org_and_invite(self, super_admin_session):
        s = super_admin_session
        org_name = f"TEST_SA_{uuid.uuid4().hex[:8]}"
        r = s.post(f"{BASE_URL}/api/super-admin/orgs", json={"name": org_name, "jurisdiction": "england"})
        assert r.status_code == 200, r.text
        org = r.json()
        _CREATED["orgs"].append(org["id"])

        # duplicate name should 400
        r_dup = s.post(f"{BASE_URL}/api/super-admin/orgs", json={"name": org_name, "jurisdiction": "england"})
        assert r_dup.status_code == 400
        assert "already exists" in r_dup.json()["detail"].lower()

        # invite an admin
        invite_email = f"sa-invite-{uuid.uuid4().hex[:8]}@example.com"
        r_inv = s.post(f"{BASE_URL}/api/super-admin/orgs/{org['id']}/invite",
                       json={"email": invite_email, "name": "SA Invite"})
        assert r_inv.status_code == 200, r_inv.text
        data = r_inv.json()
        assert "user_id" in data or data.get("email_failed")
        # track user for cleanup
        async def _get_user():
            await _ensure_pool()
            async with database.with_admin() as conn:
                u = await conn.fetchrow("SELECT id FROM users WHERE email=$1", invite_email)
                if u:
                    _CREATED["users"].append(u["id"])
        _run(_get_user())

        # duplicate email invite -> 400
        r_dup_email = s.post(f"{BASE_URL}/api/super-admin/orgs/{org['id']}/invite",
                             json={"email": invite_email, "name": "Dup"})
        assert r_dup_email.status_code == 400
        assert "already exists" in r_dup_email.json()["detail"].lower()

    def test_create_org_northern_ireland_requires_service_type(self, super_admin_session):
        s = super_admin_session
        r = s.post(f"{BASE_URL}/api/super-admin/orgs",
                   json={"name": f"TEST_NI_SA_{uuid.uuid4().hex[:6]}", "jurisdiction": "northern_ireland"})
        assert r.status_code == 400
        assert "service_type" in r.json()["detail"].lower()
