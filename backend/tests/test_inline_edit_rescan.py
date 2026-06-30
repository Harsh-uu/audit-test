"""Tests for inline transcript text editing and Re-scan Evidence features"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
MEETING_ID = "6a43d6fdfb1fc59f0685a936"  # Steve's org meeting with speaker_text


def get_token(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    return r.json().get("token")


@pytest.fixture(scope="module")
def manager_token():
    token = get_token("stevemikarics@gmail.com", "Steve123!")
    assert token, "Manager login failed"
    return token


@pytest.fixture(scope="module")
def staff_token():
    token = get_token("staff@supervision.com", "Staff123!")
    assert token, "Staff login failed"
    return token


# ─── Rescan Evidence endpoint ────────────────────────────────────────────────

class TestRescanEvidence:
    """POST /{meeting_id}/rescan-evidence"""

    def test_rescan_returns_200_for_manager(self, manager_token):
        r = requests.post(
            f"{BASE_URL}/api/review/{MEETING_ID}/rescan-evidence",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert "analysis" in data
        assert "message" in data

    def test_rescan_preserves_actions(self, manager_token):
        r = requests.post(
            f"{BASE_URL}/api/review/{MEETING_ID}/rescan-evidence",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert r.status_code == 200
        analysis = r.json()["analysis"]
        # actions should be preserved (not cleared)
        assert "actions" in analysis

    def test_rescan_returns_cqc_mappings(self, manager_token):
        r = requests.post(
            f"{BASE_URL}/api/review/{MEETING_ID}/rescan-evidence",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert r.status_code == 200
        analysis = r.json()["analysis"]
        assert "cqc_mappings" in analysis

    def test_rescan_returns_403_for_staff(self, staff_token):
        # Staff account trying to rescan Steve's meeting — should 403 (not in org)
        r = requests.post(
            f"{BASE_URL}/api/review/{MEETING_ID}/rescan-evidence",
            headers={"Authorization": f"Bearer {staff_token}"},
        )
        assert r.status_code in [403, 404], f"Expected 403/404, got {r.status_code}"

    def test_rescan_returns_401_without_token(self):
        r = requests.post(f"{BASE_URL}/api/review/{MEETING_ID}/rescan-evidence")
        assert r.status_code == 401


# ─── Speaker text PATCH endpoint ─────────────────────────────────────────────

class TestSpeakerTextPatch:
    """PATCH /{meeting_id}/speaker-text"""

    def test_patch_speaker_text_returns_200(self, manager_token):
        # Get current speaker text first
        r = requests.get(
            f"{BASE_URL}/api/meetings/{MEETING_ID}",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert r.status_code == 200
        original_text = r.json().get("transcript", {}).get("speaker_text", "")
        assert original_text, "No speaker_text on this meeting"

        # Patch
        patch_r = requests.patch(
            f"{BASE_URL}/api/review/{MEETING_ID}/speaker-text",
            headers={"Authorization": f"Bearer {manager_token}"},
            json={"speaker_text": original_text},  # re-save same text
        )
        assert patch_r.status_code == 200

    def test_patch_speaker_text_persists(self, manager_token):
        unique_marker = "TEST_INLINE_MARKER_12345"
        # Get original text
        r = requests.get(
            f"{BASE_URL}/api/meetings/{MEETING_ID}",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        lines = r.json().get("transcript", {}).get("speaker_text", "").split("\n")
        if not lines:
            pytest.skip("No speaker_text lines")

        # Modify first line and save
        modified = lines[0] + " " + unique_marker
        new_text = "\n".join([modified] + lines[1:])
        patch_r = requests.patch(
            f"{BASE_URL}/api/review/{MEETING_ID}/speaker-text",
            headers={"Authorization": f"Bearer {manager_token}"},
            json={"speaker_text": new_text},
        )
        assert patch_r.status_code == 200

        # Verify it was persisted
        get_r = requests.get(
            f"{BASE_URL}/api/meetings/{MEETING_ID}",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        saved_text = get_r.json().get("transcript", {}).get("speaker_text", "")
        assert unique_marker in saved_text, "Edit was not persisted to DB"

        # Restore original
        requests.patch(
            f"{BASE_URL}/api/review/{MEETING_ID}/speaker-text",
            headers={"Authorization": f"Bearer {manager_token}"},
            json={"speaker_text": "\n".join(lines)},
        )
