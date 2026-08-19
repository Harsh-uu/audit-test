"""Iteration 72 regression suite.

BUG 1 — prep context cross-supervisee leak (routers/prep.py::_derive_supervisee_ids)
BUG 2 — portfolio 404 for users with NULL org_id (routers/portfolio.py::_build_portfolio_data)
Plus cross-org authorization boundary checks on /api/portfolio/{user_id}.
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

MGR_ID = "465c5101-bbc8-4f26-adaa-c906d3324dd5"
DIANE_ID = "2412f428-8452-42ad-9905-d0cf9341ac30"
MARIA_ID = "f742ddf2-bfb5-44e5-8cd8-14eebb2d0cc4"

DIANE_NEW_MEETING = "1f6ba2ef-d864-48d9-9fb2-0a644ec46bc1"
DIANE_PAST_MEETING = "d272da8e-d183-4354-a7eb-a38e5c7f586e"
MARIA_PAST_1 = "27673540-cb15-4a80-8ea4-ead19fdcef35"
MARIA_PAST_2 = "4d646092-f98b-464a-ad26-96494c54fc8a"

CONNOR_ID = "60613cdc-52a6-4fef-8873-2becd059607a"
CONNOR_MEETING = "11111111-2222-3333-4444-555555555555"
DEMO_USER_ID = "831bdaef-14ca-49ed-8fb0-9b8d36bc1ef6"


# ── auth helpers ─────────────────────────────────────────────────────────────
async def _force_mfa(email):
    conn = await asyncpg.connect(DSN, ssl="require")
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    row = await conn.fetchrow("SELECT id FROM public.users WHERE email=$1", email)
    await conn.execute(
        "UPDATE public.users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, exp, email)
    if row:
        await conn.execute("DELETE FROM login_attempts WHERE identifier=$1", f"mfa_uid:{row['id']}")
    await conn.close()


async def _clear_login_attempts():
    conn = await asyncpg.connect(DSN, ssl="require")
    await conn.execute("DELETE FROM login_attempts")
    await conn.close()


_SESSIONS = {}


def _login(email, password):
    if email in _SESSIONS:
        return _SESSIONS[email]
    asyncio.run(_clear_login_attempts())
    s = requests.Session()
    r = None
    for _ in range(4):  # retry transient CDN 5xx
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
    assert me.status_code == 200, f"/auth/me failed: {me.status_code} {me.text[:200]}"
    _SESSIONS[email] = (s, me.json())
    return _SESSIONS[email]


@pytest.fixture(scope="module")
def mgr():
    s, me = _login(MGR_EMAIL, MGR_PW)
    return s


@pytest.fixture(scope="module")
def orgb_mgr():
    s, me = _login(ORGB_MGR_EMAIL, ORGB_MGR_PW)
    return s


@pytest.fixture(scope="module")
def created_meeting_ids():
    ids = []
    yield ids
    conn_dsn = DSN
    async def _rm():
        c = await asyncpg.connect(conn_dsn, ssl="require")
        for mid in ids:
            await c.execute("DELETE FROM meeting_prep WHERE meeting_id=$1", mid)
            await c.execute("DELETE FROM meetings WHERE id=$1", mid)
        await c.close()
    asyncio.run(_rm())


# ── BUG 1: prep context ──────────────────────────────────────────────────────
class TestPrepContextLeak:

    def test_precondition_fixture_shape(self, mgr):
        """Diane's new meeting must have the manager as attendee and NULL sign_off_manager_id."""
        r = mgr.get(f"{BASE}/meetings/{DIANE_NEW_MEETING}", timeout=60)
        assert r.status_code == 200, r.text[:300]
        m = r.json()
        assert m.get("sign_off_manager_id") in (None, ""), "fixture must have NULL sign_off_manager_id"
        ids = [a["user_id"] for a in m.get("attendees", [])]
        assert MGR_ID in ids and DIANE_ID in ids, f"unexpected attendees: {ids}"

    def test_context_sources_exclude_other_supervisee(self, mgr):
        r = mgr.get(f"{BASE}/prep/{DIANE_NEW_MEETING}/context", timeout=90)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        prev_ids = [s["source_id"] for s in data["sources"] if s["source_type"] == "previous_meeting"]
        assert DIANE_PAST_MEETING in prev_ids, f"Diane's own past meeting missing: {prev_ids}"
        assert MARIA_PAST_1 not in prev_ids, "LEAK: Maria past meeting 1 present"
        assert MARIA_PAST_2 not in prev_ids, "LEAK: Maria past meeting 2 present"
        assert len(prev_ids) == 1, f"expected exactly 1 previous meeting source, got {prev_ids}"
        labels = " | ".join(s.get("label", "") for s in data["sources"])
        assert "Maria" not in labels, f"LEAK: Maria referenced in source labels: {labels}"

    def test_supervisees_lists_only_diane(self, mgr):
        r = mgr.get(f"{BASE}/prep/{DIANE_NEW_MEETING}/context", timeout=90)
        assert r.status_code == 200
        sup = r.json()["supervisees"]
        assert [s["user_id"] for s in sup] == [DIANE_ID], sup
        assert sup[0]["name"] == "Diane Fletcher"
        assert MGR_ID not in [s["user_id"] for s in sup], "manager wrongly listed as supervisee"

    def test_no_mongo_objectid_in_response(self, mgr):
        r = mgr.get(f"{BASE}/prep/{DIANE_NEW_MEETING}/context", timeout=90)
        assert '"_id"' not in r.text

    # regression — genuine multi-supervisee group session still gets both histories
    def test_group_supervision_includes_both_supervisees(self, mgr, created_meeting_ids):
        r = mgr.post(f"{BASE}/meetings/", json={
            "title": "TEST_ Group supervision Diane + Maria",
            "date": datetime.now(timezone.utc).isoformat(),
            "meeting_type": "supervision",
            "attendee_ids": [DIANE_ID, MARIA_ID],
        }, timeout=60)
        assert r.status_code in (200, 201), r.text[:400]
        mid = r.json().get("id") or r.json().get("meeting", {}).get("id")
        assert mid, r.text[:300]
        created_meeting_ids.append(mid)

        ctx = mgr.get(f"{BASE}/prep/{mid}/context", timeout=90)
        assert ctx.status_code == 200, ctx.text[:400]
        data = ctx.json()
        sup_ids = sorted(s["user_id"] for s in data["supervisees"])
        assert sup_ids == sorted([DIANE_ID, MARIA_ID]), data["supervisees"]
        prev_ids = {s["source_id"] for s in data["sources"] if s["source_type"] == "previous_meeting"}
        assert DIANE_PAST_MEETING in prev_ids, prev_ids
        assert MARIA_PAST_1 in prev_ids and MARIA_PAST_2 in prev_ids, prev_ids

    # regression — manager-only meeting yields no supervisees and no personal docs
    def test_manager_only_meeting_has_no_sources(self, mgr, created_meeting_ids):
        r = mgr.post(f"{BASE}/meetings/", json={
            "title": "TEST_ Manager only meeting",
            "date": datetime.now(timezone.utc).isoformat(),
            "meeting_type": "supervision",
            "attendee_ids": [MGR_ID],
        }, timeout=60)
        assert r.status_code in (200, 201), r.text[:400]
        mid = r.json().get("id")
        created_meeting_ids.append(mid)
        ctx = mgr.get(f"{BASE}/prep/{mid}/context", timeout=90)
        assert ctx.status_code == 200, ctx.text[:300]
        data = ctx.json()
        assert data["supervisees"] == [], data["supervisees"]
        prev = [s for s in data["sources"] if s["source_type"] in ("previous_meeting", "doc_upload")]
        assert prev == [], f"personal sources leaked for a manager-only meeting: {prev}"

    def test_generated_prep_does_not_reference_other_supervisee(self, mgr):
        r = mgr.post(f"{BASE}/prep/{DIANE_NEW_MEETING}/generate",
                     json={"focus_topic": "Wellbeing and caseload"}, timeout=90)
        if r.status_code == 429:
            pytest.skip("rate limited on prep generate")
        assert r.status_code == 200, r.text[:400]
        status, sections = None, []
        for _ in range(30):
            time.sleep(5)
            g = mgr.get(f"{BASE}/prep/{DIANE_NEW_MEETING}", timeout=60)
            assert g.status_code == 200, g.text[:300]
            status = g.json().get("gen_status")
            sections = g.json().get("sections", [])
            if status in ("done", "failed"):
                break
        assert status == "done", f"generation ended with status={status}"
        blob = str(sections)
        assert "Maria" not in blob, f"LEAK: generated prep references Maria — {blob[:800]}"
        assert len(sections) > 0, "no sections generated"


# ── BUG 2: portfolio ─────────────────────────────────────────────────────────
class TestPortfolioNullOrg:

    def test_portfolio_for_null_org_user(self, mgr):
        r = mgr.get(f"{BASE}/portfolio/{CONNOR_ID}", timeout=90)
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:300]}"
        d = r.json()
        assert d["user"]["id"] == CONNOR_ID
        assert d["user"]["name"] == "Connor Repro"
        assert "stats" in d and isinstance(d["stats"]["total_meetings"], int)
        for key in ("cqc_summary", "care_cert_summary", "custom_summary", "meetings"):
            assert key in d, f"missing {key}"

    def test_null_org_user_meetings_are_listed(self, mgr):
        r = mgr.get(f"{BASE}/portfolio/{CONNOR_ID}", timeout=90)
        assert r.status_code == 200
        d = r.json()
        ids = [m["id"] for m in d["meetings"]]
        assert CONNOR_MEETING in ids, f"seeded signed-off meeting not shown: {ids}"
        assert d["stats"]["total_meetings"] >= 1
        assert d["stats"]["last_meeting_date"]

    def test_portfolio_regression_normal_user(self, mgr):
        r = mgr.get(f"{BASE}/portfolio/{DIANE_ID}", timeout=90)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["user"]["name"] == "Diane Fletcher"
        ids = [m["id"] for m in d["meetings"]]
        assert DIANE_PAST_MEETING in ids, ids
        assert MARIA_PAST_1 not in ids and MARIA_PAST_2 not in ids, ids
        assert d["stats"]["total_meetings"] == len(d["meetings"])

    def test_portfolio_unknown_user_404(self, mgr):
        r = mgr.get(f"{BASE}/portfolio/00000000-0000-0000-0000-000000000000", timeout=60)
        assert r.status_code == 404, f"{r.status_code} {r.text[:200]}"

    def test_portfolio_unauthenticated(self):
        r = requests.get(f"{BASE}/portfolio/{DIANE_ID}", timeout=60)
        assert r.status_code in (401, 403), r.status_code

    def test_attendee_cannot_view_other_portfolio(self):
        s, _ = _login("user@supervision.com", "Staff123!")
        r = s.get(f"{BASE}/portfolio/{DIANE_ID}", timeout=60)
        assert r.status_code == 403, f"{r.status_code} {r.text[:200]}"

    def test_attendee_can_view_own_portfolio(self):
        s, _ = _login("user@supervision.com", "Staff123!")
        r = s.get(f"{BASE}/portfolio/{DEMO_USER_ID}", timeout=90)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["user"]["id"] == DEMO_USER_ID


# ── cross-org isolation ──────────────────────────────────────────────────────
class TestPortfolioCrossOrg:

    def test_orgb_manager_cannot_view_orga_staff_portfolio(self, orgb_mgr):
        r = orgb_mgr.get(f"{BASE}/portfolio/{DIANE_ID}", timeout=90)
        assert r.status_code in (403, 404), (
            f"CROSS-ORG LEAK: org B manager got {r.status_code} for org A staff portfolio: {r.text[:400]}")

    def test_orgb_manager_cannot_view_null_org_user_portfolio(self, orgb_mgr):
        r = orgb_mgr.get(f"{BASE}/portfolio/{CONNOR_ID}", timeout=90)
        assert r.status_code in (403, 404), (
            f"CROSS-ORG LEAK: org B manager got {r.status_code} for null-org user portfolio: {r.text[:400]}")

    def test_orgb_manager_cannot_export_orga_staff_portfolio_pdf(self, orgb_mgr):
        r = orgb_mgr.get(f"{BASE}/portfolio/{DIANE_ID}/export-pdf", timeout=120)
        assert r.status_code in (403, 404), (
            f"CROSS-ORG LEAK on export-pdf: {r.status_code}, {len(r.content)} bytes")
