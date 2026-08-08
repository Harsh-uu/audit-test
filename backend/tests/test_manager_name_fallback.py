"""
Test: manager_name fallback bug fix in processing.py
- Verifies that when a meeting is created WITHOUT sign_off_manager_id,
  the API returns created_by_name (the creator's name) and sign_off_manager_name is null.
- Also verifies the _ensure_dict fix is present in review.py for speaker_colors.
"""

import pytest
import requests
import os

def _load_base_url():
    """Load REACT_APP_BACKEND_URL from frontend .env if not already in environment."""
    url = os.environ.get("REACT_APP_BACKEND_URL", "")
    if not url:
        env_path = "/app/frontend/.env"
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        url = line.split("=", 1)[1].strip()
                        break
    return url.rstrip("/")

BASE_URL = _load_base_url()

# Test credentials
ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PASSWORD = "Admin123!"


@pytest.fixture(scope="module")
def auth_token():
    """Authenticate as admin (Daniel Okafor) and return token."""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD,
    })
    assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"
    data = resp.json()
    token = data.get("access_token") or data.get("token")
    assert token, "No token in login response"
    return token


@pytest.fixture(scope="module")
def admin_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_profile(auth_token):
    """Fetch the admin user's profile to get their actual name."""
    headers = {"Authorization": f"Bearer {auth_token}"}
    resp = requests.get(f"{BASE_URL}/api/auth/me", headers=headers)
    assert resp.status_code == 200, f"GET /auth/me failed: {resp.status_code} {resp.text}"
    return resp.json()


class TestManagerNameFallback:
    """Verify created_by_name is set and sign_off_manager_name is null when no manager is selected."""

    created_meeting_id = None

    def test_admin_has_name(self, admin_profile):
        """Admin profile must have a non-empty name (Daniel Okafor or similar)."""
        name = admin_profile.get("name") or admin_profile.get("full_name")
        assert name and len(name) > 0, f"Admin name is empty: {admin_profile}"
        print(f"Admin name: {name}")

    def test_create_meeting_without_sign_off_manager(self, admin_headers):
        """Create a meeting WITHOUT sign_off_manager_id."""
        payload = {
            "title": "TEST_FallbackManager Meeting",
            "date": "2026-02-15",
            "meeting_type": "supervision",
            "attendee_ids": [],
            # sign_off_manager_id intentionally omitted / null
        }
        resp = requests.post(f"{BASE_URL}/api/meetings/", json=payload, headers=admin_headers)
        assert resp.status_code == 200, f"Create meeting failed: {resp.status_code} {resp.text}"
        data = resp.json()

        # Store meeting_id for subsequent tests
        TestManagerNameFallback.created_meeting_id = data.get("id")
        assert TestManagerNameFallback.created_meeting_id, "No meeting id returned"
        print(f"Created meeting id: {TestManagerNameFallback.created_meeting_id}")

        # sign_off_manager_name should be null
        assert data.get("sign_off_manager_name") is None, (
            f"Expected sign_off_manager_name=null, got: {data.get('sign_off_manager_name')}"
        )
        print(f"sign_off_manager_name: {data.get('sign_off_manager_name')} (expected null) ✅")

        # created_by_name should be the admin's name
        created_by_name = data.get("created_by_name")
        assert created_by_name and len(created_by_name) > 0, (
            f"created_by_name is empty or null: {created_by_name}"
        )
        print(f"created_by_name: '{created_by_name}' ✅")

    def test_get_meeting_confirms_fields(self, admin_headers, admin_profile):
        """Fetch the meeting via GET and confirm sign_off_manager_name=null, created_by_name=admin name."""
        meeting_id = TestManagerNameFallback.created_meeting_id
        if not meeting_id:
            pytest.skip("No meeting_id available (create test failed)")

        resp = requests.get(f"{BASE_URL}/api/meetings/{meeting_id}", headers=admin_headers)
        assert resp.status_code == 200, f"GET meeting failed: {resp.status_code} {resp.text}"
        data = resp.json()

        # sign_off_manager_name must be null
        sign_off_manager_name = data.get("sign_off_manager_name")
        assert sign_off_manager_name is None, (
            f"Expected sign_off_manager_name=null but got: '{sign_off_manager_name}'"
        )
        print(f"GET: sign_off_manager_name={sign_off_manager_name} (null as expected) ✅")

        # created_by_name must match the admin's actual name
        created_by_name = data.get("created_by_name", "")
        admin_name = admin_profile.get("name") or admin_profile.get("full_name") or ""
        assert created_by_name and len(created_by_name) > 0, (
            f"created_by_name is empty in persisted row"
        )
        print(f"GET: created_by_name='{created_by_name}', admin_name='{admin_name}' ✅")

        # They should match
        assert created_by_name == admin_name, (
            f"created_by_name='{created_by_name}' does not match admin name='{admin_name}'"
        )
        print("created_by_name correctly matches admin's actual name ✅")

    def test_processing_py_fallback_logic_code_review(self):
        """
        Code-level assertion: verify all 3 occurrences in processing.py use the correct fallback.
        This reads the actual source file and checks the exact pattern.
        """
        import pathlib
        processing_path = pathlib.Path("/app/backend/routers/processing.py")
        assert processing_path.exists(), "processing.py not found at expected path"

        source = processing_path.read_text()
        expected_pattern = (
            "meeting.get('sign_off_manager_name') or meeting.get('created_by_name') or \"Manager\""
        )
        # Count occurrences of the fallback pattern
        occurrences = source.count(
            "meeting.get(\"sign_off_manager_name\") or meeting.get(\"created_by_name\") or \"Manager\""
        )
        print(f"Found {occurrences} occurrences of correct manager_name fallback in processing.py")
        assert occurrences == 3, (
            f"Expected 3 occurrences of the fallback pattern, found {occurrences}. "
            "Bug fix may be incomplete."
        )
        print("All 3 occurrences of manager_name fallback confirmed ✅")

    def test_review_py_ensure_dict_on_speaker_colors(self):
        """
        Code-level assertion: verify review.py applies _ensure_dict to speaker_colors at line ~193.
        """
        import pathlib
        review_path = pathlib.Path("/app/backend/routers/review.py")
        assert review_path.exists(), "review.py not found at expected path"

        source = review_path.read_text()
        assert '_ensure_dict' in source, "_ensure_dict helper not found in review.py"
        assert 'speaker_colors' in source, "speaker_colors field not referenced in review.py"

        # Check the specific assignment
        assert '_ensure_dict(t.get("speaker_colors"))' in source or \
               "_ensure_dict(t.get('speaker_colors'))" in source, (
            "Expected speaker_colors to be processed via _ensure_dict in review.py"
        )
        print("review.py: speaker_colors uses _ensure_dict() ✅")

    def test_cleanup_test_meeting(self, admin_headers):
        """Clean up: delete the test meeting."""
        meeting_id = TestManagerNameFallback.created_meeting_id
        if not meeting_id:
            return

        resp = requests.delete(f"{BASE_URL}/api/meetings/{meeting_id}", headers=admin_headers)
        print(f"Cleanup meeting {meeting_id}: status={resp.status_code}")
        # 200, 204, or 404 are acceptable cleanup outcomes
        assert resp.status_code in [200, 204, 404, 405], (
            f"Unexpected cleanup response: {resp.status_code} {resp.text}"
        )
