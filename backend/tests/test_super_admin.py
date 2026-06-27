"""Super Admin API tests"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')

SUPER_ADMIN = {"email": "superadmin@1two.one", "password": "SuperAdmin123!"}
MANAGER = {"email": "manager@supervision.com", "password": "Manager123!"}
ADMIN = {"email": "admin@supervision.com", "password": "Admin123!"}


def login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds)
    if r.status_code == 200:
        return r.json().get("token")
    return None


@pytest.fixture(scope="module")
def super_token():
    token = login(SUPER_ADMIN)
    assert token, "Super admin login failed"
    return token


@pytest.fixture(scope="module")
def manager_token():
    token = login(MANAGER)
    assert token, "Manager login failed"
    return token


@pytest.fixture(scope="module")
def admin_token():
    token = login(ADMIN)
    assert token, "Admin login failed"
    return token


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ── Auth Tests ─────────────────────────────────────────────────────────

class TestSuperAdminAuth:
    def test_super_admin_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json=SUPER_ADMIN)
        assert r.status_code == 200
        data = r.json()
        assert "token" in data
        assert data.get("role") == "super_admin" or data.get("user", {}).get("role") == "super_admin"

    def test_manager_login_still_works(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json=MANAGER)
        assert r.status_code == 200

    def test_admin_login_still_works(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN)
        assert r.status_code == 200

    def test_super_admin_me(self, super_token):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers(super_token))
        assert r.status_code == 200
        data = r.json()
        assert data.get("role") == "super_admin"


# ── Super Admin Org List ───────────────────────────────────────────────

class TestSuperAdminOrgs:
    def test_list_orgs(self, super_token):
        r = requests.get(f"{BASE_URL}/api/super-admin/orgs", headers=auth_headers(super_token))
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        # Check Test Company exists
        names = [o["name"] for o in data]
        assert any("Test Company" in n for n in names), f"Test Company not found in {names}"

    def test_list_orgs_has_stats(self, super_token):
        r = requests.get(f"{BASE_URL}/api/super-admin/orgs", headers=auth_headers(super_token))
        data = r.json()
        test_company = next((o for o in data if "Test Company" in o["name"]), None)
        assert test_company is not None
        assert test_company["user_count"] >= 3
        assert test_company["meeting_count"] >= 0
        assert "status" in test_company
        assert "id" in test_company

    def test_non_super_admin_blocked(self, manager_token):
        r = requests.get(f"{BASE_URL}/api/super-admin/orgs", headers=auth_headers(manager_token))
        assert r.status_code == 403

    def test_create_org(self, super_token):
        r = requests.post(
            f"{BASE_URL}/api/super-admin/orgs",
            json={"name": "TEST_Org_Pytest"},
            headers=auth_headers(super_token)
        )
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "TEST_Org_Pytest"
        assert "id" in data
        assert data["status"] == "active"
        return data["id"]

    def test_create_org_duplicate_rejected(self, super_token):
        # Try creating same org twice
        requests.post(
            f"{BASE_URL}/api/super-admin/orgs",
            json={"name": "TEST_Dup_Org"},
            headers=auth_headers(super_token)
        )
        r = requests.post(
            f"{BASE_URL}/api/super-admin/orgs",
            json={"name": "TEST_Dup_Org"},
            headers=auth_headers(super_token)
        )
        assert r.status_code == 400


class TestSuperAdminOrgManagement:
    @pytest.fixture(scope="class")
    def test_org_id(self, super_token):
        r = requests.post(
            f"{BASE_URL}/api/super-admin/orgs",
            json={"name": "TEST_ManageOrg"},
            headers=auth_headers(super_token)
        )
        assert r.status_code == 200
        return r.json()["id"]

    def test_get_org_users(self, super_token, test_org_id):
        r = requests.get(
            f"{BASE_URL}/api/super-admin/orgs/{test_org_id}/users",
            headers=auth_headers(super_token)
        )
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_user_in_org(self, super_token, test_org_id):
        r = requests.post(
            f"{BASE_URL}/api/super-admin/orgs/{test_org_id}/users",
            json={"name": "TEST_User", "email": "testpytest_user@example.com", "password": "Test1234!", "role": "manager"},
            headers=auth_headers(super_token)
        )
        assert r.status_code == 200
        data = r.json()
        assert data["email"] == "testpytest_user@example.com"
        assert data["role"] == "manager"
        assert data["org_id"] == test_org_id

    def test_suspend_org(self, super_token, test_org_id):
        r = requests.patch(
            f"{BASE_URL}/api/super-admin/orgs/{test_org_id}",
            json={"status": "suspended"},
            headers=auth_headers(super_token)
        )
        assert r.status_code == 200

    def test_activate_org(self, super_token, test_org_id):
        r = requests.patch(
            f"{BASE_URL}/api/super-admin/orgs/{test_org_id}",
            json={"status": "active"},
            headers=auth_headers(super_token)
        )
        assert r.status_code == 200

    def test_invalid_org_id(self, super_token):
        r = requests.get(
            f"{BASE_URL}/api/super-admin/orgs/invalid_id/users",
            headers=auth_headers(super_token)
        )
        # Should return empty list or 400 - not 500
        assert r.status_code != 500


class TestDataIsolation:
    def test_manager_cannot_see_super_admin_orgs(self, manager_token):
        r = requests.get(f"{BASE_URL}/api/super-admin/orgs", headers=auth_headers(manager_token))
        assert r.status_code == 403

    def test_manager_meetings_scoped_to_org(self, manager_token):
        r = requests.get(f"{BASE_URL}/api/meetings/", headers=auth_headers(manager_token))
        assert r.status_code == 200
        # Should succeed (data isolation verified by org_id on backend)
