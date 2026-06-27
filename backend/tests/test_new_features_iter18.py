"""
Iteration 18 backend tests: Token refresh, retry endpoint, anonymise auth.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PASS = "Admin123!"
MANAGER_EMAIL = "manager@supervision.com"
MANAGER_PASS = "Manager123!"
STAFF_EMAIL = "staff@supervision.com"
STAFF_PASS = "Staff123!"

# Full meeting with transcript
MEETING_WITH_TRANSCRIPT = "6a3f88c620362dc4abb4f53d"
# Draft meeting (no analysis)
DRAFT_MEETING = "6a3ef1cbd1c3865fb94e3a02"
# Another in_review meeting
INREVIEW_MEETING = "6a3edddbe88c7907ae0bc103"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_login_data():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def manager_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": MANAGER_EMAIL, "password": MANAGER_PASS})
    assert r.status_code == 200
    return r.json()["token"]


@pytest.fixture(scope="module")
def staff_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": STAFF_EMAIL, "password": STAFF_PASS})
    assert r.status_code == 200
    return r.json()["token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ── Auth: login returns refresh_token ─────────────────────────────────────────

class TestAuthTokenRefresh:
    """Token refresh feature tests"""

    def test_login_returns_token(self, admin_login_data):
        assert "token" in admin_login_data
        assert isinstance(admin_login_data["token"], str)
        assert len(admin_login_data["token"]) > 10

    def test_login_returns_refresh_token(self, admin_login_data):
        assert "refresh_token" in admin_login_data, "Login response must include refresh_token"
        assert isinstance(admin_login_data["refresh_token"], str)
        assert len(admin_login_data["refresh_token"]) > 10

    def test_refresh_endpoint_with_bearer(self, admin_login_data):
        refresh_token = admin_login_data["refresh_token"]
        r = requests.post(
            f"{BASE_URL}/api/auth/refresh",
            headers={"Authorization": f"Bearer {refresh_token}"}
        )
        assert r.status_code == 200, f"Refresh failed: {r.text}"
        data = r.json()
        assert "access_token" in data, "Refresh response must include access_token"
        assert "refresh_token" in data

    def test_refreshed_token_works_for_me(self, admin_login_data):
        refresh_token = admin_login_data["refresh_token"]
        r = requests.post(
            f"{BASE_URL}/api/auth/refresh",
            headers={"Authorization": f"Bearer {refresh_token}"}
        )
        assert r.status_code == 200
        new_access = r.json()["access_token"]

        me_r = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {new_access}"})
        assert me_r.status_code == 200, f"/auth/me with refreshed token failed: {me_r.text}"
        assert "email" in me_r.json()

    def test_refresh_with_access_token_fails(self, admin_token):
        """Access token should not be accepted by /refresh endpoint"""
        r = requests.post(
            f"{BASE_URL}/api/auth/refresh",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert r.status_code == 401, "Should reject access token on /refresh"

    def test_refresh_without_token_fails(self):
        r = requests.post(f"{BASE_URL}/api/auth/refresh")
        assert r.status_code == 401


# ── Retry Processing ───────────────────────────────────────────────────────────

class TestRetryProcessing:
    """Retry endpoint tests"""

    def test_retry_in_review_meeting_returns_400(self, admin_token):
        """in_review meeting should not be retried"""
        r = requests.post(
            f"{BASE_URL}/api/processing/{INREVIEW_MEETING}/retry",
            headers=auth_headers(admin_token)
        )
        assert r.status_code == 400, f"Expected 400 for in_review, got {r.status_code}: {r.text}"

    def test_retry_draft_meeting_returns_400(self, admin_token):
        """Draft meeting with no audio should not be retried"""
        r = requests.post(
            f"{BASE_URL}/api/processing/{DRAFT_MEETING}/retry",
            headers=auth_headers(admin_token)
        )
        # Either 400 (not processing_failed) or 400 (no audio file)
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"

    def test_retry_invalid_meeting_returns_404(self, admin_token):
        r = requests.post(
            f"{BASE_URL}/api/processing/000000000000000000000000/retry",
            headers=auth_headers(admin_token)
        )
        assert r.status_code == 404

    def test_retry_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/processing/{INREVIEW_MEETING}/retry")
        assert r.status_code in [401, 403, 422]


# ── Anonymise auth ─────────────────────────────────────────────────────────────

class TestAnonymiseAuth:
    """Anonymise endpoint role checks"""

    def test_staff_cannot_anonymise(self, staff_token):
        r = requests.patch(
            f"{BASE_URL}/api/review/{MEETING_WITH_TRANSCRIPT}/anonymise",
            json={"phrase": "hello"},
            headers=auth_headers(staff_token)
        )
        assert r.status_code == 403, f"Expected 403 for staff, got {r.status_code}: {r.text}"

    def test_manager_can_anonymise_valid_phrase(self, manager_token):
        # Use a phrase unlikely to be in transcript (won't fail even if not found)
        r = requests.patch(
            f"{BASE_URL}/api/review/{MEETING_WITH_TRANSCRIPT}/anonymise",
            json={"phrase": "ZZZZNONEXISTENTPHRASEZZZZ"},
            headers=auth_headers(manager_token)
        )
        assert r.status_code == 200
        data = r.json()
        assert "replaced" in data
        assert data["replaced"] == False  # phrase not found, but no error

    def test_empty_phrase_returns_400(self, manager_token):
        r = requests.patch(
            f"{BASE_URL}/api/review/{MEETING_WITH_TRANSCRIPT}/anonymise",
            json={"phrase": "   "},
            headers=auth_headers(manager_token)
        )
        assert r.status_code == 400

    def test_admin_can_anonymise(self, admin_token):
        r = requests.patch(
            f"{BASE_URL}/api/review/{MEETING_WITH_TRANSCRIPT}/anonymise",
            json={"phrase": "ZZZZNONEXISTENTPHRASEZZZZ"},
            headers=auth_headers(admin_token)
        )
        assert r.status_code == 200
