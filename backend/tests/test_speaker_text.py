"""Tests for PATCH /api/review/{meeting_id}/speaker-text endpoint"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
MEETING_ID = "6a3f92df95f60e56302d0d5e"

MANAGER_CREDS = {"email": "manager@supervision.com", "password": "Manager123!"}
ADMIN_CREDS = {"email": "admin@supervision.com", "password": "Admin123!"}


def get_token(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds)
    if r.status_code == 200:
        return r.json().get("token")
    return None


@pytest.fixture(scope="module")
def manager_token():
    token = get_token(MANAGER_CREDS)
    if not token:
        pytest.skip("Manager login failed")
    return token


@pytest.fixture(scope="module")
def admin_token():
    token = get_token(ADMIN_CREDS)
    if not token:
        pytest.skip("Admin login failed")
    return token


class TestSpeakerTextEndpoint:
    """PATCH /api/review/{meeting_id}/speaker-text tests"""

    def test_patch_speaker_text_as_manager(self, manager_token):
        """Manager can update speaker_text — returns 200 with updated speaker_text"""
        new_text = "Manager: Hello, how are you today?\nWorker: I'm doing well, thank you."
        r = requests.patch(
            f"{BASE_URL}/api/review/{MEETING_ID}/speaker-text",
            json={"speaker_text": new_text},
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert "speaker_text" in data, "Response should contain speaker_text"
        assert data["speaker_text"] == new_text, "Response speaker_text should match the sent value"
        print("PASS: Manager can patch speaker_text")

    def test_patch_speaker_text_persists(self, manager_token):
        """After PATCH, GET meeting should return updated speaker_text"""
        new_text = "Sarah: Let's begin the session.\nJames: Sure, sounds good."
        requests.patch(
            f"{BASE_URL}/api/review/{MEETING_ID}/speaker-text",
            json={"speaker_text": new_text},
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        r = requests.get(
            f"{BASE_URL}/api/review/{MEETING_ID}",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert r.status_code == 200
        meeting = r.json()
        transcript = meeting.get("transcript", {})
        assert transcript.get("speaker_text") == new_text, "Persisted speaker_text should match"
        print("PASS: speaker_text persists after PATCH")

    def test_patch_speaker_text_unauthenticated(self):
        """No token should return 401 or 403"""
        r = requests.patch(
            f"{BASE_URL}/api/review/{MEETING_ID}/speaker-text",
            json={"speaker_text": "Speaker: test"},
        )
        assert r.status_code in [401, 403], f"Expected 401/403, got {r.status_code}"
        print("PASS: Unauthenticated request rejected")

    def test_patch_speaker_text_invalid_meeting(self, manager_token):
        """Non-existent meeting_id returns 404"""
        r = requests.patch(
            f"{BASE_URL}/api/review/000000000000000000000000/speaker-text",
            json={"speaker_text": "Speaker: hello"},
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert r.status_code == 404, f"Expected 404, got {r.status_code}"
        print("PASS: Invalid meeting returns 404")

    def test_patch_speaker_text_as_admin(self, admin_token):
        """Admin can also patch speaker_text"""
        new_text = "Admin Test: This is an admin correction.\nWorker: Acknowledged."
        r = requests.patch(
            f"{BASE_URL}/api/review/{MEETING_ID}/speaker-text",
            json={"speaker_text": new_text},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        print("PASS: Admin can patch speaker_text")

    def test_patch_speaker_text_403_staff(self):
        """Staff/worker role should get 403 — skip if no staff account available"""
        # Try to find a staff user - use a worker account if it exists
        staff_creds = {"email": "worker@supervision.com", "password": "Worker123!"}
        r = requests.post(f"{BASE_URL}/api/auth/login", json=staff_creds)
        if r.status_code != 200:
            pytest.skip("No staff account available for 403 test")
        token = r.json().get("token")
        patch_r = requests.patch(
            f"{BASE_URL}/api/review/{MEETING_ID}/speaker-text",
            json={"speaker_text": "Speaker: test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert patch_r.status_code == 403, f"Expected 403, got {patch_r.status_code}"
        print("PASS: Staff user correctly gets 403")

    def test_patch_restores_original_speaker_text(self, manager_token):
        """Restore speaker_text to a known good value for UI testing"""
        restore_text = "Sarah: Good morning, how have you been since our last session?\nJames: Things have been going well overall."
        r = requests.patch(
            f"{BASE_URL}/api/review/{MEETING_ID}/speaker-text",
            json={"speaker_text": restore_text},
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert r.status_code == 200
        print("PASS: Speaker text restored for UI testing")
