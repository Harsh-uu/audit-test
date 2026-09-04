"""Iter114: regression suite for the least-privilege connection-role change (m011).

Change under test:
  - database.py: main pool now authenticates as `app_default` (NOBYPASSRLS);
    with_admin() uses a separate `admin_pool` as `postgres` (BYPASSRLS)
  - server.py startup: migrations run BEFORE pool creation
  - routers/meetings.py _list_meetings_data(): attendee branch with_admin -> with_org
  - routers/portfolio.py _build_portfolio_data(): 2x with_admin -> with_org

Coverage: auth (4 roles incl. MFA), meetings CRUD + list, review reads, portfolio
(self / manager / admin), dashboard, admin panel, org settings/branding/structure,
schedules, prep, super-admin org+user management, invite flow, password-reset flow,
processing/status, and cross-tenant isolation.
"""
import asyncio
import os
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
API = f"{BASE}/api"
DSN = BE["DATABASE_URL"]
TIMEOUT = 90

ADMIN = ("admin@supervision.com", "Admin123!")
MANAGER = ("manager@supervision.com", "Manager123!")
ATTENDEE = ("user@supervision.com", "AnotherNew789!")
JANE = ("jane@supervision.com", "JaneNew456!")
SUPERADMIN = ("superadmin@1two.one", "NewPass123!")


# ---------------- helpers ----------------

async def _db(fn):
    conn = await asyncpg.connect(DSN, ssl="require")
    try:
        return await fn(conn)
    finally:
        await conn.close()


def _clear_rate_limits():
    asyncio.get_event_loop_policy().new_event_loop()
    asyncio.run(_db(lambda c: c.execute("DELETE FROM login_attempts")))


def _force_mfa(email):
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = datetime.now(timezone.utc) + timedelta(minutes=10)
    asyncio.run(_db(lambda c: c.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, exp, email)))


def login(email, password):
    """Returns an authenticated requests.Session (handles MFA via DB override)."""
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=TIMEOUT)
    if r.status_code == 429:
        _clear_rate_limits()
        r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=TIMEOUT)
    assert r.status_code == 200, f"login {email} -> {r.status_code} {r.text[:300]}"
    data = r.json()
    if data.get("requires_mfa"):
        _force_mfa(email)
        r2 = s.post(f"{API}/auth/verify-mfa",
                    json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=TIMEOUT)
        assert r2.status_code == 200, f"verify-mfa {email} -> {r2.status_code} {r2.text[:300]}"
    return s


@pytest.fixture(scope="session")
def admin_s():
    return login(*ADMIN)


@pytest.fixture(scope="session")
def manager_s():
    return login(*MANAGER)


@pytest.fixture(scope="session")
def attendee_s():
    return login(*ATTENDEE)


@pytest.fixture(scope="session")
def jane_s():
    return login(*JANE)


@pytest.fixture(scope="session")
def super_s():
    return login(*SUPERADMIN)


@pytest.fixture(scope="session")
def me(admin_s):
    r = admin_s.get(f"{API}/auth/me", timeout=TIMEOUT)
    assert r.status_code == 200
    return r.json()


# ---------------- auth: all 4 roles ----------------

class TestAuthAllRoles:
    @pytest.mark.parametrize("creds,expected_role", [
        (ADMIN, "admin"), (MANAGER, "manager"),
        (ATTENDEE, "attendee"), (JANE, "attendee"), (SUPERADMIN, "super_admin"),
    ])
    def test_login_and_me(self, creds, expected_role):
        s = login(*creds)
        r = s.get(f"{API}/auth/me", timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["email"] == creds[0]
        assert body["role"] == expected_role
        assert "id" in body and isinstance(body["id"], str)

    def test_bad_password_rejected(self):
        r = requests.post(f"{API}/auth/login",
                          json={"email": ADMIN[0], "password": "WrongPass123!"}, timeout=TIMEOUT)
        assert r.status_code in (401, 429), r.status_code

    def test_refresh_and_logout(self):
        s = login(*ATTENDEE)
        r = s.post(f"{API}/auth/refresh", timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        assert s.get(f"{API}/auth/me", timeout=TIMEOUT).status_code == 200
        assert s.post(f"{API}/auth/logout", timeout=TIMEOUT).status_code == 200
        assert s.get(f"{API}/auth/me", timeout=TIMEOUT).status_code == 401

    def test_unauthenticated_blocked(self):
        assert requests.get(f"{API}/meetings/", timeout=TIMEOUT).status_code == 401


# ---------------- read-path smoke across every major router ----------------

class TestReadPaths:
    @pytest.mark.parametrize("path", [
        "/dashboard/", "/meetings/", "/admin/users", "/admin/standards",
        "/admin/standards/documents", "/admin/template", "/admin/stats",
        "/admin/team-insights", "/admin/people-stats", "/admin/team-insights/registers",
        "/admin/meetings-brief", "/org/structure", "/org/settings", "/org/branding",
        "/schedules/", "/schedules/meeting-types", "/schedules/due",
        "/prep/focus-topics", "/doc-uploads/",
    ])
    def test_admin_read_ok(self, admin_s, path):
        r = admin_s.get(f"{API}{path}", timeout=TIMEOUT)
        assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:300]}"

    @pytest.mark.parametrize("path", ["/dashboard/", "/meetings/", "/schedules/due"])
    def test_manager_read_ok(self, manager_s, path):
        r = manager_s.get(f"{API}{path}", timeout=TIMEOUT)
        assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:300]}"

    @pytest.mark.parametrize("path", ["/dashboard/", "/meetings/"])
    def test_attendee_read_ok(self, attendee_s, path):
        r = attendee_s.get(f"{API}{path}", timeout=TIMEOUT)
        assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:300]}"


# ---------------- PART B: attendee meeting list under with_org ----------------

class TestAttendeeMeetingList:
    def test_attendee_sees_only_own_meetings(self, attendee_s):
        me = attendee_s.get(f"{API}/auth/me", timeout=TIMEOUT).json()
        uid, org_id = me["id"], me.get("org_id")
        r = attendee_s.get(f"{API}/meetings/", timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        payload = r.json()
        meetings = payload if isinstance(payload, list) else payload.get("meetings", [])
        assert isinstance(meetings, list)
        for m in meetings:
            assert m.get("org_id") in (None, org_id), f"cross-org meeting leaked: {m.get('id')}"
            attendee_ids = [a.get("user_id") for a in (m.get("attendees") or [])
                            if isinstance(a, dict)]
            shared_ids = [a.get("user_id") for a in (m.get("shared_with") or [])
                          if isinstance(a, dict)]
            assert (m.get("created_by") == uid or uid in attendee_ids or uid in shared_ids), \
                f"meeting {m.get('id')} not owned by attendee"

    def test_attendee_list_matches_db_expectation(self, attendee_s):
        """with_org must not silently drop rows: compare API count with a direct
        BYPASSRLS DB count of the same ownership predicate."""
        me = attendee_s.get(f"{API}/auth/me", timeout=TIMEOUT).json()
        uid, org_id = me["id"], me["org_id"]

        async def q(c):
            return await c.fetchval(
                """SELECT count(*) FROM meetings
                   WHERE org_id = $2::uuid AND (
                     created_by = $1::uuid
                     OR EXISTS (SELECT 1 FROM jsonb_array_elements(
                          CASE WHEN jsonb_typeof(COALESCE(attendees,'null'::jsonb))='array'
                               THEN attendees ELSE '[]'::jsonb END) a
                        WHERE a->>'user_id' = $1::text)
                     OR EXISTS (SELECT 1 FROM jsonb_array_elements(
                          CASE WHEN jsonb_typeof(COALESCE(shared_with,'null'::jsonb))='array'
                               THEN shared_with ELSE '[]'::jsonb END) s
                        WHERE s->>'user_id' = $1::text))""",
                uid, org_id)

        db_count = asyncio.run(_db(q))
        payload = attendee_s.get(f"{API}/meetings/?limit=500", timeout=TIMEOUT).json()
        meetings = payload if isinstance(payload, list) else payload.get("meetings", [])
        assert len(meetings) == db_count, f"API returned {len(meetings)} vs DB {db_count}"
        assert db_count > 0, "fixture problem: attendee has no meetings to validate against"

    def test_jane_sees_fewer_or_different_meetings(self, jane_s, attendee_s):
        jp = jane_s.get(f"{API}/meetings/?limit=500", timeout=TIMEOUT)
        assert jp.status_code == 200, jp.text[:300]
        jd = jp.json()
        jane_ids = {m["id"] for m in (jd if isinstance(jd, list) else jd.get("meetings", []))}
        ap = attendee_s.get(f"{API}/meetings/?limit=500", timeout=TIMEOUT).json()
        user_ids = {m["id"] for m in (ap if isinstance(ap, list) else ap.get("meetings", []))}
        # jane is a same-org user not on most meetings -> must not see all of user's
        assert not user_ids.issubset(jane_ids) or len(user_ids) == 0, \
            "same-org unauthorized user sees every meeting of another user"


# ---------------- PART B: portfolio under with_org ----------------

class TestPortfolio:
    def test_self_portfolio(self, attendee_s):
        uid = attendee_s.get(f"{API}/auth/me", timeout=TIMEOUT).json()["id"]
        r = attendee_s.get(f"{API}/portfolio/{uid}", timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert "user" in d or "user_id" in d or "meetings" in d, list(d.keys())

    def test_admin_views_member_portfolio(self, admin_s):
        users = admin_s.get(f"{API}/admin/users", timeout=TIMEOUT).json()
        users = users if isinstance(users, list) else users.get("users", [])
        target = next(u for u in users if u.get("email") == ATTENDEE[0])
        r = admin_s.get(f"{API}/portfolio/{target['id']}", timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:400]

    def test_manager_views_staff_portfolio(self, manager_s, admin_s):
        users = admin_s.get(f"{API}/admin/users", timeout=TIMEOUT).json()
        users = users if isinstance(users, list) else users.get("users", [])
        target = next(u for u in users if u.get("email") == ATTENDEE[0])
        r = manager_s.get(f"{API}/portfolio/{target['id']}", timeout=TIMEOUT)
        assert r.status_code in (200, 403), r.text[:400]
        if r.status_code == 200:
            assert isinstance(r.json(), dict)

    def test_export_pdf(self, attendee_s):
        uid = attendee_s.get(f"{API}/auth/me", timeout=TIMEOUT).json()["id"]
        r = attendee_s.get(f"{API}/portfolio/{uid}/export-pdf", timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        assert r.content[:4] == b"%PDF", r.content[:20]

    def test_portfolio_count_parity_with_db(self, attendee_s):
        me = attendee_s.get(f"{API}/auth/me", timeout=TIMEOUT).json()
        uid, org_id = me["id"], me["org_id"]

        async def q(c):
            return await c.fetchval(
                """SELECT count(*) FROM meetings
                   WHERE org_id=$1::uuid AND status IN ('signed_off','shared')
                     AND analysis_id IS NOT NULL
                     AND (sign_off_manager_id IS NULL OR sign_off_manager_id != $2::uuid)
                     AND EXISTS (SELECT 1 FROM jsonb_array_elements(
                          CASE WHEN jsonb_typeof(COALESCE(attendees,'[]'::jsonb))='array'
                               THEN COALESCE(attendees,'[]'::jsonb) ELSE '[]'::jsonb END) e
                        WHERE e->>'user_id' = $2::text)""",
                org_id, uid)

        db_count = asyncio.run(_db(q))
        d = attendee_s.get(f"{API}/portfolio/{uid}", timeout=TIMEOUT).json()
        api_meetings = d.get("meetings") or d.get("raw_meetings") or []
        assert len(api_meetings) == db_count, (
            f"portfolio meetings API={len(api_meetings)} DB={db_count}")


# ---------------- cross-tenant isolation ----------------

class TestCrossTenantIsolation:
    @pytest.fixture(scope="class")
    def foreign_ids(self, me):
        """A user id + meeting id belonging to an org other than the admin's."""
        my_org = me["org_id"]

        async def q(c):
            u = await c.fetchrow(
                "SELECT id, org_id FROM users WHERE org_id IS NOT NULL AND org_id != $1::uuid LIMIT 1",
                my_org)
            m = await c.fetchrow(
                "SELECT id, org_id FROM meetings WHERE org_id IS NOT NULL AND org_id != $1::uuid LIMIT 1",
                my_org)
            return (dict(u) if u else None, dict(m) if m else None)

        return asyncio.run(_db(q))

    def test_admin_cannot_read_foreign_meeting(self, admin_s, foreign_ids):
        _, m = foreign_ids
        if not m:
            pytest.skip("no foreign-org meeting in DB")
        r = admin_s.get(f"{API}/meetings/{m['id']}", timeout=TIMEOUT)
        assert r.status_code in (403, 404), f"leak: {r.status_code} {r.text[:200]}"

    def test_admin_cannot_read_foreign_portfolio(self, admin_s, foreign_ids):
        u, _ = foreign_ids
        if not u:
            pytest.skip("no foreign-org user in DB")
        r = admin_s.get(f"{API}/portfolio/{u['id']}", timeout=TIMEOUT)
        assert r.status_code in (403, 404), f"leak: {r.status_code} {r.text[:300]}"

    def test_attendee_cannot_read_foreign_meeting(self, attendee_s, foreign_ids):
        _, m = foreign_ids
        if not m:
            pytest.skip("no foreign-org meeting in DB")
        r = attendee_s.get(f"{API}/meetings/{m['id']}", timeout=TIMEOUT)
        assert r.status_code in (403, 404), f"leak: {r.status_code} {r.text[:200]}"

    def test_attendee_cannot_use_admin_endpoints(self, attendee_s):
        for p in ("/admin/users", "/admin/stats", "/super-admin/orgs"):
            r = attendee_s.get(f"{API}{p}", timeout=TIMEOUT)
            assert r.status_code in (401, 403), f"{p} -> {r.status_code}"

    def test_jane_cannot_read_other_users_meeting(self, jane_s, attendee_s):
        ap = attendee_s.get(f"{API}/meetings/?limit=500", timeout=TIMEOUT).json()
        ms = ap if isinstance(ap, list) else ap.get("meetings", [])
        if not ms:
            pytest.skip("no meetings for fixture user")
        mid = ms[0]["id"]
        r = jane_s.get(f"{API}/meetings/{mid}", timeout=TIMEOUT)
        assert r.status_code in (403, 404), f"same-org leak: {r.status_code} {r.text[:200]}"


# ---------------- meetings CRUD ----------------

class TestMeetingCRUD:
    def test_create_read_update_delete(self, admin_s, me):
        users = admin_s.get(f"{API}/admin/users", timeout=TIMEOUT).json()
        users = users if isinstance(users, list) else users.get("users", [])
        att = next(u for u in users if u.get("email") == ATTENDEE[0])
        payload = {
            "title": "TEST_iter114 meeting",
            "date": datetime.now(timezone.utc).isoformat(),
            "attendee_ids": [att["id"]],
        }
        r = admin_s.post(f"{API}/meetings/", json=payload, timeout=TIMEOUT)
        assert r.status_code in (200, 201), r.text[:400]
        mid = r.json().get("id") or r.json().get("meeting_id")
        assert mid
        try:
            g = admin_s.get(f"{API}/meetings/{mid}", timeout=TIMEOUT)
            assert g.status_code == 200, g.text[:300]
            assert g.json()["title"] == payload["title"]
            assert g.json()["org_id"] == me["org_id"]

            # visible to the attendee via the changed with_org branch
            s = login(*ATTENDEE)
            lp = s.get(f"{API}/meetings/?limit=500", timeout=TIMEOUT).json()
            ids = {m["id"] for m in (lp if isinstance(lp, list) else lp.get("meetings", []))}
            assert mid in ids, "new meeting not visible to attendee under with_org branch"

            # update attendees + manager
            up = admin_s.put(f"{API}/meetings/{mid}/attendees",
                             json={"attendee_ids": payload["attendee_ids"]}, timeout=TIMEOUT)
            assert up.status_code == 200, up.text[:300]

            # recording lifecycle basics
            n = admin_s.post(f"{API}/recording/{mid}/notice", timeout=TIMEOUT)
            assert n.status_code in (200, 201), n.text[:300]
            st = admin_s.post(f"{API}/recording/{mid}/start", timeout=TIMEOUT)
            assert st.status_code in (200, 201), st.text[:300]
            ev = admin_s.get(f"{API}/recording/{mid}/events", timeout=TIMEOUT)
            assert ev.status_code == 200, ev.text[:300]
            stat = admin_s.get(f"{API}/processing/{mid}/status", timeout=TIMEOUT)
            assert stat.status_code == 200, stat.text[:300]
        finally:
            d = admin_s.delete(f"{API}/meetings/{mid}", timeout=TIMEOUT)
            assert d.status_code in (200, 204), d.text[:300]
            g2 = admin_s.get(f"{API}/meetings/{mid}", timeout=TIMEOUT)
            assert g2.status_code == 404, f"deleted meeting still readable: {g2.status_code}"


# ---------------- org settings / branding ----------------

class TestOrgSettings:
    def test_setting_and_team_crud(self, admin_s):
        r = admin_s.post(f"{API}/org/settings", json={"name": "TEST_iter114 setting"},
                         timeout=TIMEOUT)
        assert r.status_code in (200, 201), r.text[:400]
        sid = r.json().get("id") or r.json().get("setting_id")
        assert sid
        try:
            lst = admin_s.get(f"{API}/org/settings", timeout=TIMEOUT).json()
            lst = lst if isinstance(lst, list) else lst.get("settings", [])
            assert any(s["id"] == sid for s in lst), "created setting not persisted"

            up = admin_s.put(f"{API}/org/settings/{sid}",
                             json={"name": "TEST_iter114 renamed"}, timeout=TIMEOUT)
            assert up.status_code == 200, up.text[:300]
            lst2 = admin_s.get(f"{API}/org/settings", timeout=TIMEOUT).json()
            lst2 = lst2 if isinstance(lst2, list) else lst2.get("settings", [])
            assert next(s for s in lst2 if s["id"] == sid)["name"] == "TEST_iter114 renamed"

            t = admin_s.post(f"{API}/org/settings/{sid}/teams",
                             json={"name": "TEST_iter114 team"}, timeout=TIMEOUT)
            assert t.status_code in (200, 201), t.text[:300]
            tid = t.json().get("id") or t.json().get("team_id")
            assert tid
            td = admin_s.delete(f"{API}/org/teams/{tid}", timeout=TIMEOUT)
            assert td.status_code in (200, 204), td.text[:300]
        finally:
            d = admin_s.delete(f"{API}/org/settings/{sid}", timeout=TIMEOUT)
            assert d.status_code in (200, 204), d.text[:300]

    def test_branding_round_trip(self, admin_s):
        cur = admin_s.get(f"{API}/org/branding", timeout=TIMEOUT)
        assert cur.status_code == 200, cur.text[:300]
        before = cur.json()

        async def snapshot(c):
            return await c.fetchval(
                "SELECT branding::text FROM organisations WHERE id=(SELECT org_id FROM users WHERE email=$1)",
                ADMIN[0])

        raw_before = asyncio.run(_db(snapshot))
        try:
            up = admin_s.put(f"{API}/org/branding", json={"primary_color": "#123456"},
                             timeout=TIMEOUT)
            assert up.status_code == 200, up.text[:400]
            after = admin_s.get(f"{API}/org/branding", timeout=TIMEOUT).json()
            assert after.get("primary_color") == "#123456"
            assert after.get("has_logo") == before.get("has_logo")
        finally:
            # PUT /org/branding cannot clear primary_color (None is ignored), so
            # restore the exact original JSONB directly.
            asyncio.run(_db(lambda c: c.execute(
                "UPDATE organisations SET branding=$1::jsonb "
                "WHERE id=(SELECT org_id FROM users WHERE email=$2)",
                raw_before, ADMIN[0])))
            restored = admin_s.get(f"{API}/org/branding", timeout=TIMEOUT).json()
            assert restored.get("primary_color") == before.get("primary_color")


# ---------------- schedules ----------------

class TestSchedules:
    def test_meeting_type_crud(self, admin_s):
        r = admin_s.post(f"{API}/schedules/meeting-types",
                         json={"name": "TEST_iter114 type", "frequency_months": 3},
                         timeout=TIMEOUT)
        assert r.status_code in (200, 201), r.text[:400]
        tid = r.json().get("id")
        assert tid
        try:
            lst = admin_s.get(f"{API}/schedules/meeting-types", timeout=TIMEOUT).json()
            lst = lst if isinstance(lst, list) else lst.get("meeting_types", [])
            assert any(t["id"] == tid for t in lst)
            up = admin_s.put(f"{API}/schedules/meeting-types/{tid}",
                             json={"name": "TEST_iter114 type2", "frequency_months": 6},
                             timeout=TIMEOUT)
            assert up.status_code == 200, up.text[:300]
        finally:
            d = admin_s.delete(f"{API}/schedules/meeting-types/{tid}", timeout=TIMEOUT)
            assert d.status_code in (200, 204), d.text[:300]


# ---------------- admin user management ----------------

class TestAdminUsers:
    def test_create_update_delete_user(self, admin_s):
        email = f"TEST_iter114_{uuid.uuid4().hex[:8]}@supervision.com".lower()
        r = admin_s.post(f"{API}/admin/users", json={
            "email": email, "name": "TEST iter114", "role": "attendee",
            "password": "TestPass123!"}, timeout=TIMEOUT)
        assert r.status_code in (200, 201), r.text[:400]
        uid = r.json().get("id") or r.json().get("user_id")
        assert uid
        try:
            users = admin_s.get(f"{API}/admin/users", timeout=TIMEOUT).json()
            users = users if isinstance(users, list) else users.get("users", [])
            found = next((u for u in users if u["id"] == uid), None)
            assert found and found["email"] == email

            up = admin_s.put(f"{API}/admin/users/{uid}",
                             json={"name": "TEST iter114 renamed"}, timeout=TIMEOUT)
            assert up.status_code == 200, up.text[:300]
            users2 = admin_s.get(f"{API}/admin/users", timeout=TIMEOUT).json()
            users2 = users2 if isinstance(users2, list) else users2.get("users", [])
            assert next(u for u in users2 if u["id"] == uid)["name"] == "TEST iter114 renamed"

            # new user can log in (Supabase password path)
            s = login(email, "TestPass123!")
            assert s.get(f"{API}/auth/me", timeout=TIMEOUT).json()["email"] == email
        finally:
            d = admin_s.delete(f"{API}/admin/users/{uid}", timeout=TIMEOUT)
            assert d.status_code in (200, 204), d.text[:300]


# ---------------- invite flow ----------------

class TestInviteFlow:
    def test_org_invite_user_creates_working_account(self, admin_s):
        email = f"TEST_iter114_orginv_{uuid.uuid4().hex[:8]}@supervision.com".lower()
        r = admin_s.post(f"{API}/org/invite-user",
                         json={"email": email, "name": "TEST invite", "role": "attendee",
                               "password": "InvitePass123!"}, timeout=TIMEOUT)
        assert r.status_code in (200, 201), r.text[:400]
        uid = r.json()["id"]
        try:
            s = login(email, "InvitePass123!")
            me = s.get(f"{API}/auth/me", timeout=TIMEOUT).json()
            assert me["email"] == email
            assert me["role"] == "attendee"
            assert me.get("must_change_password") is True
        finally:
            admin_s.delete(f"{API}/admin/users/{uid}", timeout=TIMEOUT)

    def test_superadmin_invite_token_accept(self, super_s):
        """Token-based invite flow: super-admin invites an org admin, invitee
        accepts and sets their own password."""
        oname = f"TEST_iter114_invorg_{uuid.uuid4().hex[:6]}"
        o = super_s.post(f"{API}/super-admin/orgs", json={"name": oname}, timeout=TIMEOUT)
        assert o.status_code in (200, 201), o.text[:400]
        oid = o.json().get("id") or o.json().get("org_id")
        email = f"TEST_iter114_inv_{uuid.uuid4().hex[:8]}@supervision.com".lower()
        r = super_s.post(f"{API}/super-admin/orgs/{oid}/invite",
                         json={"email": email, "name": "TEST invite"}, timeout=TIMEOUT)
        assert r.status_code in (200, 201), r.text[:400]

        async def q(c):
            return await c.fetchrow(
                "SELECT i.token FROM invitations i JOIN users u ON u.id = i.user_id "
                "WHERE u.email=$1 ORDER BY i.created_at DESC LIMIT 1", email)

        row = asyncio.run(_db(q))
        assert row, "invite row not persisted"
        token = row["token"]
        g = requests.get(f"{API}/auth/invite/{token}", timeout=TIMEOUT)
        assert g.status_code == 200, g.text[:300]
        assert g.json().get("email") == email

        a = requests.post(f"{API}/auth/accept-invite",
                          json={"token": token, "name": "TEST invite",
                                "password": "InvitePass123!"}, timeout=TIMEOUT)
        assert a.status_code in (200, 201), a.text[:400]
        s = login(email, "InvitePass123!")
        assert s.get(f"{API}/auth/me", timeout=TIMEOUT).json()["email"] == email

        # cleanup
        users = super_s.get(f"{API}/super-admin/orgs/{oid}/users", timeout=TIMEOUT).json()
        users = users if isinstance(users, list) else users.get("users", [])
        u = next((x for x in users if x["email"] == email), None)
        if u:
            super_s.delete(f"{API}/super-admin/orgs/{oid}/users/{u['id']}", timeout=TIMEOUT)
        super_s.delete(f"{API}/super-admin/orgs/{oid}", timeout=TIMEOUT)


# ---------------- password reset / change ----------------

class TestPasswordFlows:
    def test_forgot_and_reset(self, admin_s):
        email = f"TEST_iter114_pw_{uuid.uuid4().hex[:8]}@supervision.com".lower()
        r = admin_s.post(f"{API}/admin/users", json={
            "email": email, "name": "TEST pw", "role": "attendee",
            "password": "TestPass123!"}, timeout=TIMEOUT)
        assert r.status_code in (200, 201), r.text[:400]
        uid = r.json().get("id") or r.json().get("user_id")
        try:
            f = requests.post(f"{API}/auth/forgot-password", json={"email": email},
                              timeout=TIMEOUT)
            assert f.status_code == 200, f.text[:300]

            async def q(c):
                return await c.fetchrow(
                    "SELECT token FROM password_reset_tokens WHERE email=$1 "
                    "AND used = FALSE ORDER BY expires_at DESC LIMIT 1", email)

            row = asyncio.run(_db(q))
            assert row, "reset token not persisted"
            rp = requests.post(f"{API}/auth/reset-password",
                               json={"token": row["token"], "new_password": "ResetPass123!"},
                               timeout=TIMEOUT)
            assert rp.status_code == 200, rp.text[:400]
            s = login(email, "ResetPass123!")
            cp = s.post(f"{API}/auth/change-password",
                        json={"current_password": "ResetPass123!",
                              "new_password": "ChangedPass123!"}, timeout=TIMEOUT)
            assert cp.status_code == 200, cp.text[:400]
            login(email, "ChangedPass123!")
        finally:
            if uid:
                admin_s.delete(f"{API}/admin/users/{uid}", timeout=TIMEOUT)
            asyncio.run(_db(lambda c: c.execute(
                "DELETE FROM password_reset_tokens WHERE email=$1", email)))


# ---------------- super admin ----------------

class TestSuperAdmin:
    def test_list_orgs(self, super_s):
        r = super_s.get(f"{API}/super-admin/orgs", timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        orgs = r.json()
        orgs = orgs if isinstance(orgs, list) else orgs.get("orgs", [])
        assert len(orgs) >= 1
        assert all("id" in o and "_id" not in o for o in orgs)

    def test_org_crud_and_user_in_org(self, super_s):
        name = f"TEST_iter114_org_{uuid.uuid4().hex[:6]}"
        r = super_s.post(f"{API}/super-admin/orgs", json={"name": name}, timeout=TIMEOUT)
        assert r.status_code in (200, 201), r.text[:400]
        oid = r.json().get("id") or r.json().get("org_id")
        assert oid
        try:
            p = super_s.patch(f"{API}/super-admin/orgs/{oid}", json={"name": name + "_r"},
                              timeout=TIMEOUT)
            assert p.status_code == 200, p.text[:300]

            ul = super_s.get(f"{API}/super-admin/orgs/{oid}/users", timeout=TIMEOUT)
            assert ul.status_code == 200, ul.text[:300]

            email = f"TEST_iter114_sa_{uuid.uuid4().hex[:8]}@supervision.com".lower()
            cu = super_s.post(f"{API}/super-admin/orgs/{oid}/users", json={
                "email": email, "name": "TEST sa user", "role": "admin",
                "password": "TestPass123!"}, timeout=TIMEOUT)
            assert cu.status_code in (200, 201), cu.text[:400]
            nuid = cu.json().get("id") or cu.json().get("user_id")
            ul2 = super_s.get(f"{API}/super-admin/orgs/{oid}/users", timeout=TIMEOUT).json()
            ul2 = ul2 if isinstance(ul2, list) else ul2.get("users", [])
            assert any(u["id"] == nuid for u in ul2), "created org user not persisted"
            du = super_s.delete(f"{API}/super-admin/orgs/{oid}/users/{nuid}", timeout=TIMEOUT)
            assert du.status_code in (200, 204), du.text[:300]
        finally:
            d = super_s.delete(f"{API}/super-admin/orgs/{oid}", timeout=TIMEOUT)
            assert d.status_code in (200, 204), d.text[:300]


# ---------------- review / prep read paths on a real meeting ----------------

class TestReviewPrep:
    @pytest.fixture(scope="class")
    def signed_meeting_id(self, admin_s):
        p = admin_s.get(f"{API}/meetings/?limit=500", timeout=TIMEOUT).json()
        ms = p if isinstance(p, list) else p.get("meetings", [])
        m = next((x for x in ms if x.get("status") in ("signed_off", "shared", "reviewed")), None)
        if not m:
            pytest.skip("no reviewable meeting available")
        return m["id"]

    def test_review_read(self, admin_s, signed_meeting_id):
        r = admin_s.get(f"{API}/review/{signed_meeting_id}", timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        assert "_id" not in r.json()

    def test_comments_audit_transcript(self, admin_s, signed_meeting_id):
        for p in (f"/review/{signed_meeting_id}/comments",
                  f"/review/{signed_meeting_id}/audit-trail",
                  f"/meetings/{signed_meeting_id}/transcript-text"):
            r = admin_s.get(f"{API}{p}", timeout=TIMEOUT)
            assert r.status_code in (200, 404), f"{p} -> {r.status_code} {r.text[:200]}"

    def test_review_export_pdf(self, admin_s, signed_meeting_id):
        r = admin_s.get(f"{API}/review/{signed_meeting_id}/export-pdf", timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        assert r.content[:4] == b"%PDF"

    def test_prep_context(self, admin_s, signed_meeting_id):
        r = admin_s.get(f"{API}/prep/{signed_meeting_id}/context", timeout=TIMEOUT)
        assert r.status_code in (200, 404), r.text[:300]
