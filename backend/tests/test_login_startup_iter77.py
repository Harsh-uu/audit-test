"""Iteration 77 — verify backend startup robustness (seed_super_admin no longer
raises SystemExit) and that the normal login/MFA flow works end-to-end.
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import bcrypt
import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend")

fe = dotenv_values("/app/frontend/.env")
be = dotenv_values("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or fe["REACT_APP_BACKEND_URL"]).rstrip("/") + "/api"
DSN = be["DATABASE_URL"]

MANAGER = ("manager@supervision.com", "Manager123!")
SUPERADMIN = ("superadmin@1two.one", "SuperAdmin123!")
STAFF = ("user@supervision.com", "Staff123!")


# ---------- health / startup ----------
class TestHealth:
    def test_health_ok(self):
        r = requests.get(f"{BASE}/health", timeout=30)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data["status"] == "ok"
        assert isinstance(data.get("service"), str) and data["service"]

    def test_unauthenticated_me_is_401_not_5xx(self):
        r = requests.get(f"{BASE}/auth/me", timeout=30)
        assert r.status_code == 401, f"{r.status_code} {r.text[:200]}"


# ---------- seed crash path (fresh-DB simulation) ----------
class TestSeedSuperAdminCrashPath:
    def test_no_systemexit_in_source(self):
        src = open("/app/backend/utils/seed.py").read()
        assert "SystemExit" not in src
        assert "sys.exit" not in src

    def test_weak_password_nonexistent_user_does_not_exit(self):
        """Simulate fresh DB: super-admin email that doesn't exist + weak default
        password. Must log critical and return, not raise SystemExit, and must
        NOT create the row."""
        import importlib

        async def run():
            os.environ["DATABASE_URL"] = DSN
            os.environ["SUPER_ADMIN_EMAIL"] = "TEST_nonexistent_sa_iter77@example.com"
            os.environ["SUPER_ADMIN_PASSWORD"] = "SuperAdmin123!"
            import database
            from utils import seed as seed_mod
            importlib.reload(seed_mod)
            await database.create_pool()
            try:
                await seed_mod.seed_super_admin()
                async with database.with_admin() as conn:
                    row = await conn.fetchrow(
                        "SELECT id FROM users WHERE email = $1",
                        "TEST_nonexistent_sa_iter77@example.com")
                return row
            finally:
                await database.close_pool()

        try:
            row = asyncio.run(run())
        except SystemExit as e:
            pytest.fail(f"seed_super_admin raised SystemExit: {e}")
        assert row is None, "weak password should NOT seed a super-admin row"


# ---------- login flows ----------
def _login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=90)
    return s, r


async def _force_mfa_code(email):
    import asyncpg
    conn = await asyncpg.connect(DSN, ssl="require")
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    await conn.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, exp, email)
    await conn.close()


def _full_login(email, password, expect_mfa=True):
    s, r = _login(email, password)
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text[:300]}"
    data = r.json()
    if expect_mfa:
        assert data.get("requires_mfa") is True, f"expected requires_mfa, got {json.dumps(data)[:300]}"
        assert data.get("mfa_session"), "missing mfa_session"
        asyncio.run(_force_mfa_code(email))
        r2 = s.post(f"{BASE}/auth/verify-mfa",
                    json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=90)
        assert r2.status_code == 200, f"verify-mfa failed {r2.status_code}: {r2.text[:300]}"
    cookies = {c.name: c.value for c in s.cookies}
    assert "supervision_access" in cookies, f"no access cookie: {cookies.keys()}"
    me = s.get(f"{BASE}/auth/me", timeout=60)
    assert me.status_code == 200, me.text[:300]
    body = me.json()
    assert body["email"] == email
    assert '"_id"' not in json.dumps(body)
    return s, body


class TestLogin:
    def test_manager_login_mfa_flow(self):
        _, me = _full_login(*MANAGER)
        assert me["role"] == "manager"

    def test_super_admin_login_mfa_flow(self):
        _, me = _full_login(*SUPERADMIN)
        assert me["role"] == "super_admin"

    def test_staff_login_no_mfa(self):
        s, r = _login(*STAFF)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert not data.get("requires_mfa")
        cookies = {c.name: c.value for c in s.cookies}
        assert "supervision_access" in cookies
        me = s.get(f"{BASE}/auth/me", timeout=60)
        assert me.status_code == 200
        assert me.json()["email"] == STAFF[0]

    def test_invalid_password_rejected(self):
        r = requests.post(f"{BASE}/auth/login",
                          json={"email": STAFF[0], "password": "WrongPass123!"}, timeout=60)
        assert r.status_code in (401, 429), f"{r.status_code} {r.text[:200]}"

    def test_authenticated_data_endpoint(self):
        s, _ = _full_login(*MANAGER)
        r = s.get(f"{BASE}/meetings/", timeout=90)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        payload = r.json()
        items = payload if isinstance(payload, list) else payload.get("meetings", payload.get("items"))
        assert isinstance(items, list)
        assert '"_id"' not in json.dumps(payload)
