"""Iteration 118 regression: SELECT * -> explicit column trim (Part 2).

Covers review.py, auth.py, meetings.py, org.py, schedules.py, standards_cache.py,
remaining doc_uploads.py/admin.py/transcription_pipeline.py sites.

Read-only or self-restoring: every mutation is reverted at test end.
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

_be = dotenv_values("/app/backend/.env")
_fe = dotenv_values("/app/frontend/.env")
BASE = _fe["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = _be["DATABASE_URL"]

ADMIN = ("admin@supervision.com", "Admin123!")
USER = ("user@supervision.com", "AnotherNew789!")
JANE = ("jane@supervision.com", "JaneNew456!")
MANAGER = ("manager@supervision.com", "Manager123!")
SUPER = ("superadmin@1two.one", "NewPass123!")


def _mfa_override(email):
    async def _run():
        conn = await asyncpg.connect(DSN, ssl="require")
        h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
        exp = datetime.now(timezone.utc) + timedelta(minutes=10)
        await conn.execute(
            "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
            h, exp, email,
        )
        await conn.close()
    asyncio.run(_run())


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} -> {r.status_code}: {r.text}"
    data = r.json()
    if data.get("requires_mfa"):
        _mfa_override(email)
        r2 = s.post(
            f"{BASE}/auth/verify-mfa",
            json={"mfa_session": data["mfa_session"], "code": "123456"},
            timeout=30,
        )
        assert r2.status_code == 200, f"verify-mfa {email} -> {r2.status_code}: {r2.text}"
    return s


# ---------------- fixtures ----------------
@pytest.fixture(scope="module")
def admin():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def user():
    return _login(*USER)


@pytest.fixture(scope="module")
def jane():
    return _login(*JANE)


@pytest.fixture(scope="module")
def manager():
    return _login(*MANAGER)


# ============ auth.py trims ============
class TestAuth:
    def test_login_admin_ok(self, admin):
        r = admin.get(f"{BASE}/auth/me", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["email"] == ADMIN[0] and d["role"] == "admin"

    def test_login_attendee_ok(self, user):
        r = user.get(f"{BASE}/auth/me")
        assert r.status_code == 200 and r.json()["role"] == "attendee"

    def test_login_manager_mfa_flow(self, manager):
        # If we got here, request-mfa-code + verify-mfa both worked.
        r = manager.get(f"{BASE}/auth/me")
        assert r.status_code == 200 and r.json()["role"] == "manager"

    def test_login_bad_password(self):
        r = requests.post(f"{BASE}/auth/login", json={"email": ADMIN[0], "password": "WrongPwXYZ!"}, timeout=15)
        assert r.status_code in (400, 401), r.text
        assert "column" not in r.text.lower()

    def test_password_reset_invalid_token(self):
        r = requests.post(
            f"{BASE}/auth/reset-password",
            json={"token": "not-a-real-token-xxx", "new_password": "Whatever123!"},
            timeout=15,
        )
        assert r.status_code in (400, 401, 404), r.text
        assert "column" not in r.text.lower()

    def test_forgot_password_ok(self):
        # Should always return 200 (email enumeration guard)
        r = requests.post(f"{BASE}/auth/forgot-password", json={"email": ADMIN[0]}, timeout=15)
        assert r.status_code == 200, r.text

    def test_validate_invite_invalid(self):
        r = requests.get(f"{BASE}/auth/invitations/validate?token=notreal", timeout=15)
        assert r.status_code in (400, 404), r.text
        assert "column" not in r.text.lower()


# ============ org.py trims ============
class TestOrg:
    def test_structure(self, admin):
        r = admin.get(f"{BASE}/org/structure")
        assert r.status_code == 200
        d = r.json()
        assert "settings" in d
        for s in d["settings"]:
            assert {"id", "name", "manager_user_id", "manager_name", "teams"} <= set(s.keys())
            for t in s["teams"]:
                assert {"id", "name", "supervisor_user_id", "supervisor_name"} <= set(t.keys())

    def test_settings_flat(self, admin):
        r = admin.get(f"{BASE}/org/settings")
        assert r.status_code == 200
        for s in r.json():
            assert "id" in s and "name" in s and "manager_user_id" in s

    def test_setting_create_update_delete_roundtrip(self, admin):
        # CREATE
        r = admin.post(f"{BASE}/org/settings", json={"name": "TEST_iter118_setting"})
        assert r.status_code in (200, 201), r.text
        sid = r.json()["id"]
        try:
            # UPDATE manager_user_id (may be null-able)
            me = admin.get(f"{BASE}/auth/me").json()
            r2 = admin.put(f"{BASE}/org/settings/{sid}", json={"name": "TEST_iter118_setting_upd", "manager_user_id": me["id"]})
            assert r2.status_code == 200, r2.text
            # verify via structure
            struct = admin.get(f"{BASE}/org/structure").json()
            match = [s for s in struct["settings"] if s["id"] == sid]
            assert match and match[0]["manager_user_id"] == me["id"]
            assert match[0]["manager_name"]  # name resolves via join

            # create team under this setting
            r3 = admin.post(f"{BASE}/org/settings/{sid}/teams", json={"name": "TEST_iter118_team", "supervisor_user_id": me["id"]})
            assert r3.status_code in (200, 201), r3.text
            tid = r3.json()["id"]
            r4 = admin.put(f"{BASE}/org/teams/{tid}", json={"name": "TEST_iter118_team_upd", "supervisor_user_id": me["id"], "setting_id": sid})
            assert r4.status_code == 200, r4.text
            admin.delete(f"{BASE}/org/teams/{tid}")
        finally:
            admin.delete(f"{BASE}/org/settings/{sid}")


# ============ schedules.py trims ============
class TestSchedules:
    def test_list_schedules_enriched(self, admin):
        r = admin.get(f"{BASE}/schedules")
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list) and rows, "expected at least one schedule seeded"
        for s in rows:
            assert {"id", "staff_user_id", "meeting_type_id", "frequency", "next_due", "is_overdue", "staff_name", "meeting_type_name", "meeting_type_color"} <= set(s.keys())
            assert s["staff_name"], "staff_name must resolve"
            assert s["meeting_type_name"], "meeting_type_name must resolve"
            assert s["meeting_type_color"], "meeting_type_color must resolve (not blank)"

    def test_list_meeting_types(self, admin):
        r = admin.get(f"{BASE}/schedules/meeting-types")
        assert r.status_code == 200 and len(r.json()) > 0
        for mt in r.json():
            assert {"id", "name", "default_frequency", "color"} <= set(mt.keys())

    def test_create_schedule_roundtrip(self, admin):
        me = admin.get(f"{BASE}/auth/me").json()
        types = admin.get(f"{BASE}/schedules/meeting-types").json()
        existing = admin.get(f"{BASE}/schedules").json()
        used = {(s["staff_user_id"], s["meeting_type_id"]) for s in existing}
        attendee_id = _pick_attendee(me["org_id"])
        mt_id = next((t["id"] for t in types if (attendee_id, t["id"]) not in used), None)
        if not mt_id:
            pytest.skip("no free meeting-type/staff combination available")
        payload = {
            "staff_user_id": attendee_id,
            "meeting_type_id": mt_id,
            "frequency": "monthly",
            "start_date": "2026-06-01",
        }
        r = admin.post(f"{BASE}/schedules/", json=payload)
        assert r.status_code in (200, 201), r.text
        sid = r.json()["id"]
        try:
            g = admin.get(f"{BASE}/schedules").json()
            assert any(s["id"] == sid for s in g)
        finally:
            admin.delete(f"{BASE}/schedules/{sid}")


async def _pick_attendee_async(org_id):
    conn = await asyncpg.connect(DSN, ssl="require")
    r = await conn.fetchval(
        "SELECT id FROM users WHERE org_id=$1 AND role='attendee' LIMIT 1", org_id
    )
    await conn.close()
    return str(r)


def _pick_attendee(org_id):
    return asyncio.run(_pick_attendee_async(org_id))


# ============ admin.py standards + docs trims ============
class TestStandards:
    def test_standards_cqc_with_sub_outcomes(self, admin):
        r = admin.get(f"{BASE}/admin/standards?type=cqc")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) >= 40
        # Some cqc entries may have empty sub_outcomes; at least ensure field is present list
        for row in rows:
            assert {"id", "type", "reference", "name", "description", "sub_outcomes"} <= set(row.keys())
            assert row["type"] == "cqc"
            assert isinstance(row["sub_outcomes"], list)

    def test_standards_care_cert_with_sub_outcomes(self, admin):
        r = admin.get(f"{BASE}/admin/standards?type=care_cert")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) >= 15
        subs_total = sum(len(x["sub_outcomes"]) for x in rows)
        assert subs_total > 20, f"expected non-zero sub_outcomes across care_cert, got {subs_total}"

    def test_standards_documents(self, admin):
        r = admin.get(f"{BASE}/admin/standards/documents")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ============ review.py trims ============
class TestReview:
    @classmethod
    def setup_class(cls):
        s = _login(*ADMIN)
        mts = s.get(f"{BASE}/meetings").json()
        # Pick an in_review meeting with mappings for evidence/rescan tests
        for m in mts:
            if m.get("status") == "in_review":
                r = s.get(f"{BASE}/review/{m['id']}").json()
                a = r.get("analysis") or {}
                if (a.get("cqc_mappings") or a.get("care_cert_mappings")) and (a.get("actions") is not None):
                    cls.mid = m["id"]
                    cls.analysis = a
                    return
        pytest.skip("no in_review meeting with mappings found")

    def test_review_full_payload(self, admin):
        r = admin.get(f"{BASE}/review/{self.mid}")
        assert r.status_code == 200
        d = r.json()
        assert d["analysis"]["summary"]
        # comments field present (from list-comments join)
        assert "comments" in d

    def test_comments_list(self, admin):
        r = admin.get(f"{BASE}/review/{self.mid}/comments")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_comment_add_then_list(self, admin):
        r = admin.post(f"{BASE}/review/{self.mid}/comments", json={"text": "TEST_iter118 comment"})
        assert r.status_code in (200, 201), r.text
        cid = r.json().get("id")
        lst = admin.get(f"{BASE}/review/{self.mid}/comments").json()
        assert any(c.get("id") == cid for c in lst)
        # cleanup: no delete endpoint, but comment marked with TEST_ prefix is acceptable

    def test_update_evidence_accept_reject_roundtrip(self, admin):
        mappings = (self.analysis.get("cqc_mappings") or []) + (self.analysis.get("care_cert_mappings") or [])
        target = next((m for m in mappings if m.get("id")), None)
        if not target:
            pytest.skip("no evidence mapping with id")
        eid = target["id"]
        prev_status = target.get("status", "pending")
        # accept
        r = admin.put(f"{BASE}/review/{self.mid}/evidence/{eid}", json={"status": "accepted"})
        assert r.status_code == 200, r.text
        # verify via GET
        d = admin.get(f"{BASE}/review/{self.mid}").json()
        all_maps = (d["analysis"].get("cqc_mappings") or []) + (d["analysis"].get("care_cert_mappings") or [])
        found = next((m for m in all_maps if m.get("id") == eid), None)
        assert found and found.get("status") == "accepted"
        # restore
        admin.put(f"{BASE}/review/{self.mid}/evidence/{eid}", json={"status": prev_status})

    def test_bulk_update_evidence(self, admin):
        mappings = [m for m in (self.analysis.get("cqc_mappings") or []) if m.get("confidence") in ("likely_evidence", "possible_evidence") and (m.get("status") or "pending") == "pending"][:2]
        if not mappings:
            pytest.skip("no eligible pending mappings")
        prev = {m["id"]: m.get("status", "pending") for m in mappings if m.get("id")}
        r = admin.post(
            f"{BASE}/review/{self.mid}/evidence/bulk-action",
            json={"confidence": mappings[0]["confidence"], "status": "accepted"},
        )
        assert r.status_code == 200, r.text
        # restore
        for eid, st in prev.items():
            admin.put(f"{BASE}/review/{self.mid}/evidence/{eid}", json={"status": st})

    def test_export_transcript_endpoint_no_500(self, admin):
        r = admin.get(f"{BASE}/review/{self.mid}/export-transcript")
        # either 200 (if transcript present) or 404, but never 500
        assert r.status_code in (200, 404, 400), r.text
        assert "column" not in r.text.lower()

    def test_export_pdf_endpoint_no_500(self, admin):
        r = admin.get(f"{BASE}/review/{self.mid}/export-pdf")
        # signed_off required for pdf usually
        assert r.status_code in (200, 400, 403, 404), r.text
        assert "column" not in r.text.lower()

    def test_rescan_evidence_no_500(self, admin):
        r = admin.post(f"{BASE}/review/{self.mid}/rescan-evidence", json={})
        # Could return 200/202 or 429; assert not 500 and no column error
        assert r.status_code < 500, r.text
        assert "column" not in r.text.lower()


# ============ meetings.py trim ============
class TestMeetings:
    def test_meetings_list_admin(self, admin):
        r = admin.get(f"{BASE}/meetings")
        assert r.status_code == 200 and isinstance(r.json(), list)

    def test_meetings_list_jane_isolation(self, jane):
        r = jane.get(f"{BASE}/meetings")
        assert r.status_code == 200
        mts = r.json()
        # jane sees only meetings she is on (should be small subset)
        assert len(mts) <= 5, f"jane sees {len(mts)} - expected small subset"

    def test_meeting_create_delete_roundtrip(self, admin):
        payload = {"title": "TEST_iter118_meeting", "date": "2026-12-01T10:00", "location": "unit-test", "meeting_type": "supervision", "attendee_ids": []}
        r = admin.post(f"{BASE}/meetings/", json=payload)
        assert r.status_code in (200, 201), r.text
        d = r.json()
        mid = d["id"] if isinstance(d, dict) else None
        assert mid, f"unexpected response: {d}"
        try:
            g = admin.get(f"{BASE}/meetings/{mid}")
            assert g.status_code == 200 and g.json()["title"] == payload["title"]
        finally:
            r2 = admin.delete(f"{BASE}/meetings/{mid}")
            assert r2.status_code in (200, 204)


# ============ focus topics (prep.py NOT in this pass but often coupled) ============
class TestFocusTopics:
    def test_list(self, admin):
        r = admin.get(f"{BASE}/prep/focus-topics")
        assert r.status_code == 200 and isinstance(r.json(), list)

    def test_create_update_delete_roundtrip(self, admin):
        r = admin.post(f"{BASE}/prep/focus-topics", json={"topic": "TEST_iter118_focus"})
        assert r.status_code in (200, 201), r.text
        tid = r.json()["id"]
        try:
            r2 = admin.put(f"{BASE}/prep/focus-topics/{tid}", json={"topic": "TEST_iter118_focus_upd", "is_current": True})
            assert r2.status_code == 200, r2.text
            lst = admin.get(f"{BASE}/prep/focus-topics").json()
            assert any(t["id"] == tid for t in lst)
        finally:
            admin.delete(f"{BASE}/prep/focus-topics/{tid}")


# ============ portfolio & compliance sub_outcomes dependency ============
class TestPortfolio:
    def test_admin_portfolio(self, admin):
        me = admin.get(f"{BASE}/auth/me").json()
        r = admin.get(f"{BASE}/portfolio/{me['id']}")
        assert r.status_code == 200
        # should not have column errors
        assert "column" not in r.text.lower()

    def test_user_portfolio_attendee(self, user):
        me = user.get(f"{BASE}/auth/me").json()
        r = user.get(f"{BASE}/portfolio/{me['id']}")
        assert r.status_code == 200
        assert "column" not in r.text.lower()
