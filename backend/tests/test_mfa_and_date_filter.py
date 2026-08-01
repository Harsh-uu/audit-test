"""
Tests for: MFA 2FA flows (super_admin, verify-mfa, request-mfa-code, toggle-mfa, /me)
and Team Intelligence date filter API
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

SUPER_ADMIN_EMAIL = "superadmin@1two.one"
SUPER_ADMIN_PASS = "SuperAdmin123!"
ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PASS = "Admin123!"
MANAGER_EMAIL = "manager@supervision.com"
MANAGER_PASS = "Manager123!"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
    assert r.status_code == 200
    data = r.json()
    assert "token" in data
    return data["token"]


@pytest.fixture(scope="module")
def manager_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": MANAGER_EMAIL, "password": MANAGER_PASS})
    assert r.status_code == 200
    data = r.json()
    assert "token" in data
    return data["token"]


class TestMfaSuperAdmin:
    """Super admin login must require MFA - no direct token"""

    def test_superadmin_login_requires_mfa(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": SUPER_ADMIN_EMAIL, "password": SUPER_ADMIN_PASS})
        assert r.status_code == 200
        data = r.json()
        assert data.get("requires_mfa") is True, f"Expected requires_mfa=True, got: {data}"
        assert "mfa_session" in data, "No mfa_session in response"
        assert "email" in data
        assert "token" not in data, "Super admin should not get a direct token"

    def test_superadmin_login_no_direct_token(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": SUPER_ADMIN_EMAIL, "password": SUPER_ADMIN_PASS})
        data = r.json()
        assert "token" not in data


class TestVerifyMfa:
    """verify-mfa endpoint tests"""

    def test_verify_mfa_invalid_code_returns_401(self):
        # Get mfa_session from super admin login
        login_r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": SUPER_ADMIN_EMAIL, "password": SUPER_ADMIN_PASS})
        mfa_session = login_r.json().get("mfa_session")
        assert mfa_session, "No mfa_session from login"

        r = requests.post(f"{BASE_URL}/api/auth/verify-mfa", json={"mfa_session": mfa_session, "code": "999999"})
        assert r.status_code == 401
        data = r.json()
        assert "detail" in data

    def test_verify_mfa_invalid_session_returns_401(self):
        r = requests.post(f"{BASE_URL}/api/auth/verify-mfa", json={"mfa_session": "invalid.jwt.token", "code": "123456"})
        assert r.status_code == 401
        data = r.json()
        assert "Session expired" in data.get("detail", "") or "Invalid" in data.get("detail", "")


class TestRequestMfaCode:
    """request-mfa-code endpoint for admin/manager"""

    def test_request_mfa_code_manager(self, manager_token):
        r = requests.post(
            f"{BASE_URL}/api/auth/request-mfa-code",
            headers={"Authorization": f"Bearer {manager_token}"}
        )
        assert r.status_code == 200
        data = r.json()
        assert "message" in data
        assert "verification code" in data["message"].lower() or "sent" in data["message"].lower()

    def test_request_mfa_code_admin(self, admin_token):
        r = requests.post(
            f"{BASE_URL}/api/auth/request-mfa-code",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert r.status_code == 200


class TestToggleMfa:
    """toggle-mfa endpoint - wrong code should return 401"""

    def test_toggle_mfa_wrong_code_returns_401(self, manager_token):
        # First request a code
        requests.post(
            f"{BASE_URL}/api/auth/request-mfa-code",
            headers={"Authorization": f"Bearer {manager_token}"}
        )
        # Then try wrong code
        r = requests.post(
            f"{BASE_URL}/api/auth/toggle-mfa",
            json={"code": "000000", "enable": True},
            headers={"Authorization": f"Bearer {manager_token}"}
        )
        assert r.status_code == 401
        data = r.json()
        assert "Invalid code" in data.get("detail", "")


class TestMeEndpoint:
    """GET /me should not expose mfa_code fields, should expose mfa_enabled"""

    def test_me_hides_mfa_code_fields(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert r.status_code == 200
        data = r.json()
        assert "mfa_code" not in data
        assert "mfa_code_expires_at" not in data
        assert "mfa_code_attempts" not in data

    def test_me_exposes_mfa_enabled(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert r.status_code == 200
        data = r.json()
        assert "mfa_enabled" in data
        assert isinstance(data["mfa_enabled"], bool)


class TestTeamInsightsDateFilter:
    """GET /api/admin/team-insights with date_from/date_to params"""

    def test_team_insights_with_date_range(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/team-insights",
            params={"date_from": "2026-01-01", "date_to": "2026-12-31"},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert r.status_code == 200
        data = r.json()
        assert "staff_count" in data or "staff" in data, f"Unexpected response keys: {list(data.keys())}"

    def test_team_insights_without_date_range(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/team-insights",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert r.status_code == 200

    def test_normal_admin_login_no_mfa(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
        assert r.status_code == 200
        data = r.json()
        assert "token" in data
        assert data.get("requires_mfa") is not True
