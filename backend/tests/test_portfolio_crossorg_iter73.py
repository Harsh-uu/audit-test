"""Iteration 73 — independent spot-check of the cross-org tenant fix in
routers/portfolio.py::_build_portfolio_data().

Run SERIALLY (no xdist):
  cd /app/backend && python3 -m pytest tests/test_portfolio_crossorg_iter73.py -v -o addopts=""
"""
import asyncio
import time
from datetime import datetime, timezone, timedelta

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

be = dotenv_values("/app/backend/.env")
fe = dotenv_values("/app/frontend/.env")
BASE = (fe.get("REACT_APP_BACKEND_URL") or "").rstrip("/") + "/api"
DSN = be["DATABASE_URL"]

MGR_EMAIL, MGR_PW = "manager@supervision.com", "Manager123!"
ORGB_MGR_EMAIL, ORGB_MGR_PW = "test-orgb-manager@example.com", "OrgBManager123!"
ORGB_MGR_ID = "99999999-8888-7777-6666-555555555555"
ORGB_ORG_ID = "3628a11d-36b8-42df-9d46-0479450ee22c"

DIANE_ID = "2412f428-8452-42ad-9905-d0cf9341ac30"
CONNOR_ID = "60613cdc-52a6-4fef-8873-2becd059607a"


async def _q(sql, *args):
    conn = await asyncpg.connect(DSN, ssl="require")
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


async def _exec(sql, *args):
    conn = await asyncpg.connect(DSN, ssl="require")
    try:
        return await conn.execute(sql, *args)
    finally:
        await conn.close()


async def _force_mfa(email):
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    rows = await _q("SELECT id FROM public.users WHERE email=$1", email)
    await _exec(
        "UPDATE public.users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, exp, email)
    if rows:
        await _exec("DELETE FROM login_attempts WHERE identifier=$1", f"mfa_uid:{rows[0]['id']}")


_SESSIONS = {}


def _login(email, password):
    if email in _SESSIONS:
        return _SESSIONS[email]
    asyncio.run(_exec("DELETE FROM login_attempts"))
    s = requests.Session()
    r = None
    for _ in range(4):
        r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=60)
        if r.status_code < 500:
            break
        time.sleep(4)
    if r.status_code != 200:
        pytest.fail(f"login failed for {email}: {r.status_code} {r.text[:300]}")
    data = r.json()
    if data.get("requires_mfa"):
        asyncio.run(_force_mfa(email))
        r2 = s.post(f"{BASE}/auth/verify-mfa",
                    json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=60)
        if r2.status_code != 200:
            pytest.fail(f"MFA verify failed for {email}: {r2.status_code} {r2.text[:300]}")
    me = s.get(f"{BASE}/auth/me", timeout=60)
    assert me.status_code == 200, f"/auth/me failed: {me.status_code}"
    _SESSIONS[email] = (s, me.json())
    return _SESSIONS[email]


@pytest.fixture(scope="module")
def mgr_a():
    return _login(MGR_EMAIL, MGR_PW)


@pytest.fixture(scope="module")
def mgr_b():
    return _login(ORGB_MGR_EMAIL, ORGB_MGR_PW)


# ── fixture / precondition checks ────────────────────────────────────────────
class TestPreconditions:
    def test_orgb_manager_has_real_distinct_org(self, mgr_a, mgr_b):
        _, me_a = mgr_a
        _, me_b = mgr_b
        assert me_b["id"] == ORGB_MGR_ID
        assert me_b["role"] == "manager"
        assert me_b.get("org_id") == ORGB_ORG_ID, f"org B manager org_id={me_b.get('org_id')}"
        assert me_a.get("org_id"), "org A manager must have a real org_id"
        assert me_a["org_id"] != me_b["org_id"]

    def test_connor_org_id_is_null(self):
        rows = asyncio.run(_q("SELECT id, org_id FROM public.users WHERE id=$1", CONNOR_ID))
        assert rows, "Connor Repro fixture missing — run python tests/seed_iter72.py"
        assert rows[0]["org_id"] is None, f"Connor org_id should be NULL, got {rows[0]['org_id']}"

    def test_orgb_manager_scope_is_org_level(self):
        # get_manager_scope(): no team_id and no setting_id ⇒ level 'org' ⇒ the
        # scoped-manager 403 gate is skipped, so the tenant check is the ONLY gate.
        rows = asyncio.run(_q(
            "SELECT team_id, setting_id FROM public.users WHERE id=$1", ORGB_MGR_ID))
        assert rows, "org B manager fixture missing"
        assert not rows[0]["team_id"] and not rows[0]["setting_id"], (
            "org B manager is scope-restricted; cross-org tests would pass for the wrong reason")


# ── cross-org denial ─────────────────────────────────────────────────────────
class TestCrossOrgDenied:
    def test_view_orga_staff_denied(self, mgr_b):
        s, _ = mgr_b
        r = s.get(f"{BASE}/portfolio/{DIANE_ID}", timeout=60)
        assert r.status_code == 404, f"cross-org leak: {r.status_code} {r.text[:300]}"

    def test_export_pdf_orga_staff_denied(self, mgr_b):
        s, _ = mgr_b
        r = s.get(f"{BASE}/portfolio/{DIANE_ID}/export-pdf", timeout=90)
        assert r.status_code == 404, f"cross-org PDF leak: {r.status_code}"
        assert b"%PDF" not in r.content[:8]

    def test_view_null_org_user_denied_for_unrelated_org(self, mgr_b):
        s, _ = mgr_b
        r = s.get(f"{BASE}/portfolio/{CONNOR_ID}", timeout=60)
        assert r.status_code == 404, f"null-org user leaked cross-org: {r.status_code} {r.text[:300]}"

    def test_export_pdf_null_org_user_denied_for_unrelated_org(self, mgr_b):
        s, _ = mgr_b
        r = s.get(f"{BASE}/portfolio/{CONNOR_ID}/export-pdf", timeout=90)
        assert r.status_code == 404, f"null-org PDF leaked cross-org: {r.status_code}"


# ── same-org / related-org still works (no regression) ───────────────────────
class TestSameOrgStillWorks:
    def test_same_org_staff_portfolio_200(self, mgr_a):
        s, _ = mgr_a
        r = s.get(f"{BASE}/portfolio/{DIANE_ID}", timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        d = r.json()
        assert d["user"]["id"] == DIANE_ID
        assert d["user"]["email"]
        assert "'_id'" not in str(d), "MongoDB _id leaked in response"
        assert isinstance(d["meetings"], list)
        assert d["stats"]["total_meetings"] == len(d["meetings"])

    def test_same_org_export_pdf_200(self, mgr_a):
        s, _ = mgr_a
        r = s.get(f"{BASE}/portfolio/{DIANE_ID}/export-pdf", timeout=90)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        assert r.content[:4] == b"%PDF"

    def test_null_org_user_visible_to_related_org_manager(self, mgr_a):
        s, _ = mgr_a
        r = s.get(f"{BASE}/portfolio/{CONNOR_ID}", timeout=60)
        assert r.status_code == 200, f"null-org regression: {r.status_code} {r.text[:300]}"
        d = r.json()
        assert d["user"]["id"] == CONNOR_ID
        assert len(d["meetings"]) >= 1, "expected Connor's signed-off meeting to be listed"

    def test_null_org_user_export_pdf_related_org_manager(self, mgr_a):
        s, _ = mgr_a
        r = s.get(f"{BASE}/portfolio/{CONNOR_ID}/export-pdf", timeout=90)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        assert r.content[:4] == b"%PDF"

    def test_unknown_user_404(self, mgr_a):
        s, _ = mgr_a
        r = s.get(f"{BASE}/portfolio/00000000-0000-0000-0000-000000000000", timeout=60)
        assert r.status_code == 404


# ── org B manager can still see its OWN org data (fix isn't a blanket deny) ──
class TestOrgBOwnDataUnaffected:
    def test_orgb_manager_own_portfolio_200(self, mgr_b):
        s, _ = mgr_b
        r = s.get(f"{BASE}/portfolio/{ORGB_MGR_ID}", timeout=60)
        assert r.status_code == 200, f"org B manager denied own portfolio: {r.status_code} {r.text[:300]}"
        assert r.json()["user"]["id"] == ORGB_MGR_ID
