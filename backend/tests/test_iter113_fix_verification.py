"""Iter113: verification of the 5 fixes from iteration_112 + auth regression checks.

Modules under test:
  - deps.get_current_user  -> GET /api/auth/me now returns must_change_password + mfa_enabled (FIX 1)
  - routers/auth.py        -> reset-password / change-password happy path still works (FIX 3)
  - routers/auth.py login  -> MFA gate (admin/manager optional, super_admin mandatory) (REGRESSION)
  - bcrypt fallback vs Supabase credential path (REGRESSION)
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

FE = dotenv_values("/app/frontend/.env")
BE = dotenv_values("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or FE["REACT_APP_BACKEND_URL"]).rstrip("/")
DSN = BE["DATABASE_URL"]

ADMIN = ("admin@supervision.com", "Admin123!")
MANAGER = ("manager@supervision.com", "Manager123!")
SUPERADMIN = ("superadmin@1two.one", "NewPass123!")
SUPA_USER = ("user@supervision.com", "AnotherNew789!")
JANE = ("jane@supervision.com", "JaneNew456!")

TIMEOUT = 60


# ---------- helpers ----------

async def _clear_rate_limits():
    c = await asyncpg.connect(DSN)
    await c.execute("DELETE FROM login_attempts")
    await c.close()


async def _flags(email):
    c = await asyncpg.connect(DSN)
    r = await c.fetchrow(
        "SELECT id, must_change_password, mfa_enabled, supabase_migrated, supabase_password_set "
        "FROM users WHERE email=$1", email)
    await c.close()
    return dict(r) if r else None


async def _force_mfa_code(email):
    c = await asyncpg.connect(DSN)
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    await c.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2 WHERE email=$3",
        h, datetime.now(timezone.utc) + timedelta(minutes=10), email)
    await c.close()


async def _reset_token(email):
    c = await asyncpg.connect(DSN)
    r = await c.fetchrow(
        "SELECT token FROM password_reset_tokens WHERE email=$1", email)
    await c.close()
    return r["token"] if r else None


async def _purge(email):
    c = await asyncpg.connect(DSN)
    row = await c.fetchrow("SELECT id FROM users WHERE email=$1", email)
    if row:
        await c.execute("DELETE FROM password_reset_tokens WHERE email=$1", email)
        await c.execute("DELETE FROM login_attempts WHERE identifier=$1", email)
        await c.execute("DELETE FROM users WHERE id=$1", row["id"])
    await c.close()
    if row:
        sys.path.insert(0, "/app/backend")
        os.environ.setdefault("SUPABASE_URL", BE["SUPABASE_URL"])
        os.environ.setdefault("SUPABASE_SERVICE_KEY", BE["SUPABASE_SERVICE_KEY"])
        try:
            from utils.supabase_auth import _get_admin_client
            _get_admin_client().auth.admin.delete_user(str(row["id"]))
        except Exception as e:  # noqa: BLE001
            print("supabase delete failed:", e)


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": email, "password": password},
               timeout=TIMEOUT)
    return s, r


def _login_full(email, password):
    """Login, completing MFA if required. Returns authenticated session."""
    asyncio.run(_clear_rate_limits())
    s, r = _login(email, password)
    assert r.status_code == 200, f"login {email} -> {r.status_code} {r.text[:300]}"
    body = r.json()
    if body.get("requires_mfa"):
        asyncio.run(_force_mfa_code(email))
        vr = s.post(f"{BASE}/api/auth/verify-mfa",
                    json={"mfa_session": body["mfa_session"], "code": "123456"}, timeout=TIMEOUT)
        assert vr.status_code == 200, f"verify-mfa -> {vr.status_code} {vr.text[:300]}"
        body = vr.json()
    return s, body


@pytest.fixture(scope="module", autouse=True)
def _clean():
    asyncio.run(_clear_rate_limits())
    yield
    asyncio.run(_clear_rate_limits())


@pytest.fixture(scope="module")
def admin_session():
    s, _ = _login_full(*ADMIN)
    return s


# ================= FIX 1: /auth/me exposes must_change_password + mfa_enabled =================

class TestFix1AuthMeFlags:

    def test_me_includes_new_fields_for_admin(self, admin_session):
        r = admin_session.get(f"{BASE}/api/auth/me", timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert "must_change_password" in data, f"missing must_change_password: {list(data)}"
        assert "mfa_enabled" in data, f"missing mfa_enabled: {list(data)}"
        assert isinstance(data["must_change_password"], bool)
        assert isinstance(data["mfa_enabled"], bool)
        assert data["email"] == ADMIN[0]
        assert "_id" not in data
        assert "password_hash" not in data

    def test_new_admin_created_user_me_reports_must_change_password(self, admin_session):
        email = f"test_iter113_{uuid.uuid4().hex[:6]}@example.com"
        try:
            cr = admin_session.post(f"{BASE}/api/admin/users", timeout=TIMEOUT,
                                    json={"email": email, "name": "TEST Iter113 MCP",
                                          "role": "attendee", "password": "InitialPass123!"})
            assert cr.status_code in (200, 201), f"create -> {cr.status_code} {cr.text[:300]}"

            db = asyncio.run(_flags(email))
            assert db["must_change_password"] is True, "DB precondition: flag should be TRUE"

            us, body = _login_full(email, "InitialPass123!")
            assert body.get("requires_mfa") is not True
            me = us.get(f"{BASE}/api/auth/me", timeout=TIMEOUT)
            assert me.status_code == 200, me.text[:300]
            prof = me.json()
            assert prof["must_change_password"] is True, \
                f"/auth/me must_change_password should be True, got {prof.get('must_change_password')}"
            assert prof["mfa_enabled"] is False
        finally:
            asyncio.run(_purge(email))


# ================= FIX 3: reset-password / change-password happy path =================

class TestFix3PasswordLifecycleHappyPath:

    def test_reset_then_change_password_round_trip(self, admin_session):
        email = f"test_iter113_pw_{uuid.uuid4().hex[:6]}@example.com"
        p0, p1, p2 = "InitialPass123!", "ResetPass456!", "ChangePass789!"
        try:
            cr = admin_session.post(f"{BASE}/api/admin/users", timeout=TIMEOUT,
                                    json={"email": email, "name": "TEST Iter113 PW",
                                          "role": "attendee", "password": p0})
            assert cr.status_code in (200, 201), cr.text[:300]

            # --- forgot -> reset ---
            fr = requests.post(f"{BASE}/api/auth/forgot-password", json={"email": email},
                               timeout=TIMEOUT)
            assert fr.status_code == 200, fr.text[:300]
            tok = asyncio.run(_reset_token(email))
            assert tok, "no reset token issued"

            rr = requests.post(f"{BASE}/api/auth/reset-password",
                               json={"token": tok, "new_password": p1}, timeout=TIMEOUT)
            assert rr.status_code == 200, f"reset-password -> {rr.status_code} {rr.text[:300]}"

            flags = asyncio.run(_flags(email))
            assert flags["supabase_password_set"] is True

            # old password rejected, new one works
            asyncio.run(_clear_rate_limits())
            _, bad = _login(email, p0)
            assert bad.status_code == 401, f"old password should be rejected, got {bad.status_code}"
            s1, _ = _login_full(email, p1)

            # --- change-password ---
            cp = s1.post(f"{BASE}/api/auth/change-password",
                         json={"current_password": p1, "new_password": p2}, timeout=TIMEOUT)
            assert cp.status_code == 200, f"change-password -> {cp.status_code} {cp.text[:300]}"

            asyncio.run(_clear_rate_limits())
            _, bad2 = _login(email, p1)
            assert bad2.status_code == 401, f"p1 should now be rejected, got {bad2.status_code}"
            s2, _ = _login_full(email, p2)
            me = s2.get(f"{BASE}/api/auth/me", timeout=TIMEOUT)
            assert me.status_code == 200
            assert me.json()["email"] == email
        finally:
            asyncio.run(_purge(email))

    def test_change_password_wrong_current_rejected(self, admin_session):
        email = f"test_iter113_cp_{uuid.uuid4().hex[:6]}@example.com"
        try:
            cr = admin_session.post(f"{BASE}/api/admin/users", timeout=TIMEOUT,
                                    json={"email": email, "name": "TEST Iter113 CP",
                                          "role": "attendee", "password": "InitialPass123!"})
            assert cr.status_code in (200, 201), cr.text[:300]
            s, _ = _login_full(email, "InitialPass123!")
            r = s.post(f"{BASE}/api/auth/change-password",
                       json={"current_password": "WrongPass123!", "new_password": "NewOne456!"},
                       timeout=TIMEOUT)
            assert r.status_code in (400, 401), f"expected 400/401, got {r.status_code}"
        finally:
            asyncio.run(_purge(email))

    def test_reset_password_weak_password_rejected(self, admin_session):
        email = f"test_iter113_weak_{uuid.uuid4().hex[:6]}@example.com"
        try:
            cr = admin_session.post(f"{BASE}/api/admin/users", timeout=TIMEOUT,
                                    json={"email": email, "name": "TEST Iter113 Weak",
                                          "role": "attendee", "password": "InitialPass123!"})
            assert cr.status_code in (200, 201), cr.text[:300]
            requests.post(f"{BASE}/api/auth/forgot-password", json={"email": email}, timeout=TIMEOUT)
            tok = asyncio.run(_reset_token(email))
            r = requests.post(f"{BASE}/api/auth/reset-password",
                              json={"token": tok, "new_password": "Ab1!short"}, timeout=TIMEOUT)
            assert r.status_code == 400, f"expected 400 for 9-char password, got {r.status_code}"
        finally:
            asyncio.run(_purge(email))


# ================= REGRESSION: MFA gate + credential paths =================

class TestRegressionLoginPaths:

    def test_admin_login_no_mfa(self):
        asyncio.run(_clear_rate_limits())
        s, r = _login(*ADMIN)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body.get("requires_mfa") is not True, "admin should NOT require MFA"
        assert body.get("user", body).get("role") == "admin"

    def test_manager_login_no_mfa(self):
        asyncio.run(_clear_rate_limits())
        s, r = _login(*MANAGER)
        assert r.status_code == 200, r.text[:300]
        assert r.json().get("requires_mfa") is not True, "manager should NOT require MFA"

    def test_super_admin_login_requires_mfa(self):
        asyncio.run(_clear_rate_limits())
        s, r = _login(*SUPERADMIN)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body.get("requires_mfa") is True, "super_admin MFA must remain mandatory"
        assert body.get("mfa_session")
        assert "access_token" not in body

    def test_supabase_migrated_user_login(self):
        flags = asyncio.run(_flags(SUPA_USER[0]))
        assert flags["supabase_password_set"] is True, "precondition: user should be Supabase-backed"
        s, body = _login_full(*SUPA_USER)
        me = s.get(f"{BASE}/api/auth/me", timeout=TIMEOUT)
        assert me.status_code == 200
        assert me.json()["email"] == SUPA_USER[0]

    def test_bcrypt_fallback_user_login(self):
        flags = asyncio.run(_flags(ADMIN[0]))
        assert flags["supabase_password_set"] is False, "precondition: admin on bcrypt"
        s, body = _login_full(*ADMIN)
        me = s.get(f"{BASE}/api/auth/me", timeout=TIMEOUT)
        assert me.status_code == 200

    def test_wrong_password_bcrypt_path_401(self):
        asyncio.run(_clear_rate_limits())
        _, r = _login(ADMIN[0], "TotallyWrong999!")
        assert r.status_code == 401, f"expected 401, got {r.status_code} {r.text[:200]}"

    def test_wrong_password_supabase_path_401(self):
        asyncio.run(_clear_rate_limits())
        _, r = _login(JANE[0], "TotallyWrong999!")
        assert r.status_code == 401, f"expected 401, got {r.status_code} {r.text[:200]}"

    def test_toggle_mfa_endpoint_available_for_admin(self, admin_session):
        """FIX 2 backend side: admin can request an MFA toggle code."""
        r = admin_session.post(f"{BASE}/api/auth/request-mfa-code", json={}, timeout=TIMEOUT)
        assert r.status_code == 200, f"request-mfa-code -> {r.status_code}: {r.text[:300]}"

    def test_toggle_mfa_wrong_code_rejected(self, admin_session):
        r = admin_session.post(f"{BASE}/api/auth/toggle-mfa",
                               json={"code": "000000", "enable": True}, timeout=TIMEOUT)
        assert r.status_code in (400, 401), f"expected rejection, got {r.status_code}"
