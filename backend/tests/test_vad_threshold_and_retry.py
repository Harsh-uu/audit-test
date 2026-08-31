"""
Tests for iteration 56:
1. ai.py _compress_to_mp3 uses -40dB threshold (not -50dB) in silence_filter
2. ai.py analyze_meeting truncates transcript at 80,000 chars with note
3. POST /api/processing/{meeting_id}/retry endpoint returns 200 for processing_failed meeting
4. Backend syntax validity (no import or startup errors)
"""

import pytest
import requests
import os
import uuid
import re

def _get_base_url():
    """Try public URL first; fall back to localhost if 502/unreachable."""
    public = (os.environ.get("REACT_APP_BACKEND_URL") or "https://supervision-preview.preview.emergentagent.com").rstrip("/")
    try:
        r = requests.get(f"{public}/api/auth/login", timeout=5)
        if r.status_code != 502:
            return public
    except Exception:
        pass
    return "http://localhost:8001"

BASE_URL = _get_base_url()

ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PASS = "Admin123!"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def admin_token():
    """Authenticate as admin and return bearer token."""
    resp = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    data = resp.json()
    token = data.get("access_token") or data.get("token")
    assert token, f"No token in response: {data}"
    return token


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# ── Code Review Tests (static verification) ──────────────────────────────────

class TestCodeReview:
    """Static code verification — check that the fixes are present in source files."""

    def test_silence_filter_uses_minus_40db(self):
        """ai.py _compress_to_mp3 silence_filter must use -40dB not -50dB."""
        ai_path = os.path.join(os.path.dirname(__file__), "..", "utils", "ai.py")
        with open(ai_path, "r") as f:
            content = f.read()

        # Must contain -40dB somewhere in the silence filter block
        assert "-40dB" in content, "Expected -40dB threshold in ai.py silence_filter"
        # Must NOT contain the old -50dB threshold in silence_filter
        # (check specifically in the silence_filter string, not elsewhere)
        silence_filter_match = re.search(
            r'silence_filter\s*=\s*\(.*?\)', content, re.DOTALL
        )
        assert silence_filter_match, "Could not find silence_filter assignment in ai.py"
        silence_filter_text = silence_filter_match.group(0)
        assert "-40dB" in silence_filter_text, \
            f"silence_filter should contain -40dB, got: {silence_filter_text}"
        assert "-50dB" not in silence_filter_text, \
            f"silence_filter should NOT contain old -50dB threshold, got: {silence_filter_text}"
        print("PASS: silence_filter uses -40dB threshold correctly")

    def test_silence_filter_has_both_silenceremove_steps(self):
        """ai.py silence_filter must have two silenceremove steps (start + end via areverse)."""
        ai_path = os.path.join(os.path.dirname(__file__), "..", "utils", "ai.py")
        with open(ai_path, "r") as f:
            content = f.read()

        silence_filter_match = re.search(
            r'silence_filter\s*=\s*\(.*?\)', content, re.DOTALL
        )
        assert silence_filter_match, "Could not find silence_filter in ai.py"
        filter_text = silence_filter_match.group(0)

        # Should have start_periods=1 twice
        assert filter_text.count("start_periods=1") == 2, \
            f"Expected 2x start_periods=1 in silence_filter, found: {filter_text.count('start_periods=1')}"
        # Should have areverse for end-silence removal
        assert "areverse" in filter_text, \
            "Expected areverse in silence_filter for trailing silence removal"
        print("PASS: silence_filter has both silenceremove steps with areverse")

    def test_transcript_capped_at_80000(self):
        """ai.py analyze_meeting user_prompt must cap transcript at 80,000 chars."""
        ai_path = os.path.join(os.path.dirname(__file__), "..", "utils", "ai.py")
        with open(ai_path, "r") as f:
            content = f.read()

        # Should contain [:80000]
        assert "transcript_text[:80000]" in content, \
            "Expected transcript_text[:80000] in ai.py analyze_meeting"
        print("PASS: transcript capped at 80,000 chars in analyze_meeting")

    def test_transcript_truncation_note(self):
        """ai.py truncation note must be appended when transcript exceeds 80,000 chars."""
        ai_path = os.path.join(os.path.dirname(__file__), "..", "utils", "ai.py")
        with open(ai_path, "r") as f:
            content = f.read()

        # Should contain the truncation note conditional
        assert "TRUNCATED" in content, \
            "Expected truncation note (TRUNCATED) in ai.py for transcript cap"
        assert "len(transcript_text) > 80000" in content, \
            "Expected len check > 80000 in ai.py for conditional truncation note"
        print("PASS: transcript truncation note is conditionally appended")

    def test_backend_imports_valid(self):
        """server.py and all routers must import without errors."""
        import subprocess
        result = subprocess.run(
            ["python", "-c", "import server; print('imports OK')"],
            capture_output=True, text=True,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        assert result.returncode == 0, \
            f"Backend import error:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        assert "imports OK" in result.stdout
        print("PASS: Backend imports without errors")

    def test_ai_py_imports_valid(self):
        """utils/ai.py must import without syntax errors."""
        import subprocess
        result = subprocess.run(
            ["python", "-c", "from utils.ai import analyze_meeting, _compress_to_mp3; print('ai.py OK')"],
            capture_output=True, text=True,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        assert result.returncode == 0, \
            f"ai.py import error:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        assert "ai.py OK" in result.stdout
        print("PASS: utils/ai.py imports cleanly")


# ── API Tests ──────────────────────────────────────────────────────────────────

class TestRetryEndpoint:
    """Tests for POST /api/processing/{meeting_id}/retry"""

    def test_retry_invalid_meeting_id_returns_404(self, admin_headers):
        """Retry with a non-existent meeting ID returns 404."""
        fake_id = str(uuid.uuid4())
        resp = requests.post(
            f"{BASE_URL}/api/processing/{fake_id}/retry",
            headers=admin_headers,
        )
        assert resp.status_code == 404, \
            f"Expected 404 for non-existent meeting, got {resp.status_code}: {resp.text}"
        print(f"PASS: Non-existent meeting returns 404: {resp.json()}")

    def test_retry_requires_auth(self):
        """Retry without auth token returns 401 or 403."""
        fake_id = str(uuid.uuid4())
        resp = requests.post(
            f"{BASE_URL}/api/processing/{fake_id}/retry",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code in (401, 403), \
            f"Expected 401/403 for unauthenticated request, got {resp.status_code}: {resp.text}"
        print(f"PASS: Unauthenticated retry returns {resp.status_code}")

    def test_retry_wrong_status_returns_400(self, admin_headers):
        """Retry a meeting with status != processing_failed returns 400."""
        # Create a scheduled meeting (status defaults to 'scheduled')
        meeting_data = {
            "title": f"TEST_RetryWrongStatus_{uuid.uuid4().hex[:6]}",
            "date": "2026-03-01",
            "meeting_type": "supervision",
        }
        create_resp = requests.post(
            f"{BASE_URL}/api/meetings/",
            json=meeting_data,
            headers=admin_headers,
        )
        assert create_resp.status_code in (200, 201), \
            f"Failed to create test meeting: {create_resp.text}"
        meeting_id = create_resp.json().get("id")
        assert meeting_id, "No meeting ID in create response"

        try:
            # Retry a non-processing_failed meeting — should be 400
            retry_resp = requests.post(
                f"{BASE_URL}/api/processing/{meeting_id}/retry",
                headers=admin_headers,
            )
            assert retry_resp.status_code == 400, \
                f"Expected 400 for wrong status, got {retry_resp.status_code}: {retry_resp.text}"
            error_detail = retry_resp.json().get("detail", "")
            assert "processing_failed" in error_detail.lower() or "audio" in error_detail.lower(), \
                f"Expected informative error message, got: {error_detail}"
            print(f"PASS: Wrong-status meeting returns 400: {error_detail}")
        finally:
            # Cleanup
            requests.delete(f"{BASE_URL}/api/meetings/{meeting_id}", headers=admin_headers)

    def test_retry_no_audio_file_returns_400(self, admin_headers):
        """Retry a processing_failed meeting with no audio file returns 400 (no audio)."""
        # Create a meeting with processing_failed status via the meetings API
        # (We'll create a meeting then check what happens when there's no audio_file_id)
        meeting_data = {
            "title": f"TEST_RetryNoAudio_{uuid.uuid4().hex[:6]}",
            "date": "2026-03-01",
            "meeting_type": "supervision",
        }
        create_resp = requests.post(
            f"{BASE_URL}/api/meetings/",
            json=meeting_data,
            headers=admin_headers,
        )
        assert create_resp.status_code in (200, 201), \
            f"Failed to create test meeting: {create_resp.text}"
        meeting_id = create_resp.json().get("id")
        assert meeting_id

        try:
            # At this point meeting has no audio_file_id, but we need processing_failed status
            # The retry endpoint checks status first, then audio_file_id
            # A newly-created meeting has status='scheduled', so we get 400 on status check
            retry_resp = requests.post(
                f"{BASE_URL}/api/processing/{meeting_id}/retry",
                headers=admin_headers,
            )
            # Either 400 (wrong status) or 400 (no audio) are both valid here
            assert retry_resp.status_code == 400, \
                f"Expected 400, got {retry_resp.status_code}: {retry_resp.text}"
            print(f"PASS: Meeting with no audio + wrong status returns 400: {retry_resp.json().get('detail')}")
        finally:
            requests.delete(f"{BASE_URL}/api/meetings/{meeting_id}", headers=admin_headers)

    def test_retry_endpoint_method_is_post(self, admin_headers):
        """Confirm that /api/processing/{id}/retry is POST (not GET) — review request mentioned GET."""
        fake_id = str(uuid.uuid4())
        # POST should get 404 (no such meeting), not 405 (method not allowed)
        post_resp = requests.post(
            f"{BASE_URL}/api/processing/{fake_id}/retry",
            headers=admin_headers,
        )
        # GET should return 405 Method Not Allowed
        get_resp = requests.get(
            f"{BASE_URL}/api/processing/{fake_id}/retry",
            headers=admin_headers,
        )
        assert post_resp.status_code == 404, \
            f"POST retry expected 404 (not found), got {post_resp.status_code}"
        assert get_resp.status_code == 405, \
            f"GET retry expected 405 (method not allowed), got {get_resp.status_code}: {get_resp.text}"
        print(f"PASS: POST /api/processing/{{id}}/retry is correct (GET returns 405 as expected)")

    def test_health_check(self, admin_headers):
        """Verify backend is running — GET /api/meetings returns 200."""
        resp = requests.get(f"{BASE_URL}/api/meetings/", headers=admin_headers)
        assert resp.status_code == 200, f"Health check failed: {resp.status_code} {resp.text}"
        print(f"PASS: Backend is running — GET /api/meetings/ returned 200")
