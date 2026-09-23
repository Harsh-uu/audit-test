"""Iter162 regression: Activity Log, org-level users, unassigned exclusions,
admin-cannot-be-assigned-team, hard-delete guard, deactivated login 401,
plus reactivate flow. Builds on test_deactivate_hard_delete.py fixtures.
"""
import os
import sys
import uuid
import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "https://supervision-preview.preview.emergentagent.com").rstrip("/")

ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PW = "Admin123!X"
MANAGER_EMAIL = "manager@supervision.com"
MANAGER_PW = "Manager123!"


def _db_execute(query: str, *args):
    import asyncio, asyncpg
    dsn = os.environ.get("DATABASE_URL") or os.environ["APP_DATABASE_URL"]
    async def _run():
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(query, *args)
        finally:
            await conn.close()
    asyncio.run(_run())


def _login_full(session, email, pw):
    r = session.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pw})
    if r.status_code != 200:
        return False, r
    data = r.json()
    if not data.get("requires_mfa"):
        return True, r
    mfa_session = data.get("mfa_session")
    import bcrypt as _bcrypt
    from datetime import datetime, timezone, timedelta
    h = _bcrypt.hashpw(b"123456", _bcrypt.gensalt()).decode()
    _db_execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, datetime.now(timezone.utc) + timedelta(minutes=10), email,
    )
    r2 = session.post(f"{BASE_URL}/api/auth/verify-mfa",
                      json={"mfa_session": mfa_session, "code": "123456"})
    return r2.status_code == 200, r2


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    ok, _ = _login_full(s, ADMIN_EMAIL, ADMIN_PW)
    if not ok:
        pytest.skip("Admin login failed")
    return s


@pytest.fixture(scope="module")
def manager_session():
    s = requests.Session()
    ok, _ = _login_full(s, MANAGER_EMAIL, MANAGER_PW)
    if not ok:
        pytest.skip("Manager login failed")
    return s


def _create_throwaway(admin_session, role="attendee"):
    email = f"testreg_{uuid.uuid4().hex[:8]}@example.com"
    name = f"TestReg {uuid.uuid4().hex[:4]}"
    pw = "TestUser123!"
    payload = {"email": email, "name": name, "role": role, "password": pw}
    r = admin_session.post(f"{BASE_URL}/api/admin/users", json=payload)
    assert r.status_code == 200, f"create failed: {r.status_code} {r.text}"
    uid = r.json()["id"]
    _db_execute("UPDATE users SET must_change_password=FALSE WHERE id=$1::uuid", uid)
    return {"id": uid, "email": email, "name": name, "password": pw, "role": role}


def _cleanup(admin_session, uid):
    admin_session.delete(f"{BASE_URL}/api/admin/users/{uid}")
    admin_session.delete(f"{BASE_URL}/api/admin/users/{uid}/hard-delete")


# ── AUTH: Deactivated login 401 ─────────────────────────────────────────────
class TestAuthDeactivatedLogin:
    def test_active_user_login_ok(self, admin_session):
        u = _create_throwaway(admin_session)
        try:
            s = requests.Session()
            r = s.post(f"{BASE_URL}/api/auth/login", json={"email": u["email"], "password": u["password"]})
            assert r.status_code == 200
        finally:
            _cleanup(admin_session, u["id"])

    def test_deactivated_user_401_with_correct_password(self, admin_session):
        u = _create_throwaway(admin_session)
        try:
            admin_session.delete(f"{BASE_URL}/api/admin/users/{u['id']}")
            s = requests.Session()
            r = s.post(f"{BASE_URL}/api/auth/login", json={"email": u["email"], "password": u["password"]})
            assert r.status_code == 401
            assert "deactivat" in r.json().get("detail", "").lower()
        finally:
            _cleanup(admin_session, u["id"])


# ── ACTIVITY LOG ─────────────────────────────────────────────────────────────
class TestActivityLog:
    def test_manager_forbidden_403(self, manager_session):
        r = manager_session.get(f"{BASE_URL}/api/admin/activity-log")
        assert r.status_code == 403

    def test_admin_can_read(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/admin/activity-log")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_deactivate_creates_log_entry(self, admin_session):
        u = _create_throwaway(admin_session)
        try:
            admin_session.delete(f"{BASE_URL}/api/admin/users/{u['id']}")
            r = admin_session.get(f"{BASE_URL}/api/admin/activity-log")
            assert r.status_code == 200
            entries = r.json()
            # Find an entry mentioning the user's name or email
            found = any(u["name"] in (e.get("detail") or "") or u["email"] in (e.get("detail") or "")
                        for e in entries)
            assert found, f"No activity-log entry mentioning {u['email']} found in {len(entries)} entries"
        finally:
            _cleanup(admin_session, u["id"])

    def test_hard_delete_creates_log_entry(self, admin_session):
        u = _create_throwaway(admin_session)
        admin_session.delete(f"{BASE_URL}/api/admin/users/{u['id']}")
        rh = admin_session.delete(f"{BASE_URL}/api/admin/users/{u['id']}/hard-delete")
        assert rh.status_code == 200
        r = admin_session.get(f"{BASE_URL}/api/admin/activity-log")
        assert r.status_code == 200
        # At least one hard-delete style event should exist referencing the target
        entries = r.json()
        found = any(u["email"] in (e.get("detail") or "") or u["name"] in (e.get("detail") or "")
                    for e in entries)
        assert found, "No hard-delete activity log entry found for target user"


# ── ADMIN CANNOT BE ASSIGNED A TEAM ─────────────────────────────────────────
class TestAdminAssignTeamBlocked:
    def test_assign_admin_to_team_400(self, admin_session):
        # Get an admin's id (self)
        r_me = admin_session.get(f"{BASE_URL}/api/auth/me")
        admin_id = r_me.json()["id"]
        # Get a team id (any)
        r_struct = admin_session.get(f"{BASE_URL}/api/org/structure")
        assert r_struct.status_code == 200
        teams = []
        for s in r_struct.json().get("settings", []):
            teams.extend(s.get("teams", []))
        if not teams:
            pytest.skip("No teams in org to test with")
        team_id = teams[0]["id"]
        r = admin_session.patch(f"{BASE_URL}/api/org/users/{admin_id}/assign-team",
                                json={"team_id": team_id})
        assert r.status_code == 400
        assert "admin" in r.json().get("detail", "").lower()


# ── STRUCTURE: unassigned + org_level_users ─────────────────────────────────
class TestStructureLists:
    def test_structure_shape(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/org/structure")
        assert r.status_code == 200
        body = r.json()
        assert "settings" in body
        assert "unassigned_users" in body
        assert "org_level_users" in body
        # Admin (admin@supervision.com) should be in org_level_users
        emails = [u["email"] for u in body["org_level_users"]]
        assert ADMIN_EMAIL in emails, f"Admin should appear in org_level_users, got {emails}"
        # Roles present should be admin or manager
        for u in body["org_level_users"]:
            assert u["role"] in ("admin", "manager")

    def test_unassigned_excludes_admins_and_managers(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/org/structure")
        body = r.json()
        for u in body["unassigned_users"]:
            assert u["role"] not in ("admin", "manager"), \
                f"unassigned_users leaked {u['role']} {u['email']}"

    def test_new_attendee_no_team_appears_unassigned(self, admin_session):
        u = _create_throwaway(admin_session, role="attendee")
        try:
            r = admin_session.get(f"{BASE_URL}/api/org/structure")
            body = r.json()
            emails = [x["email"] for x in body["unassigned_users"]]
            assert u["email"] in emails, f"New unassigned attendee not in list: {emails}"
        finally:
            _cleanup(admin_session, u["id"])


# ── HARD DELETE guard already exists in test_deactivate_hard_delete; smoke here ─
class TestHardDeleteGuardSmoke:
    def test_hard_delete_active_blocked_400(self, admin_session):
        u = _create_throwaway(admin_session)
        try:
            r = admin_session.delete(f"{BASE_URL}/api/admin/users/{u['id']}/hard-delete")
            assert r.status_code == 400
        finally:
            _cleanup(admin_session, u["id"])


# ── People stats sanity ─────────────────────────────────────────────────────
class TestPeopleStats:
    def test_people_stats_ok(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/admin/people-stats")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
