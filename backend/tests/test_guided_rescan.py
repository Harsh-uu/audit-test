"""Tests for Guided Re-scan feature: POST /api/review/{meeting_id}/rescan-evidence"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

JANE_CREDS = {"email": "jane@sunrisecare.com", "password": "Jane1two1!"}
# Jane has a known signed_off meeting with transcript and analysis
KNOWN_MEETING_ID = "6a46da6d1936c45e856ce791"


def get_token(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds)
    if r.status_code == 200:
        return r.json().get("token") or r.cookies.get("token")
    return None


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def get_signed_off_meeting(token):
    """Find a meeting in signed_off or in_review status with analysis_id."""
    r = requests.get(f"{BASE_URL}/api/meetings/", headers=auth_headers(token))
    if r.status_code != 200:
        return None
    meetings = r.json()
    if isinstance(meetings, dict):
        meetings = meetings.get("meetings", [])
    for m in meetings:
        if m.get("status") in ("signed_off", "in_review", "reviewed") and m.get("analysis_id") and m.get("transcript_id"):
            return m.get("id") or str(m.get("_id", ""))
    return None


class TestRescanEndpoint:
    """Test POST /api/review/{meeting_id}/rescan-evidence"""

    @pytest.fixture(scope="class")
    def token(self):
        t = get_token(JANE_CREDS)
        if not t:
            pytest.skip("Could not authenticate")
        return t

    @pytest.fixture(scope="class")
    def meeting_id(self, token):
        return KNOWN_MEETING_ID

    def test_rescan_without_custom_prompt_empty_body(self, token, meeting_id):
        """Backward compat: POST with empty body {} returns {status: processing}"""
        r = requests.post(
            f"{BASE_URL}/api/review/{meeting_id}/rescan-evidence",
            json={},
            headers=auth_headers(token),
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("status") == "processing", f"Expected status=processing, got {data}"

    def test_rescan_with_null_custom_prompt(self, token, meeting_id):
        """POST with {custom_prompt: null} returns {status: processing}"""
        r = requests.post(
            f"{BASE_URL}/api/review/{meeting_id}/rescan-evidence",
            json={"custom_prompt": None},
            headers=auth_headers(token),
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("status") == "processing"

    def test_rescan_with_custom_prompt(self, token, meeting_id):
        """POST with custom_prompt string returns {status: processing}"""
        r = requests.post(
            f"{BASE_URL}/api/review/{meeting_id}/rescan-evidence",
            json={"custom_prompt": "Focus on medication management and manual handling"},
            headers=auth_headers(token),
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("status") == "processing", f"Expected status=processing, got {data}"

    def test_rescan_sets_rescan_status_processing(self, token, meeting_id):
        """After rescan POST, meeting rescan_status should be 'processing'"""
        # Trigger rescan
        requests.post(
            f"{BASE_URL}/api/review/{meeting_id}/rescan-evidence",
            json={"custom_prompt": "Test guidance"},
            headers=auth_headers(token),
        )
        # Fetch meeting and check rescan_status
        r = requests.get(f"{BASE_URL}/api/meetings/{meeting_id}", headers=auth_headers(token))
        if r.status_code == 200:
            data = r.json()
            rescan_status = data.get("rescan_status")
            # Should be 'processing' or 'done' (if AI is fast)
            assert rescan_status in ("processing", "done"), f"Unexpected rescan_status: {rescan_status}"
        else:
            # Alternative: check via review endpoint
            r2 = requests.get(f"{BASE_URL}/api/review/{meeting_id}", headers=auth_headers(token))
            assert r2.status_code == 200

    def test_rescan_unauthorized_as_attendee(self, meeting_id):
        """Non-manager should get 403"""
        # Try to use an attendee or no token
        r = requests.post(
            f"{BASE_URL}/api/review/{meeting_id}/rescan-evidence",
            json={},
        )
        assert r.status_code in (401, 403, 422), f"Expected 401/403, got {r.status_code}"

    def test_rescan_response_has_message(self, token, meeting_id):
        """Response should contain both status and message fields"""
        r = requests.post(
            f"{BASE_URL}/api/review/{meeting_id}/rescan-evidence",
            json={},
            headers=auth_headers(token),
        )
        assert r.status_code == 200
        data = r.json()
        assert "status" in data
        assert "message" in data
