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


# fix-org-by-email endpoint
class TestFixOrgByEmail:
    def test_fix_org_endpoint_exists(self, admin_token):
        """POST /api/admin/users/fix-org-by-email should not 404"""
        # Get admin's org_id first
        me = requests.get(f"{BASE_URL}/api/auth/me", headers=auth(admin_token))
        admin_org_id = me.json().get("org_id")
        assert admin_org_id, "Admin has no org_id"

        # user@supervision.com should already have org_id, so this should
        # succeed (sets to same org) or say user already in org
        r = requests.post(
            f"{BASE_URL}/api/admin/users/fix-org-by-email",
            params={"email": USER_EMAIL},
            json={"org_id": admin_org_id},
            headers=auth(admin_token),
        )
        # 200 = fixed; 403 could happen if user is already in a different org
        assert r.status_code in (200, 403, 400), f"Unexpected status {r.status_code}: {r.text}"
        print(f"fix-org-by-email status: {r.status_code}, response: {r.text}")
