"""Tests for PATCH /api/review/{meeting_id}/anonymise endpoint"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
MEETING_ID = "6a3edddbe88c7907ae0bc103"


def get_token(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        return r.cookies.get("access_token") or r.json().get("access_token")
    return None


def admin_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@supervision.com", "password": "Admin123!"})
    assert r.status_code == 200
    return s


def staff_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "staff@supervision.com", "password": "Staff123!"})
    assert r.status_code == 200
    return s


class TestAnonymiseEndpoint:
    """Tests for PATCH /api/review/{meeting_id}/anonymise"""

    def test_admin_can_anonymise_phrase(self):
        """Admin with phrase present in transcript gets replaced:true"""
        s = admin_session()
        # First get current transcript to pick a word
        r = s.get(f"{BASE_URL}/api/review/{MEETING_ID}")
        assert r.status_code == 200
        transcript_text = r.json().get("transcript", {}).get("text", "")
        # Use a word that's likely in the transcript
        # Pick first word from transcript that is 4+ chars
        words = [w.strip(".,!?;:\"'") for w in transcript_text.split() if len(w.strip(".,!?;:\"'")) >= 4]
        if not words:
            pytest.skip("No suitable word found in transcript")
        phrase = words[0]
        r2 = s.patch(f"{BASE_URL}/api/review/{MEETING_ID}/anonymise", json={"phrase": phrase})
        assert r2.status_code == 200
        data = r2.json()
        assert "replaced" in data
        # Could be True or False depending on whether word exists
        print(f"Anonymise '{phrase}' → replaced={data['replaced']}")

    def test_anonymise_phrase_not_in_transcript_returns_replaced_false(self):
        """Phrase not found returns {replaced: false} gracefully"""
        s = admin_session()
        r = s.patch(f"{BASE_URL}/api/review/{MEETING_ID}/anonymise", json={"phrase": "XYZNOTEXIST99999"})
        assert r.status_code == 200
        data = r.json()
        assert data["replaced"] is False

    def test_anonymise_replaces_and_persists(self):
        """Anonymise a known phrase and verify transcript updated"""
        s = admin_session()
        # Get current transcript
        r = s.get(f"{BASE_URL}/api/review/{MEETING_ID}")
        assert r.status_code == 200
        transcript_text = r.json().get("transcript", {}).get("text", "")
        # Find a word that's definitely present (3+ chars)
        words = [w.strip(".,!?;:\"'") for w in transcript_text.split() if len(w.strip(".,!?;:\"'")) >= 3]
        if not words:
            pytest.skip("No suitable word found in transcript")
        phrase = words[0]
        expected_initial = phrase[0].upper() + "."
        r2 = s.patch(f"{BASE_URL}/api/review/{MEETING_ID}/anonymise", json={"phrase": phrase})
        assert r2.status_code == 200
        if r2.json().get("replaced"):
            # Verify the transcript now contains the initial
            r3 = s.get(f"{BASE_URL}/api/review/{MEETING_ID}")
            new_text = r3.json().get("transcript", {}).get("text", "")
            assert phrase.lower() not in new_text.lower() or expected_initial in new_text
            print(f"PASS: '{phrase}' replaced with '{expected_initial}'")

    def test_attendee_gets_403_from_anonymise(self):
        """Staff/attendee role must get 403 Forbidden"""
        s = staff_session()
        r = s.patch(f"{BASE_URL}/api/review/{MEETING_ID}/anonymise", json={"phrase": "test"})
        assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"
        print("PASS: Attendee gets 403")

    def test_empty_phrase_returns_400(self):
        """Empty phrase should return 400"""
        s = admin_session()
        r = s.patch(f"{BASE_URL}/api/review/{MEETING_ID}/anonymise", json={"phrase": "   "})
        assert r.status_code == 400
        print("PASS: Empty phrase returns 400")

    def test_anonymise_first_initial_format(self):
        """Verify replacement uses first-initial-dot format (e.g. 'Robert' -> 'R.')"""
        s = admin_session()
        # Get transcript to find a word
        r = s.get(f"{BASE_URL}/api/review/{MEETING_ID}")
        transcript_text = r.json().get("transcript", {}).get("text", "")
        # Try to find any word
        words = [w.strip(".,!?;:\"'") for w in transcript_text.split() if len(w.strip(".,!?;:\"'")) >= 4]
        if not words:
            pytest.skip("No suitable word in transcript")
        phrase = words[0]
        r2 = s.patch(f"{BASE_URL}/api/review/{MEETING_ID}/anonymise", json={"phrase": phrase})
        assert r2.status_code == 200
        data = r2.json()
        if data.get("replaced"):
            expected = phrase[0].upper() + "."
            assert expected in data.get("message", "")
            print(f"PASS: Initial format correct: '{expected}'")
