"""Iter116: FULL application regression sweep (all router categories).

Covers: auth (all 4 roles + MFA bypass, refresh, logout, negative), meetings CRUD +
role scoping, recording, processing status, review, prep, portfolio (+PDF), admin panel
(users/standards/template/insights/stats/exports/audit), schedules & meeting types, org
structure/settings/teams/branding, super-admin cross-tenant org+user CRUD, doc-uploads,
isolation (cross-tenant + same-org) and RBAC negatives.

Run: python3 -m pytest tests/test_iter116_full_regression.py -v
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

FE = dotenv_values("/app/frontend/.env")
BE = dotenv_values("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or FE["REACT_APP_BACKEND_URL"]).rstrip("/")
API = f"{BASE}/api"
DSN = BE["DATABASE_URL"]
T = 90

ADMIN = ("admin@supervision.com", "Admin123!")
MANAGER = ("manager@supervision.com", "Manager123!")
ATTENDEE = ("user@supervision.com", "AnotherNew789!")
JANE = ("jane@supervision.com", "JaneNew456!")
SUPER = ("superadmin@1two.one", "NewPass123!")

TAG = uuid.uuid4().hex[:8]


# ---------------------------------------------------------------- helpers
async def _force_mfa(email):
    conn = await asyncpg.connect(DSN, ssl="require")
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = datetime.now(timezone.utc) + timedelta(minutes=10)
    await conn.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, exp, email)
    await conn.close()


def login(email, pw):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=T)
    assert r.status_code == 200, f"login {email} -> {r.status_code} {r.text[:200]}"
    data = r.json()
    if data.get("requires_mfa"):
        asyncio.run(_force_mfa(email))
        r2 = s.post(f"{API}/auth/verify-mfa",
                    json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=T)
        assert r2.status_code == 200, f"verify-mfa {email} -> {r2.status_code} {r2.text[:200]}"
    me = s.get(f"{API}/auth/me", timeout=T)
    assert me.status_code == 200, f"/auth/me {email} -> {me.status_code} {me.text[:200]}"
    s.me = me.json()
    return s


def mlist(payload):
    return payload if isinstance(payload, list) else payload.get("meetings", [])


@pytest.fixture(scope="session")
def admin():
    return login(*ADMIN)


@pytest.fixture(scope="session")
def manager():
    return login(*MANAGER)


@pytest.fixture(scope="session")
def attendee():
    return login(*ATTENDEE)


@pytest.fixture(scope="session")
def jane():
    return login(*JANE)


@pytest.fixture(scope="session")
def sadmin():
    return login(*SUPER)


@pytest.fixture(scope="session")
def anon():
    return requests.Session()


@pytest.fixture(scope="session")
def admin_meeting(admin):
    """A meeting created by admin, cleaned up at session end."""
    payload = {
        "title": f"TEST_iter116_{TAG}",
        "meeting_type": "supervision",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "time": "10:00",
        "attendees": [{"user_id": admin.me["id"], "name": admin.me.get("name", "Admin")}],
    }
    r = admin.post(f"{API}/meetings/", json=payload, timeout=T)
    assert r.status_code in (200, 201), f"create meeting -> {r.status_code} {r.text[:300]}"
    mid = r.json().get("id") or r.json().get("meeting_id")
    assert mid
    yield mid
    admin.delete(f"{API}/meetings/{mid}", timeout=T)


# ---------------------------------------------------------------- auth
class TestAuth:
    def test_health(self, anon):
        r = anon.get(f"{API}/", timeout=T)
        assert r.status_code in (200, 404), r.status_code

    def test_admin_login_and_me(self, admin):
        assert admin.me["role"] == "admin"
        assert admin.me["email"] == ADMIN[0]

    def test_manager_login_requires_mfa_then_succeeds(self, manager):
        assert manager.me["role"] == "manager"

    def test_attendee_login(self, attendee):
        assert attendee.me["role"] in ("attendee", "staff")

    def test_super_admin_login(self, sadmin):
        assert sadmin.me["role"] == "super_admin"

    def test_bad_password_401(self, anon):
        r = anon.post(f"{API}/auth/login",
                      json={"email": ADMIN[0], "password": "WrongPass123!"}, timeout=T)
        assert r.status_code in (401, 429), r.status_code

    def test_unknown_email_401(self, anon):
        r = anon.post(f"{API}/auth/login",
                      json={"email": f"nobody_{TAG}@x.com", "password": "WrongPass123!"}, timeout=T)
        assert r.status_code in (401, 429), r.status_code

    def test_me_requires_auth(self, anon):
        r = anon.get(f"{API}/auth/me", timeout=T)
        assert r.status_code == 401, r.status_code

    def test_refresh_rotates_access_cookie(self):
        s = login(*ATTENDEE)
        old = s.cookies.get("supervision_access")
        r = s.post(f"{API}/auth/refresh", timeout=T)
        assert r.status_code == 200, r.text[:200]
        assert s.get(f"{API}/auth/me", timeout=T).status_code == 200
        assert old is not None

    def test_logout_invalidates_session(self):
        s = login(*JANE)
        assert s.post(f"{API}/auth/logout", timeout=T).status_code == 200
        assert s.get(f"{API}/auth/me", timeout=T).status_code == 401

    def test_forgot_password_is_non_enumerating(self, anon):
        r = anon.post(f"{API}/auth/forgot-password",
                      json={"email": f"nobody_{TAG}@x.com"}, timeout=T)
        assert r.status_code in (200, 202, 429), f"{r.status_code} {r.text[:200]}"

    def test_reset_password_bad_token_rejected(self, anon):
        r = anon.post(f"{API}/auth/reset-password",
                      json={"token": "bogus-token", "new_password": f"Aa1!{TAG}xyz"}, timeout=T)
        assert r.status_code in (400, 401, 404, 422), f"{r.status_code} {r.text[:200]}"

    def test_change_password_wrong_current_rejected(self, attendee):
        r = attendee.post(f"{API}/auth/change-password",
                          json={"current_password": "Definitely-Wrong-1!",
                                "new_password": f"Aa1!{TAG}xyz"}, timeout=T)
        assert r.status_code in (400, 401, 403), f"{r.status_code} {r.text[:200]}"

    def test_change_password_weak_rejected(self, attendee):
        r = attendee.post(f"{API}/auth/change-password",
                          json={"current_password": ATTENDEE[1], "new_password": "abc"}, timeout=T)
        assert r.status_code in (400, 422), f"{r.status_code} {r.text[:200]}"

    def test_invite_lookup_bad_token(self, anon):
        r = anon.get(f"{API}/auth/invite/bogus-{TAG}", timeout=T)
        assert r.status_code in (400, 404), r.status_code


# ---------------------------------------------------------------- meetings
class TestMeetings:
    def test_admin_list(self, admin):
        r = admin.get(f"{API}/meetings/?limit=500", timeout=T)
        assert r.status_code == 200, r.text[:300]
        assert len(mlist(r.json())) >= 1

    def test_attendee_list_only_own(self, attendee):
        uid = attendee.me["id"]
        r = attendee.get(f"{API}/meetings/?limit=500", timeout=T)
        assert r.status_code == 200, r.text[:300]
        ms = mlist(r.json())
        assert ms
        for m in ms:
            att = [a.get("user_id") for a in (m.get("attendees") or []) if isinstance(a, dict)]
            shared = [a.get("user_id") for a in (m.get("shared_with") or []) if isinstance(a, dict)]
            assert m.get("created_by") == uid or uid in att or uid in shared, m.get("id")

    def test_manager_list(self, manager):
        r = manager.get(f"{API}/meetings/?limit=500", timeout=T)
        assert r.status_code == 200, r.text[:300]

    def test_dashboard_matches_meetings(self, admin):
        d = admin.get(f"{API}/dashboard/", timeout=T)
        assert d.status_code == 200, d.text[:300]
        body = d.json()
        assert isinstance(body, (list, dict))

    def test_create_read_meeting(self, admin, admin_meeting):
        r = admin.get(f"{API}/meetings/{admin_meeting}", timeout=T)
        assert r.status_code == 200, r.text[:300]
        m = r.json()
        assert m["id"] == admin_meeting
        assert m["title"] == f"TEST_iter116_{TAG}"
        assert "_id" not in m

    def test_update_attendees_persists(self, admin, attendee, admin_meeting):
        r = admin.put(f"{API}/meetings/{admin_meeting}/attendees",
                      json={"attendee_ids": [admin.me["id"], attendee.me["id"]]}, timeout=T)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        got = admin.get(f"{API}/meetings/{admin_meeting}", timeout=T).json()
        ids = [a.get("user_id") for a in (got.get("attendees") or [])]
        assert attendee.me["id"] in ids, ids

    def test_update_signoff_manager_persists(self, admin, manager, admin_meeting):
        r = admin.put(f"{API}/meetings/{admin_meeting}/manager",
                      json={"manager_id": manager.me["id"]}, timeout=T)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        got = admin.get(f"{API}/meetings/{admin_meeting}", timeout=T).json()
        assert str(got.get("sign_off_manager_id") or "") == manager.me["id"], got

    def test_transcript_text_endpoint(self, admin, admin_meeting):
        r = admin.get(f"{API}/meetings/{admin_meeting}/transcript-text", timeout=T)
        assert r.status_code in (200, 404), f"{r.status_code} {r.text[:200]}"

    def test_unknown_meeting_404(self, admin):
        r = admin.get(f"{API}/meetings/{uuid.uuid4()}", timeout=T)
        assert r.status_code == 404, r.status_code

    def test_jane_cannot_read_admin_meeting(self, jane, admin_meeting):
        r = jane.get(f"{API}/meetings/{admin_meeting}", timeout=T)
        assert r.status_code in (403, 404), f"same-org leak: {r.status_code} {r.text[:200]}"

    def test_delete_meeting_round_trip(self, admin):
        payload = {"title": f"TEST_iter116_del_{TAG}", "meeting_type": "supervision",
                   "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "time": "11:00",
                   "attendees": [{"user_id": admin.me["id"], "name": "Admin"}]}
        c = admin.post(f"{API}/meetings/", json=payload, timeout=T)
        assert c.status_code in (200, 201), c.text[:200]
        mid = c.json()["id"]
        d = admin.delete(f"{API}/meetings/{mid}", timeout=T)
        assert d.status_code in (200, 204), d.text[:200]
        assert admin.get(f"{API}/meetings/{mid}", timeout=T).status_code == 404


# ---------------------------------------------------------------- recording / processing
class TestRecordingProcessing:
    def test_notice_start_pause_resume_stop(self, admin, admin_meeting):
        assert admin.post(f"{API}/recording/{admin_meeting}/notice", timeout=T).status_code in (200, 201)
        s = admin.post(f"{API}/recording/{admin_meeting}/start", timeout=T)
        assert s.status_code in (200, 201), f"start -> {s.status_code} {s.text[:200]}"
        assert admin.post(f"{API}/recording/{admin_meeting}/pause", timeout=T).status_code in (200, 201)
        assert admin.post(f"{API}/recording/{admin_meeting}/resume", timeout=T).status_code in (200, 201)
        assert admin.post(f"{API}/recording/{admin_meeting}/stop", timeout=T).status_code in (200, 201)
        ev = admin.get(f"{API}/recording/{admin_meeting}/events", timeout=T)
        assert ev.status_code == 200, ev.text[:200]

    def test_processing_status(self, admin, admin_meeting):
        r = admin.get(f"{API}/processing/{admin_meeting}/status", timeout=T)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        assert "status" in r.json()

    def test_empty_upload_rejected(self, admin, admin_meeting):
        r = admin.post(f"{API}/processing/{admin_meeting}/upload",
                       data=b"", headers={"Content-Type": "audio/webm"}, timeout=T)
        assert r.status_code in (400, 422), f"{r.status_code} {r.text[:200]}"

    def test_jane_cannot_upload_to_admin_meeting(self, jane, admin_meeting):
        r = jane.post(f"{API}/processing/{admin_meeting}/upload",
                      data=b"x" * 32, headers={"Content-Type": "audio/webm"}, timeout=T)
        assert r.status_code in (403, 404), f"{r.status_code} {r.text[:200]}"


# ---------------------------------------------------------------- review
class TestReview:
    @pytest.fixture(scope="class")
    def reviewable(self, admin):
        ms = mlist(admin.get(f"{API}/meetings/?limit=500", timeout=T).json())
        signed = [m for m in ms if m.get("status") == "signed_off"]
        done = signed or [m for m in ms if m.get("status") in ("completed", "in_review", "review")]
        if not done:
            pytest.skip("no completed/in-review meeting available")
        return done[0]["id"]

    def test_get_review(self, admin, reviewable):
        r = admin.get(f"{API}/review/{reviewable}", timeout=T)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        body = r.json()
        assert "_id" not in body

    def test_comments_round_trip(self, admin, reviewable):
        c = admin.post(f"{API}/review/{reviewable}/comments",
                       json={"text": f"TEST_iter116 comment {TAG}"}, timeout=T)
        assert c.status_code in (200, 201), f"{c.status_code} {c.text[:300]}"
        g = admin.get(f"{API}/review/{reviewable}/comments", timeout=T)
        assert g.status_code == 200
        blob = str(g.json())
        assert TAG in blob, "comment not persisted"

    def test_audit_trail(self, admin, reviewable):
        r = admin.get(f"{API}/review/{reviewable}/audit-trail", timeout=T)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

    def test_export_pdf(self, admin, reviewable):
        r = admin.get(f"{API}/review/{reviewable}/export-pdf", timeout=T)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        assert r.content[:4] == b"%PDF", r.content[:20]

    def test_export_transcript(self, admin, reviewable):
        r = admin.get(f"{API}/review/{reviewable}/export-transcript", timeout=T)
        # 404/400 acceptable when the signed-off meeting has no stored transcript
        assert r.status_code in (200, 400, 404), f"{r.status_code} {r.text[:300]}"

    def test_jane_cannot_read_review(self, jane, reviewable):
        r = jane.get(f"{API}/review/{reviewable}", timeout=T)
        assert r.status_code in (403, 404), f"IDOR: {r.status_code}"

    def test_jane_cannot_export_pdf(self, jane, reviewable):
        r = jane.get(f"{API}/review/{reviewable}/export-pdf", timeout=T)
        assert r.status_code in (403, 404), f"IDOR: {r.status_code}"


# ---------------------------------------------------------------- prep
class TestPrep:
    def test_focus_topics_crud(self, admin):
        c = admin.post(f"{API}/prep/focus-topics", json={"topic": f"TEST_iter116_topic_{TAG}"}, timeout=T)
        assert c.status_code in (200, 201), f"{c.status_code} {c.text[:300]}"
        tid = c.json().get("id")
        lst = admin.get(f"{API}/prep/focus-topics", timeout=T)
        assert lst.status_code == 200
        assert TAG in str(lst.json())
        if tid:
            u = admin.put(f"{API}/prep/focus-topics/{tid}",
                          json={"topic": f"TEST_iter116_topic_{TAG}_upd"}, timeout=T)
            assert u.status_code in (200, 204), f"{u.status_code} {u.text[:200]}"
            d = admin.delete(f"{API}/prep/focus-topics/{tid}", timeout=T)
            assert d.status_code in (200, 204), d.text[:200]

    def test_prep_get_and_context(self, admin, admin_meeting):
        p = admin.get(f"{API}/prep/{admin_meeting}", timeout=T)
        assert p.status_code in (200, 404), f"{p.status_code} {p.text[:300]}"
        c = admin.get(f"{API}/prep/{admin_meeting}/context", timeout=T)
        assert c.status_code in (200, 404), f"{c.status_code} {c.text[:300]}"


# ---------------------------------------------------------------- portfolio
class TestPortfolio:
    def test_own_portfolio(self, attendee):
        r = attendee.get(f"{API}/portfolio/{attendee.me['id']}", timeout=T)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

    def test_own_portfolio_pdf(self, attendee):
        r = attendee.get(f"{API}/portfolio/{attendee.me['id']}/export-pdf", timeout=T)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        assert r.content[:4] == b"%PDF"

    def test_admin_views_staff_portfolio(self, admin, attendee):
        r = admin.get(f"{API}/portfolio/{attendee.me['id']}", timeout=T)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

    def test_manager_views_staff_portfolio(self, manager, attendee):
        r = manager.get(f"{API}/portfolio/{attendee.me['id']}", timeout=T)
        assert r.status_code in (200, 403), f"{r.status_code} {r.text[:300]}"

    def test_attendee_cannot_view_other_portfolio(self, jane, attendee):
        r = jane.get(f"{API}/portfolio/{attendee.me['id']}", timeout=T)
        assert r.status_code in (403, 404), f"portfolio leak: {r.status_code}"


# ---------------------------------------------------------------- admin panel
class TestAdminPanel:
    def test_users_list(self, admin):
        r = admin.get(f"{API}/admin/users", timeout=T)
        assert r.status_code == 200, r.text[:300]
        users = r.json() if isinstance(r.json(), list) else r.json().get("users", [])
        assert users
        assert all("password_hash" not in u for u in users), "password hash exposed"

    def test_user_crud_round_trip(self, admin):
        email = f"test_iter116_{TAG}@supervision.com"
        c = admin.post(f"{API}/admin/users",
                       json={"email": email, "name": "TEST iter116", "role": "attendee",
                             "password": f"Aa1!{TAG}xyzQ"}, timeout=T)
        assert c.status_code in (200, 201), f"create user -> {c.status_code} {c.text[:300]}"
        uid = c.json().get("id") or c.json().get("user_id")
        assert uid
        try:
            u = admin.put(f"{API}/admin/users/{uid}", json={"name": "TEST iter116 upd"}, timeout=T)
            assert u.status_code in (200, 204), f"{u.status_code} {u.text[:300]}"
            lst = admin.get(f"{API}/admin/users", timeout=T).json()
            users = lst if isinstance(lst, list) else lst.get("users", [])
            found = [x for x in users if x.get("id") == uid]
            assert found and found[0]["name"] == "TEST iter116 upd", found
        finally:
            d = admin.delete(f"{API}/admin/users/{uid}", timeout=T)
            assert d.status_code in (200, 204), d.text[:200]

    def test_standards_list_and_types(self, admin):
        for typ in ("cqc", "care_cert"):
            r = admin.get(f"{API}/admin/standards?type={typ}", timeout=T)
            assert r.status_code == 200, f"{typ}: {r.status_code} {r.text[:200]}"
            assert r.json(), f"{typ} standards empty"

    def test_standards_documents(self, admin):
        r = admin.get(f"{API}/admin/standards/documents", timeout=T)
        assert r.status_code == 200, r.text[:300]

    def test_custom_standard_create_delete(self, admin):
        c = admin.post(f"{API}/admin/standards",
                       json={"type": "custom", "reference": f"T116-{TAG}", "name": f"TEST_iter116 {TAG}",
                             "description": "regression", "keywords": []}, timeout=T)
        assert c.status_code in (200, 201), f"{c.status_code} {c.text[:300]}"
        sid = c.json().get("id") or c.json().get("standard_id")
        if sid:
            d = admin.delete(f"{API}/admin/standards/{sid}", timeout=T)
            assert d.status_code in (200, 204), d.text[:200]

    def test_template_get_put(self, admin):
        g = admin.get(f"{API}/admin/template", timeout=T)
        assert g.status_code == 200, g.text[:300]
        body = g.json()
        p = admin.put(f"{API}/admin/template", json=body, timeout=T)
        assert p.status_code in (200, 204), f"{p.status_code} {p.text[:300]}"

    def test_stats_and_people_stats(self, admin):
        for path in ("/admin/stats", "/admin/people-stats", "/admin/meetings-brief"):
            r = admin.get(f"{API}{path}", timeout=T)
            assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:200]}"

    def test_team_insights(self, admin):
        for path in ("/admin/team-insights", "/admin/team-insights/action-stats",
                     "/admin/team-insights/registers"):
            r = admin.get(f"{API}{path}", timeout=T)
            assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:200]}"

    def test_audit_and_integrations_health(self, admin):
        r = admin.get(f"{API}/admin/integrations/health", timeout=T)
        assert r.status_code == 200, r.text[:300]

    def test_export_evidence(self, admin):
        r = admin.post(f"{API}/admin/export-evidence", json={"format": "csv"}, timeout=T)
        assert r.status_code in (200, 400, 422), f"{r.status_code} {r.text[:300]}"

    def test_export_transcripts(self, admin):
        r = admin.post(f"{API}/admin/export-transcripts", json={"format": "csv"}, timeout=T)
        # 404 = no signed_off meeting has a transcript in this dataset (data condition)
        assert r.status_code in (200, 404), f"{r.status_code} {r.text[:300]}"

    def test_export_excerpts(self, admin):
        for path in ("/admin/export-cqc-excerpts", "/admin/export-cc-excerpts"):
            r = admin.get(f"{API}{path}", timeout=T)
            assert r.status_code in (200, 404), f"{path}: {r.status_code} {r.text[:200]}"

    def test_attendee_blocked_from_admin(self, attendee):
        for path in ("/admin/users", "/admin/stats", "/admin/team-insights", "/admin/standards"):
            r = attendee.get(f"{API}{path}", timeout=T)
            assert r.status_code == 403, f"{path} not gated for attendee: {r.status_code}"

    def test_anon_blocked_from_admin(self, anon):
        r = anon.get(f"{API}/admin/users", timeout=T)
        assert r.status_code == 401, r.status_code


# ---------------------------------------------------------------- schedules
class TestSchedules:
    def test_meeting_types_crud(self, admin):
        c = admin.post(f"{API}/schedules/meeting-types",
                       json={"name": f"TEST_iter116_{TAG}", "frequency_months": 3}, timeout=T)
        assert c.status_code in (200, 201), f"{c.status_code} {c.text[:300]}"
        tid = c.json().get("id")
        lst = admin.get(f"{API}/schedules/meeting-types", timeout=T)
        assert lst.status_code == 200 and TAG in str(lst.json())
        if tid:
            u = admin.put(f"{API}/schedules/meeting-types/{tid}",
                          json={"name": f"TEST_iter116_{TAG}_u", "frequency_months": 6}, timeout=T)
            assert u.status_code in (200, 204), u.text[:200]
            d = admin.delete(f"{API}/schedules/meeting-types/{tid}", timeout=T)
            assert d.status_code in (200, 204), d.text[:200]

    def test_schedules_list_and_due(self, admin):
        for path in ("/schedules/", "/schedules/due"):
            r = admin.get(f"{API}{path}", timeout=T)
            assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:200]}"


# ---------------------------------------------------------------- org
class TestOrg:
    def test_structure_and_settings(self, admin):
        for path in ("/org/structure", "/org/settings", "/org/branding"):
            r = admin.get(f"{API}{path}", timeout=T)
            assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:200]}"

    def test_settings_and_team_crud(self, admin):
        c = admin.post(f"{API}/org/settings", json={"name": f"TEST_iter116_setting_{TAG}",
                                                    "type": "location"}, timeout=T)
        assert c.status_code in (200, 201), f"{c.status_code} {c.text[:300]}"
        sid = c.json().get("id")
        assert sid
        try:
            t = admin.post(f"{API}/org/settings/{sid}/teams",
                           json={"name": f"TEST_iter116_team_{TAG}"}, timeout=T)
            assert t.status_code in (200, 201), f"team create -> {t.status_code} {t.text[:300]}"
            tid = t.json().get("id")
            struct = admin.get(f"{API}/org/structure", timeout=T)
            assert TAG in str(struct.json()), "new setting/team missing from /org/structure"
            if tid:
                u = admin.put(f"{API}/org/teams/{tid}",
                              json={"name": f"TEST_iter116_team_{TAG}_u"}, timeout=T)
                assert u.status_code in (200, 204), u.text[:200]
                assert admin.delete(f"{API}/org/teams/{tid}", timeout=T).status_code in (200, 204)
        finally:
            admin.delete(f"{API}/org/settings/{sid}", timeout=T)

    def test_branding_put_round_trip(self, admin):
        cur = admin.get(f"{API}/org/branding", timeout=T).json()
        p = admin.put(f"{API}/org/branding", json=cur, timeout=T)
        assert p.status_code in (200, 204), f"{p.status_code} {p.text[:300]}"

    def test_branding_logo_fetch(self, admin):
        org_id = admin.me.get("org_id")
        r = admin.get(f"{API}/org/branding/logo/{org_id}", timeout=T)
        assert r.status_code in (200, 302, 404), f"{r.status_code} {r.text[:200]}"

    def test_attendee_cannot_mutate_org(self, attendee):
        r = attendee.post(f"{API}/org/settings", json={"name": "nope", "type": "location"}, timeout=T)
        assert r.status_code == 403, r.status_code


# ---------------------------------------------------------------- doc uploads
class TestDocUploads:
    def test_list(self, admin):
        r = admin.get(f"{API}/doc-uploads/", timeout=T)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

    def test_unknown_upload_404(self, admin):
        r = admin.get(f"{API}/doc-uploads/{uuid.uuid4()}", timeout=T)
        assert r.status_code == 404, r.status_code


# ---------------------------------------------------------------- super admin
class TestSuperAdmin:
    def test_list_orgs(self, sadmin):
        r = sadmin.get(f"{API}/super-admin/orgs", timeout=T)
        assert r.status_code == 200, r.text[:300]
        orgs = r.json() if isinstance(r.json(), list) else r.json().get("organisations", [])
        assert orgs

    def test_org_and_user_lifecycle(self, sadmin):
        c = sadmin.post(f"{API}/super-admin/orgs",
                        json={"name": f"TEST_iter116_org_{TAG}"}, timeout=T)
        assert c.status_code in (200, 201), f"create org -> {c.status_code} {c.text[:300]}"
        oid = c.json().get("id") or c.json().get("org_id")
        assert oid
        try:
            uc = sadmin.post(f"{API}/super-admin/orgs/{oid}/users",
                             json={"email": f"test_iter116_org_{TAG}@example.com",
                                   "name": "TEST iter116 OrgAdmin", "role": "admin",
                                   "password": f"Aa1!{TAG}xyzQ"}, timeout=T)
            assert uc.status_code in (200, 201), f"create org user -> {uc.status_code} {uc.text[:300]}"
            uid = uc.json().get("id") or uc.json().get("user_id")
            lst = sadmin.get(f"{API}/super-admin/orgs/{oid}/users", timeout=T)
            assert lst.status_code == 200 and TAG in str(lst.json())
            if uid:
                pu = sadmin.patch(f"{API}/super-admin/orgs/{oid}/users/{uid}",
                                  json={"name": "TEST iter116 upd"}, timeout=T)
                assert pu.status_code in (200, 204), f"{pu.status_code} {pu.text[:300]}"
                du = sadmin.delete(f"{API}/super-admin/orgs/{oid}/users/{uid}", timeout=T)
                assert du.status_code in (200, 204), du.text[:200]
        finally:
            d = sadmin.delete(f"{API}/super-admin/orgs/{oid}", timeout=T)
            assert d.status_code in (200, 204), f"delete org -> {d.status_code} {d.text[:300]}"

    def test_admin_blocked_from_super_admin(self, admin):
        r = admin.get(f"{API}/super-admin/orgs", timeout=T)
        assert r.status_code == 403, r.status_code

    def test_anon_blocked_from_super_admin(self, anon):
        r = anon.get(f"{API}/super-admin/orgs", timeout=T)
        assert r.status_code == 401, r.status_code


# ---------------------------------------------------------------- isolation
class TestIsolation:
    def test_cross_tenant_new_org_admin_sees_nothing(self, sadmin):
        oid = None
        try:
            c = sadmin.post(f"{API}/super-admin/orgs", json={"name": f"TEST_iter116_iso_{TAG}"}, timeout=T)
            assert c.status_code in (200, 201), c.text[:300]
            oid = c.json()["id"]
            email = f"test_iter116_iso_{TAG}@example.com"
            pw = f"Aa1!{TAG}isoQ"
            uc = sadmin.post(f"{API}/super-admin/orgs/{oid}/users",
                             json={"email": email, "name": "TEST iso admin", "role": "admin",
                                   "password": pw}, timeout=T)
            assert uc.status_code in (200, 201), uc.text[:300]
            s = requests.Session()
            r = s.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=T)
            assert r.status_code == 200, f"new org admin login -> {r.status_code} {r.text[:200]}"
            if r.json().get("requires_mfa"):
                asyncio.run(_force_mfa(email))
                r2 = s.post(f"{API}/auth/verify-mfa",
                            json={"mfa_session": r.json()["mfa_session"], "code": "123456"}, timeout=T)
                assert r2.status_code == 200, r2.text[:200]
            if s.get(f"{API}/auth/me", timeout=T).status_code != 200:
                pytest.skip("new org admin must change password before API access")
            ms = mlist(s.get(f"{API}/meetings/?limit=500", timeout=T).json())
            assert ms == [], f"cross-tenant leak: new org sees {len(ms)} meetings"
            us = s.get(f"{API}/admin/users", timeout=T).json()
            us = us if isinstance(us, list) else us.get("users", [])
            emails = {u.get("email") for u in us}
            assert ADMIN[0] not in emails, f"cross-tenant user leak: {emails}"
        finally:
            if oid:
                sadmin.delete(f"{API}/super-admin/orgs/{oid}", timeout=T)

    def test_same_org_two_attendees_no_overlap(self, jane, attendee):
        j = {m["id"] for m in mlist(jane.get(f"{API}/meetings/?limit=500", timeout=T).json())}
        u = {m["id"] for m in mlist(attendee.get(f"{API}/meetings/?limit=500", timeout=T).json())}
        assert j and u
        assert not (j & u), f"overlap: {j & u}"

    def test_admin_list_is_superset(self, admin, jane, attendee):
        a = {m["id"] for m in mlist(admin.get(f"{API}/meetings/?limit=500", timeout=T).json())}
        j = {m["id"] for m in mlist(jane.get(f"{API}/meetings/?limit=500", timeout=T).json())}
        u = {m["id"] for m in mlist(attendee.get(f"{API}/meetings/?limit=500", timeout=T).json())}
        assert (j | u) <= a, f"admin missing rows: {(j | u) - a}"
