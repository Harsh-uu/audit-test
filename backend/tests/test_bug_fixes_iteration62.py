"""
Tests for 3 bug fixes in iteration 62:
1. GET /api/admin/users/debug-by-email - no 500 error for null org_id users
2. GET /api/meetings/ for attendee user - should return list not 401/500
3. GET /api/auth/me returns org_branding field
4. POST /api/admin/users/fix-org-by-email works for admins
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PASSWORD = "Admin123!"
USER_EMAIL = "user@supervision.com"
USER_PASSWORD = "Staff123!"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    return r.json().get("token")


@pytest.fixture(scope="module")
def user_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": USER_EMAIL, "password": USER_PASSWORD})
    assert r.status_code == 200, f"User login failed: {r.text}"
    return r.json().get("token")


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# Bug 1: debug-by-email should not 500 for any user
class TestDebugByEmail:
    def test_debug_user_email_no_500(self, admin_token):
        """GET /api/admin/users/debug-by-email?email=user@supervision.com should return 200"""
        r = requests.get(
            f"{BASE_URL}/api/admin/users/debug-by-email",
            params={"email": USER_EMAIL},
            headers=auth(admin_token),
        )
        assert r.status_code == 200, f"Expected 200 got {r.status_code}: {r.text}"
        data = r.json()
        assert "user" in data
        assert "org_name" in data
        assert "meetings_as_attendee" in data
        assert "issues" in data  # can be None or list
        print(f"debug-by-email user result: issues={data.get('issues')}, org_name={data.get('org_name')}, meetings={data.get('meetings_as_attendee')}")

    def test_debug_admin_email_no_issues(self, admin_token):
        """GET /api/admin/users/debug-by-email?email=admin@supervision.com should have no issues"""
        r = requests.get(
            f"{BASE_URL}/api/admin/users/debug-by-email",
            params={"email": ADMIN_EMAIL},
            headers=auth(admin_token),
        )
        assert r.status_code == 200, f"Expected 200 got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("issues") is None, f"Admin user should have no issues, got: {data.get('issues')}"
        assert data.get("user", {}).get("role") in ("admin", "super_admin")
        print(f"debug-by-email admin: org_name={data.get('org_name')}")

    def test_debug_by_email_requires_admin(self, user_token):
        """Non-admin should get 403"""
        r = requests.get(
            f"{BASE_URL}/api/admin/users/debug-by-email",
            params={"email": USER_EMAIL},
            headers=auth(user_token),
        )
        assert r.status_code == 403


# Bug 2: attendee user should be able to list meetings
class TestAttendeeMeetingsList:
    def test_attendee_can_list_meetings(self, user_token):
        """GET /api/meetings/ for attendee should return 200 with a list"""
        r = requests.get(f"{BASE_URL}/api/meetings/", headers=auth(user_token))
        assert r.status_code == 200, f"Expected 200 got {r.status_code}: {r.text}"
        data = r.json()
        assert isinstance(data, list), f"Expected list got {type(data)}"
        print(f"Attendee meetings count: {len(data)}")

    def test_attendee_login_response_has_role(self, user_token):
        """Token from login should be valid and user endpoint returns role"""
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=auth(user_token))
        assert r.status_code == 200
        data = r.json()
        assert "role" in data
        assert data["role"] in ("attendee", "shared_reviewer", "admin", "manager")
        print(f"User role: {data['role']}, org_id: {data.get('org_id')}")


# Bug 3: auth/me returns org_branding
class TestAuthMe:
    def test_auth_me_returns_org_branding(self, admin_token):
        """GET /api/auth/me for admin should include org_branding field"""
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=auth(admin_token))
        assert r.status_code == 200, f"Expected 200 got {r.status_code}: {r.text}"
        data = r.json()
        assert "org_branding" in data, f"org_branding missing from /me response. Keys: {list(data.keys())}"
        print(f"org_branding: {data.get('org_branding')}")

    def test_admin_login_includes_role(self, admin_token):
        """Admin auth/me has correct role"""
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=auth(admin_token))
        assert r.status_code == 200
        data = r.json()
        assert data.get("role") == "admin", f"Expected admin role, got: {data.get('role')}"


# fix-org-by-email endpoint — P0-01 security fix verification
#
# Uses its own session-cookie login (not the Bearer-token `admin_token`
# fixture above, which pre-dates the cookie-based auth migration and no
# longer authenticates) and reads DATABASE_URL straight from backend/.env,
# matching the proven-working pattern in tests/test_idor_sec001.py.
import asyncio
import uuid
from datetime import datetime, timezone

import asyncpg
from dotenv import dotenv_values

_be_env = dotenv_values("/app/backend/.env")
_fe_env = dotenv_values("/app/frontend/.env")
_DSN = _be_env.get("DATABASE_URL")
# Module-level BASE_URL (above) relies on REACT_APP_BACKEND_URL being present
# in the backend process env, which it isn't when running pytest from
# /app/backend — fall back to reading it straight from frontend/.env.
_BASE_URL = BASE_URL or _fe_env.get("REACT_APP_BACKEND_URL", "").rstrip("/")


class TestFixOrgByEmailSecurity:
    """P0-01: an admin of any organisation was able to reassign ANY user
    (found by email, globally, no org filter) into their own org, with no
    check on the target's CURRENT org_id — even though the endpoint's own
    docstring says it exists only to repair users whose org_id is NULL.
    Once reassigned, the existing org-scoped reset-password/update-user
    endpoints would treat that user as the attacker's own, enabling full
    cross-tenant account takeover with zero audit trail.

    Fix: non-super_admin callers may now only repair a user whose org_id is
    CURRENTLY NULL (404 otherwise, same as "not found" to avoid leaking
    cross-org account existence), and every successful reassignment is now
    audit-logged (action=user_org_fixed_by_email).
    """

    @pytest.fixture(scope="class")
    def admin_session(self):
        s = requests.Session()
        r = s.post(f"{_BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": "Admin123!X"})
        assert r.status_code == 200, f"Admin login failed: {r.text}"
        me = s.get(f"{_BASE_URL}/api/auth/me")
        assert me.status_code == 200, f"/auth/me failed: {me.text}"
        org_id = me.json().get("org_id")
        assert org_id, "Admin has no org_id"
        return s, org_id

    @pytest.fixture
    def null_org_user(self):
        """Disposable user with org_id=NULL — the endpoint's documented
        legitimate use case. Created/removed per-test so it never pollutes
        other suites."""
        email = f"p0-01-nullorg-{uuid.uuid4().hex[:8]}@example.com"
        uid = str(uuid.uuid4())

        async def _create():
            conn = await asyncpg.connect(_DSN, ssl="require")
            try:
                await conn.execute(
                    "INSERT INTO users (id, email, password_hash, name, role, org_id, is_active, "
                    "must_change_password, created_at) VALUES ($1,$2,'x','P0-01 Test Fixture','attendee',"
                    "NULL,TRUE,TRUE,$3)",
                    uid, email, datetime.now(timezone.utc),
                )
            finally:
                await conn.close()

        async def _cleanup():
            conn = await asyncpg.connect(_DSN, ssl="require")
            try:
                await conn.execute(
                    "DELETE FROM audit_logs WHERE action='user_org_fixed_by_email' AND detail LIKE $1",
                    f"%{email}%",
                )
                await conn.execute("DELETE FROM users WHERE id=$1", uid)
            finally:
                await conn.close()

        asyncio.run(_create())
        yield uid, email
        asyncio.run(_cleanup())

    def test_blocks_reassigning_user_with_existing_org(self, admin_session):
        """A user who already has a non-NULL org_id (user@supervision.com,
        a DIFFERENT org in the real exploit scenario) must NOT be
        reassignable by a plain admin — must 404, not silently succeed."""
        session, admin_org_id = admin_session
        r = session.post(
            f"{_BASE_URL}/api/admin/users/fix-org-by-email",
            params={"email": USER_EMAIL},
            json={"org_id": admin_org_id},
        )
        assert r.status_code == 404, f"Expected 404 (org_id not NULL), got {r.status_code}: {r.text}"

    def test_repairs_user_with_null_org(self, admin_session, null_org_user):
        """The documented legitimate use case — repairing a NULL-org user
        into the caller's own org — must still work for a plain admin, and
        must now write an audit_logs row."""
        session, admin_org_id = admin_session
        uid, email = null_org_user
        r = session.post(
            f"{_BASE_URL}/api/admin/users/fix-org-by-email",
            params={"email": email},
            json={"org_id": admin_org_id},
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        assert r.json()["user_id"] == uid

        async def _check_audit():
            conn = await asyncpg.connect(_DSN, ssl="require")
            try:
                return await conn.fetchrow(
                    "SELECT detail FROM audit_logs WHERE action='user_org_fixed_by_email' AND detail LIKE $1",
                    f"%{email}%",
                )
            finally:
                await conn.close()

        audit_row = asyncio.run(_check_audit())
        assert audit_row is not None, "Expected an audit_logs row for this org reassignment"

    def test_cannot_assign_to_a_different_org_than_own(self, admin_session, null_org_user):
        """Non-super_admin destination restriction must still hold: even a
        NULL-org user cannot be assigned into an org the caller doesn't
        belong to."""
        session, _admin_org_id = admin_session
        _uid, email = null_org_user
        other_org_id = "3628a11d-36b8-42df-9d46-0479450ee22c"  # IDOR Test Org B fixture
        r = session.post(
            f"{_BASE_URL}/api/admin/users/fix-org-by-email",
            params={"email": email},
            json={"org_id": other_org_id},
        )
        assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"
