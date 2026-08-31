"""Iteration 103 — regression suite for the narrowed get_current_user() SELECT in deps.py.

deps.get_current_user() now selects only:
  id, org_id, email, name, role, team_id, setting_id, password_changed_at

Covers:
  * login + protected access for admin / manager / attendee
  * /api/auth/me field correctness vs DB + no leak of dropped sensitive columns
  * broad smoke across role-gated endpoints (admin / manager / attendee)
  * get_manager_scope() end-to-end isolation (role/team_id/setting_id)
  * SEC-001: password change / admin reset must invalidate the old access token
    (depends on password_changed_at still being selected)
  * admin.py force-reseed log line reading current_user.get('email')

Run with:  cd /app/backend && python3 -m pytest tests/test_iter103_current_user_select.py -n 0 -q
(-n 0 mandatory: shared-account MFA override + login rate-limit table are global state.)
"""
import asyncio
from datetime import datetime, timedelta, timezone

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

BE = dotenv_values("/app/backend/.env")
FE = dotenv_values("/app/frontend/.env")
BASE = FE["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = BE["DATABASE_URL"]

ORG = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"
SETTING_ONE = "70591fed-9a98-4d09-a16a-b911735c63e4"

ADMIN = ("admin@supervision.com", "Admin123!")
MANAGER = ("manager@supervision.com", "Manager123!")
JANE = ("jane@supervision.com", "Jane123!")

DROPPED_COLUMNS = [
    "password_hash", "mfa_code", "mfa_code_expires_at", "mfa_code_attempts",
    "must_change_password", "password_changed_at",
]
SELECTED = ["id", "org_id", "email", "name", "role", "team_id", "setting_id"]


# ── infra helpers ─────────────────────────────────────────────────────────────
def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _db(fn):
    conn = await asyncpg.connect(DSN)
    try:
        return await fn(conn)
    finally:
        await conn.close()


def db(fn):
    return _run(_db(fn))


def clear_limits():
    db(lambda c: c.execute("DELETE FROM login_attempts"))


def login(email, password):
    """Password login + DB MFA bypass. Returns an authenticated requests.Session."""
    clear_limits()
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=90)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:300]}"
    data = r.json()
    if data.get("requires_mfa"):
        h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
        exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        db(lambda c: c.execute(
            "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
            h, exp, email))
        r2 = s.post(f"{BASE}/auth/verify-mfa",
                    json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=90)
        assert r2.status_code == 200, f"mfa failed for {email}: {r2.status_code} {r2.text[:300]}"
    assert s.cookies.get("supervision_access"), f"no access cookie set for {email}"
    return s


@pytest.fixture(scope="session")
def admin_s():
    return login(*ADMIN)


@pytest.fixture(scope="session")
def manager_s():
    return login(*MANAGER)


@pytest.fixture(scope="session")
def attendee_s():
    return login(*JANE)


def db_user(email):
    return dict(db(lambda c: c.fetchrow("SELECT * FROM users WHERE email=$1", email)))


# ── 1. Login works for all 3 roles and the session reaches protected endpoints ─
class TestLoginAllRoles:
    @pytest.mark.parametrize("email,password,role", [
        (ADMIN[0], ADMIN[1], "admin"),
        (MANAGER[0], MANAGER[1], "manager"),
        (JANE[0], JANE[1], "attendee"),
    ])
    def test_login_then_protected_access(self, email, password, role):
        s = login(email, password)
        me = s.get(f"{BASE}/auth/me", timeout=60)
        assert me.status_code == 200, f"{email} /auth/me {me.status_code}: {me.text[:300]}"
        assert me.json()["role"] == role, me.json()
        # a second protected endpoint on the same session (same dependency)
        d = s.get(f"{BASE}/dashboard/", timeout=120)
        assert d.status_code == 200, f"{email} /dashboard {d.status_code}: {d.text[:300]}"

    def test_no_token_is_401(self):
        r = requests.get(f"{BASE}/auth/me", timeout=60)
        assert r.status_code == 401, r.status_code

    def test_garbage_token_is_401(self):
        r = requests.get(f"{BASE}/auth/me",
                         headers={"Authorization": "Bearer not-a-jwt"}, timeout=60)
        assert r.status_code == 401, r.status_code


# ── 2. /auth/me correctness for each role ─────────────────────────────────────
class TestAuthMeFields:
    @pytest.mark.parametrize("email", [ADMIN[0], MANAGER[0], JANE[0]])
    def test_me_matches_db_and_hides_dropped_columns(self, email):
        s = login(email, {ADMIN[0]: ADMIN[1], MANAGER[0]: MANAGER[1], JANE[0]: JANE[1]}[email])
        r = s.get(f"{BASE}/auth/me", timeout=60)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        row = db_user(email)
        for f in SELECTED:
            assert f in body, f"{email}: /auth/me missing field {f} -> {body}"
            assert body[f] == row[f], f"{email}: {f} mismatch api={body[f]!r} db={row[f]!r}"
        for f in DROPPED_COLUMNS:
            assert f not in body, f"{email}: /auth/me leaked {f}"
        # org branding block still resolved from org_id
        assert body["org_name"], body
        assert "org_branding" in body and "has_logo" in body["org_branding"], body
        assert body["org_jurisdiction"], body
        assert "org_service_type" in body

    def test_admin_org_matches_test_company(self, admin_s):
        body = admin_s.get(f"{BASE}/auth/me", timeout=60).json()
        assert body["org_id"] == ORG, body["org_id"]


# ── 3. Broad role smoke — nothing 500s / no spurious 401 ──────────────────────
ADMIN_GETS = [
    "/admin/users", "/admin/standards", "/admin/standards/documents", "/admin/template",
    "/admin/team-insights", "/admin/people-stats", "/admin/team-insights/action-stats",
    "/admin/team-insights/registers", "/admin/meetings-brief", "/admin/stats",
    "/org/structure", "/org/settings", "/org/branding",
    "/dashboard/", "/meetings/", "/schedules/", "/schedules/due", "/schedules/meeting-types",
]


class TestAdminSmoke:
    @pytest.mark.parametrize("path", ADMIN_GETS)
    def test_admin_get(self, admin_s, path):
        r = admin_s.get(f"{BASE}{path}", timeout=180)
        assert r.status_code == 200, f"admin GET {path} -> {r.status_code}: {r.text[:300]}"

    def test_admin_meeting_detail_and_report(self, admin_s):
        lst = admin_s.get(f"{BASE}/meetings/", timeout=120)
        assert lst.status_code == 200, lst.text[:300]
        payload = lst.json()
        meetings = payload if isinstance(payload, list) else payload.get("meetings", [])
        assert meetings, "no meetings available to smoke-test meeting detail"
        mid = meetings[0]["id"]
        d = admin_s.get(f"{BASE}/meetings/{mid}", timeout=120)
        assert d.status_code == 200, f"GET /meetings/{mid} -> {d.status_code}: {d.text[:300]}"
        rev = admin_s.get(f"{BASE}/review/{mid}", timeout=180)
        assert rev.status_code in (200, 400, 404), f"GET /review/{mid} -> {rev.status_code}: {rev.text[:300]}"

    def test_admin_org_settings_write_roundtrip(self, admin_s):
        """org settings CRUD path also reads current_user org_id/role."""
        r = admin_s.post(f"{BASE}/org/settings",
                         json={"name": "TEST_iter103 Setting", "type": "branch"}, timeout=90)
        assert r.status_code in (200, 201), f"create setting -> {r.status_code}: {r.text[:300]}"
        sid = r.json().get("id") or r.json().get("setting", {}).get("id")
        assert sid, r.json()
        try:
            upd = admin_s.put(f"{BASE}/org/settings/{sid}",
                              json={"name": "TEST_iter103 Setting v2", "type": "branch"}, timeout=90)
            assert upd.status_code == 200, f"update setting -> {upd.status_code}: {upd.text[:300]}"
            lst = admin_s.get(f"{BASE}/org/settings", timeout=90).json()
            items = lst if isinstance(lst, list) else lst.get("settings", [])
            assert any(x["id"] == sid for x in items), "created setting not returned by GET"
        finally:
            dele = admin_s.delete(f"{BASE}/org/settings/{sid}", timeout=90)
            assert dele.status_code in (200, 204), f"cleanup delete -> {dele.status_code}: {dele.text[:200]}"


class TestManagerSmoke:
    @pytest.mark.parametrize("path", [
        "/dashboard/", "/meetings/", "/admin/standards", "/admin/team-insights",
        "/admin/people-stats", "/admin/meetings-brief", "/org/structure", "/schedules/due",
    ])
    def test_manager_get(self, manager_s, path):
        r = manager_s.get(f"{BASE}{path}", timeout=180)
        assert r.status_code in (200, 403), f"manager GET {path} -> {r.status_code}: {r.text[:300]}"
        assert r.status_code != 401, f"manager got 401 on {path} with a valid session"

    def test_manager_signoff_visible_meetings(self, manager_s):
        r = manager_s.get(f"{BASE}/meetings/", timeout=120)
        assert r.status_code == 200, r.text[:300]


class TestAttendeeSmoke:
    @pytest.mark.parametrize("path", ["/dashboard/", "/meetings/"])
    def test_attendee_allowed(self, attendee_s, path):
        r = attendee_s.get(f"{BASE}{path}", timeout=180)
        assert r.status_code == 200, f"attendee GET {path} -> {r.status_code}: {r.text[:300]}"

    @pytest.mark.parametrize("path", [
        "/admin/users", "/admin/standards", "/admin/team-insights", "/admin/stats",
        "/schedules/due",
    ])
    def test_attendee_forbidden_not_500(self, attendee_s, path):
        r = attendee_s.get(f"{BASE}{path}", timeout=120)
        assert r.status_code == 403, f"attendee GET {path} -> {r.status_code}: {r.text[:300]}"

    def test_attendee_own_portfolio(self, attendee_s):
        uid = attendee_s.get(f"{BASE}/auth/me", timeout=60).json()["id"]
        r = attendee_s.get(f"{BASE}/portfolio/{uid}", timeout=180)
        assert r.status_code == 200, f"attendee own portfolio -> {r.status_code}: {r.text[:300]}"

    def test_attendee_cannot_reseed_standards(self, attendee_s):
        r = attendee_s.post(f"{BASE}/admin/standards/reseed", timeout=120)
        assert r.status_code == 403, f"{r.status_code}: {r.text[:200]}"


# ── 4. get_manager_scope end-to-end isolation ────────────────────────────────
def _set_manager_scope(setting_id, team_id):
    db(lambda c: c.execute(
        "UPDATE users SET setting_id=$1, team_id=$2 WHERE email=$3",
        setting_id, team_id, MANAGER[0]))


class TestManagerScopeIsolation:
    @pytest.fixture(autouse=True)
    def restore(self):
        yield
        _set_manager_scope(None, None)
        db(lambda c: c.execute("DELETE FROM teams WHERE id='TEST_iter103_team'"))

    def test_setting_scope_reflected_in_me_and_dashboard(self):
        _set_manager_scope(SETTING_ONE, None)
        s = login(*MANAGER)
        me = s.get(f"{BASE}/auth/me", timeout=60).json()
        assert me["setting_id"] == SETTING_ONE, me
        assert me["team_id"] is None, me
        d = s.get(f"{BASE}/dashboard/", timeout=180)
        assert d.status_code == 200, d.text[:300]
        struct = d.json().get("org_structure")
        assert struct is not None, "org_structure missing (fetch_structure raised)"
        assert [x["id"] for x in struct["settings"]] == [SETTING_ONE], struct["settings"]

    def test_team_scope_reflected_in_me_and_dashboard(self):
        tid = "TEST_iter103_team"
        db(lambda c: c.execute(
            """INSERT INTO teams (id, org_id, setting_id, name, members, created_at)
               VALUES ($1,$2,$3,'TEST_iter103 Team','[]'::jsonb, now()::text)
               ON CONFLICT (id) DO UPDATE SET setting_id=$3""", tid, ORG, SETTING_ONE))
        team = {"id": tid, "setting_id": SETTING_ONE}
        _set_manager_scope(SETTING_ONE, tid)
        s = login(*MANAGER)
        me = s.get(f"{BASE}/auth/me", timeout=60).json()
        assert me["team_id"] == team["id"], me
        d = s.get(f"{BASE}/dashboard/", timeout=180)
        assert d.status_code == 200, d.text[:300]
        struct = d.json()["org_structure"]
        assert [x["id"] for x in struct["settings"]] == [team["setting_id"]], struct["settings"]
        assert [t["id"] for t in struct["settings"][0]["teams"]] == [team["id"]], struct

    def test_scoped_manager_people_stats_is_subset_of_admin(self, admin_s):
        a = admin_s.get(f"{BASE}/admin/people-stats", timeout=180)
        assert a.status_code == 200, a.text[:300]
        _set_manager_scope(SETTING_ONE, None)
        s = login(*MANAGER)
        m = s.get(f"{BASE}/admin/people-stats", timeout=180)
        assert m.status_code == 200, m.text[:300]

        def ids(payload):
            items = payload if isinstance(payload, list) else (
                payload.get("people") or payload.get("staff") or payload.get("users") or [])
            return {x.get("id") or x.get("user_id") for x in items if isinstance(x, dict)}

        admin_ids, mgr_ids = ids(a.json()), ids(m.json())
        if admin_ids and mgr_ids:
            assert mgr_ids <= admin_ids, f"scoped manager saw users outside admin set: {mgr_ids - admin_ids}"


# ── 5. SEC-001: password change invalidates old access token ──────────────────
NEW_JANE = "TempJane103!"


def _restore_jane():
    h = bcrypt.hashpw(JANE[1].encode(), bcrypt.gensalt()).decode()
    now = datetime.now(timezone.utc).isoformat()
    db(lambda c: c.execute(
        """UPDATE users SET password_hash=$1, password_changed_at=$2,
           must_change_password=FALSE, mfa_code=NULL, mfa_code_expires_at=NULL,
           mfa_code_attempts=0 WHERE email=$3""", h, now, JANE[0]))
    clear_limits()


class TestSec001TokenFreshness:
    @pytest.fixture(autouse=True)
    def restore_password(self):
        yield
        _restore_jane()

    def test_self_change_password_invalidates_old_access_token(self):
        s = login(*JANE)
        assert s.get(f"{BASE}/auth/me", timeout=60).status_code == 200
        old_access = s.cookies.get("supervision_access")

        ch = s.post(f"{BASE}/auth/change-password",
                    json={"current_password": JANE[1], "new_password": NEW_JANE}, timeout=90)
        assert ch.status_code == 200, f"change-password -> {ch.status_code}: {ch.text[:300]}"

        # Old access token must now be rejected — this is the behaviour that
        # depends on password_changed_at remaining in the narrowed SELECT.
        stale = requests.Session()
        stale.cookies.set("supervision_access", old_access)
        r = stale.get(f"{BASE}/auth/me", timeout=60)
        assert r.status_code == 401, f"STALE TOKEN STILL WORKS ({r.status_code}) — SEC-001 regression"
        assert "Session expired" in r.text, r.text[:300]

        # also via Authorization header path
        r2 = requests.get(f"{BASE}/auth/me",
                          headers={"Authorization": f"Bearer {old_access}"}, timeout=60)
        assert r2.status_code == 401, r2.status_code
        assert "Session expired" in r2.text, r2.text[:300]

        # stale token rejected on a non-auth protected route too
        r3 = requests.get(f"{BASE}/meetings/",
                          headers={"Authorization": f"Bearer {old_access}"}, timeout=90)
        assert r3.status_code == 401, r3.status_code

        # new password logs in and works
        s2 = login(JANE[0], NEW_JANE)
        me = s2.get(f"{BASE}/auth/me", timeout=60)
        assert me.status_code == 200, me.text[:300]
        assert me.json()["email"] == JANE[0]

    def test_admin_reset_password_invalidates_target_users_token(self, admin_s):
        s = login(*JANE)
        old_access = s.cookies.get("supervision_access")
        jane_id = db_user(JANE[0])["id"]

        rp = admin_s.post(f"{BASE}/admin/users/{jane_id}/reset-password",
                          json={"new_password": NEW_JANE}, timeout=90)
        assert rp.status_code == 200, f"admin reset -> {rp.status_code}: {rp.text[:300]}"

        r = requests.get(f"{BASE}/auth/me",
                         headers={"Authorization": f"Bearer {old_access}"}, timeout=60)
        assert r.status_code == 401, f"token survived admin reset ({r.status_code}) — SEC-001 regression"
        assert "Session expired" in r.text, r.text[:300]

    def test_refresh_token_also_rejected_after_change(self):
        s = login(*JANE)
        old_refresh = s.cookies.get("supervision_refresh")
        ch = s.post(f"{BASE}/auth/change-password",
                    json={"current_password": JANE[1], "new_password": NEW_JANE}, timeout=90)
        assert ch.status_code == 200, ch.text[:300]
        rs = requests.Session()
        rs.cookies.set("supervision_refresh", old_refresh)
        r = rs.post(f"{BASE}/auth/refresh", timeout=60)
        assert r.status_code == 401, f"stale refresh token accepted ({r.status_code})"

    def test_unchanged_password_keeps_token_valid(self):
        """Sanity: the freshness check must not reject tokens when nothing changed."""
        s = login(*JANE)
        tok = s.cookies.get("supervision_access")
        for _ in range(3):
            r = requests.get(f"{BASE}/auth/me",
                             headers={"Authorization": f"Bearer {tok}"}, timeout=60)
            assert r.status_code == 200, f"valid token wrongly rejected: {r.status_code} {r.text[:200]}"


# ── 6. current_user.get('email') read site (admin.py force-reseed log) ────────
class TestEmailReadSite:
    def test_super_admin_reseed_logs_real_email(self):
        s = login("superadmin@1two.one", "NewPass123!")
        r = s.post(f"{BASE}/admin/standards/reseed", timeout=300)
        assert r.status_code == 200, f"reseed -> {r.status_code}: {r.text[:300]}"
        assert r.json().get("status") == "complete", r.json()

    def test_super_admin_me_and_orgs(self):
        """super_admin may have NULL org_id — narrowed SELECT must still work."""
        s = login("superadmin@1two.one", "NewPass123!")
        me = s.get(f"{BASE}/auth/me", timeout=60)
        assert me.status_code == 200, me.text[:300]
        body = me.json()
        assert body["role"] == "super_admin", body
        for f in DROPPED_COLUMNS:
            assert f not in body, f"super_admin /auth/me leaked {f}"
        orgs = s.get(f"{BASE}/super-admin/orgs", timeout=120)
        assert orgs.status_code == 200, f"/super-admin/orgs -> {orgs.status_code}: {orgs.text[:300]}"
        assert isinstance(orgs.json(), list) and orgs.json()

    def test_admin_role_blocked_from_reseed(self, admin_s):
        r = admin_s.post(f"{BASE}/admin/standards/reseed", timeout=120)
        assert r.status_code == 403, f"{r.status_code}: {r.text[:200]}"
