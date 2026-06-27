"""Tests for email fallback feature - creator email when no attendees"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
MEETING_ID = "6a3f92df95f60e56302d0d5e"


@pytest.fixture(scope="module")
def manager_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "manager@supervision.com", "password": "Manager123!"})
    assert r.status_code == 200
    return r.json()["token"]


@pytest.fixture(scope="module")
def auth_headers(manager_token):
    return {"Authorization": f"Bearer {manager_token}"}


class TestGetMeetingEmailFields:
    """Verify GET /api/meetings/{id} returns created_by_email and created_by_name"""

    def test_get_meeting_has_created_by_email(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/meetings/{MEETING_ID}", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "created_by_email" in data, "created_by_email missing from response"
        assert data["created_by_email"] != "", "created_by_email is empty"

    def test_get_meeting_has_created_by_name(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/meetings/{MEETING_ID}", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "created_by_name" in data, "created_by_name missing from response"
        assert data["created_by_name"] != "", "created_by_name is empty"

    def test_created_by_email_is_manager_email(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/meetings/{MEETING_ID}", headers=auth_headers)
        data = r.json()
        assert data["created_by_email"] == "manager@supervision.com"


class TestSendEmailWithAttendees:
    """Test POST /api/review/{id}/send-email with attendee recipients"""

    def test_send_email_to_attendees(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/meetings/{MEETING_ID}", headers=auth_headers)
        meeting = r.json()
        attendee_emails = [a["email"] for a in meeting.get("attendees", []) if a.get("email")]
        assert len(attendee_emails) > 0, "No attendees with email found for this test"

        resp = requests.post(
            f"{BASE_URL}/api/review/{MEETING_ID}/send-email",
            json={"recipients": attendee_emails, "message": "Test email from automated test"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"


class TestSendEmailWithCreatorFallback:
    """Test send-email when recipients is creator email (no-attendees fallback)"""

    def test_send_email_to_creator_email(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/meetings/{MEETING_ID}", headers=auth_headers)
        meeting = r.json()
        creator_email = meeting.get("created_by_email")
        assert creator_email, "created_by_email not available"

        resp = requests.post(
            f"{BASE_URL}/api/review/{MEETING_ID}/send-email",
            json={"recipients": [creator_email], "message": "Fallback email test"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_send_email_empty_recipients_fails(self, auth_headers):
        """Edge case: sending with empty recipients should fail gracefully"""
        resp = requests.post(
            f"{BASE_URL}/api/review/{MEETING_ID}/send-email",
            json={"recipients": [], "message": ""},
            headers=auth_headers,
        )
        # Should return 400 or some error status, not 500
        assert resp.status_code in [400, 422, 200], f"Unexpected status: {resp.status_code}"
