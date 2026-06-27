"""Backend tests for POST /api/admin/users/{id}/reset-password endpoint"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
STAFF_ID = "6a3e5728bb3b2159b3c93f63"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@supervision.com", "password": "Admin123!"})
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    return r.cookies


@pytest.fixture(scope="module")
def staff_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "staff@supervision.com", "password": "Staff123!"})
    assert r.status_code == 200, f"Staff login failed: {r.text}"
    return r.cookies


class TestResetPasswordEndpoint:
    """POST /api/admin/users/{id}/reset-password"""

    def test_short_password_returns_400(self, admin_token):
        """Password < 8 chars returns 400"""
        r = requests.post(
            f"{BASE_URL}/api/admin/users/{STAFF_ID}/reset-password",
            json={"new_password": "short"},
            cookies=admin_token,
        )
        assert r.status_code == 400
        data = r.json()
        assert "Password must be at least 8 characters" in data.get("detail", "")

    def test_non_admin_returns_403(self, staff_token):
        """Non-admin calling reset-password returns 403"""
        r = requests.post(
            f"{BASE_URL}/api/admin/users/{STAFF_ID}/reset-password",
            json={"new_password": "ValidPass99!"},
            cookies=staff_token,
        )
        assert r.status_code == 403

    def test_admin_can_reset_password(self, admin_token):
        """Admin successfully resets a user password"""
        r = requests.post(
            f"{BASE_URL}/api/admin/users/{STAFF_ID}/reset-password",
            json={"new_password": "TempPass99!"},
            cookies=admin_token,
        )
        assert r.status_code == 200
        assert r.json().get("message") == "Password reset successfully"

    def test_user_can_login_with_new_password(self):
        """After reset, user can log in with new password"""
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "staff@supervision.com", "password": "TempPass99!"},
        )
        assert r.status_code == 200

    def test_restore_staff_password(self, admin_token):
        """Restore staff password to Staff123!"""
        r = requests.post(
            f"{BASE_URL}/api/admin/users/{STAFF_ID}/reset-password",
            json={"new_password": "Staff123!"},
            cookies=admin_token,
        )
        assert r.status_code == 200
        # verify login with original password works again
        r2 = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "staff@supervision.com", "password": "Staff123!"},
        )
        assert r2.status_code == 200
