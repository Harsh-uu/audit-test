"""
Tests for iteration 59 — _jlist() helper fix for asyncpg JSONB stringification bug.

Root cause: asyncpg returns attendees JSONB column as a raw string when RLS role
(with_org() context) is active. Code was then calling .get() on each character,
causing 'str object has no attribute get'.

Fix: _jlist() helper added at lines 18-24. Applied to all 6 attendees reads.

Verifies:
1. _jlist() helper is defined in processing.py (lines 18-24)
2. All 6 attendees reads use _jlist() — lines 57, 106, 213, 497, 588, 598
3. No remaining bare .get('attendees') calls outside _jlist()
4. Backend starts with no errors (import test)
5. GET /api/meetings/{id} returns processing_error field
6. POST /api/processing/{id}/retry returns 200 for a valid meeting
"""

import pytest
import requests
import os
import re
import uuid

# ── Base URL ──────────────────────────────────────────────────────────────────

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
if not BASE_URL:
    raise RuntimeError("REACT_APP_BACKEND_URL not set")

ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PASS = "Admin123!"

PROCESSING_PY = os.path.join(os.path.dirname(__file__), "..", "routers", "processing.py")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def processing_content():
    """Read processing.py once for all static tests."""
    with open(PROCESSING_PY, "r") as f:
        return f.read()


@pytest.fixture(scope="module")
def processing_lines(processing_content):
    """Return processing.py as list of lines (1-indexed: lines[0] = line 1)."""
    return processing_content.splitlines()


@pytest.fixture(scope="module")
def admin_token():
    """Authenticate as admin and return bearer token."""
    resp = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
        timeout=15,
    )
    assert resp.status_code == 200, f"Login failed ({resp.status_code}): {resp.text}"
    data = resp.json()
    token = data.get("access_token") or data.get("token")
    assert token, f"No token in login response: {data}"
    return token


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# ── 1. _jlist() helper definition ─────────────────────────────────────────────

class TestJlistHelperDefined:
    """Verify _jlist() helper is defined in processing.py at the expected location."""

    def test_jlist_function_exists(self, processing_content):
        """_jlist() must be defined in processing.py."""
        assert "def _jlist(" in processing_content, (
            "_jlist() function not found in processing.py — fix not applied"
        )
        print("PASS: def _jlist() found in processing.py")

    def test_jlist_defined_near_top(self, processing_lines):
        """_jlist() should be defined early in the file (lines 15-30) before first use."""
        for i, line in enumerate(processing_lines, start=1):
            if "def _jlist(" in line:
                assert i <= 30, (
                    f"_jlist() defined at line {i}, expected at lines 15-30 (before first use at line 57)"
                )
                print(f"PASS: _jlist() defined at line {i} (within expected range 15-30)")
                return
        pytest.fail("_jlist() not found in processing.py")

    def test_jlist_handles_list_input(self, processing_content):
        """_jlist() must have: if isinstance(val, list): return val"""
        assert "isinstance(val, list)" in processing_content, (
            "_jlist() must check isinstance(val, list) to pass lists through directly"
        )
        print("PASS: _jlist() checks isinstance(val, list)")

    def test_jlist_handles_string_input(self, processing_content):
        """_jlist() must handle string values by JSON-parsing them."""
        assert "isinstance(val, str)" in processing_content, (
            "_jlist() must check isinstance(val, str) to JSON-parse asyncpg-returned strings"
        )
        assert "json.loads(val)" in processing_content, (
            "_jlist() must call json.loads(val) to parse string JSONB"
        )
        print("PASS: _jlist() handles str input via json.loads()")

    def test_jlist_has_safe_fallback(self, processing_content):
        """_jlist() must return [] as fallback on any failure."""
        # Find the _jlist function block and check for empty list fallback
        match = re.search(
            r'def _jlist\(.*?\n(?:.*\n){0,10}',
            processing_content,
        )
        assert "return []" in processing_content or "return val or []" in processing_content, (
            "_jlist() must return [] as fallback (either 'return []' or 'return val or []')"
        )
        print("PASS: _jlist() has [] fallback")


# ── 2. All 6 attendees reads use _jlist() ─────────────────────────────────────

class TestAllAttendeesReadsUseJlist:
    """Verify every .get('attendees') call is wrapped in _jlist()."""

    def test_line_57_uses_jlist(self, processing_lines):
        """Line 57: _get_rolled_actions must use _jlist(prev.get('attendees'))."""
        line = processing_lines[56]  # 0-indexed → line 57
        assert "_jlist(" in line and "attendees" in line, (
            f"Line 57 expected _jlist(prev.get('attendees')), got: {line!r}"
        )
        print(f"PASS: Line 57 uses _jlist(): {line.strip()}")

    def test_line_106_uses_jlist(self, processing_lines):
        """Line 106: run_transcription_and_analysis must use _jlist(meeting.get('attendees'))."""
        line = processing_lines[105]  # 0-indexed → line 106
        assert "_jlist(" in line and "attendees" in line, (
            f"Line 106 expected _jlist(meeting.get('attendees')), got: {line!r}"
        )
        print(f"PASS: Line 106 uses _jlist(): {line.strip()}")

    def test_line_213_uses_jlist(self, processing_lines):
        """Line 213: run_transcription_and_analysis must use _jlist(meeting.get('attendees'))."""
        line = processing_lines[212]  # 0-indexed → line 213
        assert "_jlist(" in line and "attendees" in line, (
            f"Line 213 expected _jlist(meeting.get('attendees')), got: {line!r}"
        )
        print(f"PASS: Line 213 uses _jlist(): {line.strip()}")

    def test_line_497_uses_jlist(self, processing_lines):
        """Line 497: diarize_meeting_transcript must use _jlist(meeting.get('attendees'))."""
        line = processing_lines[496]  # 0-indexed → line 497
        assert "_jlist(" in line and "attendees" in line, (
            f"Line 497 expected _jlist(meeting.get('attendees')), got: {line!r}"
        )
        print(f"PASS: Line 497 uses _jlist(): {line.strip()}")

    def test_line_588_uses_jlist(self, processing_lines):
        """Line 588: _run_retranscribe_background attendee_count must use _jlist()."""
        line = processing_lines[587]  # 0-indexed → line 588
        assert "_jlist(" in line and "attendees" in line, (
            f"Line 588 expected _jlist(meeting.get('attendees')), got: {line!r}"
        )
        print(f"PASS: Line 588 uses _jlist(): {line.strip()}")

    def test_line_598_uses_jlist(self, processing_lines):
        """Line 598: _run_retranscribe_background attendees list must use _jlist()."""
        line = processing_lines[597]  # 0-indexed → line 598
        assert "_jlist(" in line and "attendees" in line, (
            f"Line 598 expected _jlist(meeting.get('attendees')), got: {line!r}"
        )
        print(f"PASS: Line 598 uses _jlist(): {line.strip()}")

    def test_exactly_6_jlist_attendees_calls(self, processing_content):
        """There must be exactly 6 _jlist() calls involving 'attendees' in processing.py."""
        # Find all lines with both _jlist( and attendees
        lines = processing_content.splitlines()
        jlist_attendees_lines = [
            (i + 1, line.strip())
            for i, line in enumerate(lines)
            if "_jlist(" in line and "attendees" in line
        ]
        print(f"_jlist() + attendees calls found at lines: {[(n, l) for n, l in jlist_attendees_lines]}")
        assert len(jlist_attendees_lines) == 6, (
            f"Expected exactly 6 _jlist() calls with 'attendees', found {len(jlist_attendees_lines)}: "
            f"{jlist_attendees_lines}"
        )
        print(f"PASS: Exactly 6 _jlist()+attendees calls found")


# ── 3. No bare attendees reads remain ─────────────────────────────────────────

class TestNoBareattendeesReads:
    """Verify there are no bare .get('attendees') calls not wrapped in _jlist()."""

    def test_no_bare_meeting_get_attendees(self, processing_lines):
        """No line should have meeting.get('attendees') or meeting.get(\"attendees\") outside _jlist()."""
        violations = []
        for i, line in enumerate(processing_lines, start=1):
            # Skip lines that are inside _jlist() call (those are fine)
            if "_jlist(" in line:
                continue
            # Skip SQL queries (attendees in SQL is fine)
            stripped = line.strip()
            if stripped.startswith('"') or stripped.startswith("'") or stripped.startswith("SELECT"):
                continue
            # Check for bare meeting.get('attendees') or meeting.get("attendees")
            if re.search(r'meeting\.get\(["\']attendees["\']', line):
                violations.append((i, line.strip()))

        assert not violations, (
            f"Found bare meeting.get('attendees') calls NOT wrapped in _jlist():\n"
            + "\n".join(f"  Line {n}: {l}" for n, l in violations)
        )
        print("PASS: No bare meeting.get('attendees') calls outside _jlist()")

    def test_no_bare_prev_get_attendees(self, processing_lines):
        """No line should have prev.get('attendees') outside _jlist()."""
        violations = []
        for i, line in enumerate(processing_lines, start=1):
            if "_jlist(" in line:
                continue
            if re.search(r'prev\.get\(["\']attendees["\']', line):
                violations.append((i, line.strip()))

        assert not violations, (
            f"Found bare prev.get('attendees') calls NOT wrapped in _jlist():\n"
            + "\n".join(f"  Line {n}: {l}" for n, l in violations)
        )
        print("PASS: No bare prev.get('attendees') calls outside _jlist()")

    def test_no_direct_square_bracket_attendees(self, processing_lines):
        """No line should have meeting['attendees'] or prev['attendees'] (dict access) outside _jlist()."""
        violations = []
        for i, line in enumerate(processing_lines, start=1):
            if "_jlist(" in line:
                continue
            stripped = line.strip()
            if stripped.startswith('"') or stripped.startswith("'"):
                continue
            if re.search(r'(meeting|prev)\[["\']attendees["\']', line):
                violations.append((i, line.strip()))

        assert not violations, (
            f"Found bare dict['attendees'] accesses NOT wrapped in _jlist():\n"
            + "\n".join(f"  Line {n}: {l}" for n, l in violations)
        )
        print("PASS: No bare dict['attendees'] accesses outside _jlist()")


# ── 4. Backend starts with no errors ──────────────────────────────────────────

class TestBackendStartsCleanly:
    """Verify the processing router and server import without errors."""

    def test_processing_router_imports_cleanly(self):
        """routers/processing.py must import without syntax or module errors."""
        import subprocess
        result = subprocess.run(
            ["python", "-c", "from routers.processing import router, _jlist; print('OK')"],
            capture_output=True, text=True,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        assert result.returncode == 0, (
            f"processing.py import error:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
        assert "OK" in result.stdout, f"Expected 'OK' in stdout: {result.stdout}"
        print("PASS: routers/processing.py (including _jlist) imports cleanly")

    def test_jlist_can_be_imported(self):
        """_jlist must be importable from routers.processing."""
        import subprocess
        result = subprocess.run(
            ["python", "-c",
             "from routers.processing import _jlist; "
             "assert _jlist([1,2]) == [1,2]; "
             "assert _jlist('[1,2]') == [1,2]; "
             "assert _jlist(None) == []; "
             "assert _jlist('bad json') == []; "
             "print('_jlist works correctly')"],
            capture_output=True, text=True,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        assert result.returncode == 0, (
            f"_jlist test error:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
        assert "_jlist works correctly" in result.stdout
        print("PASS: _jlist() unit tested — handles list, JSON string, None, invalid JSON")

    def test_health_endpoint_returns_200(self):
        """GET /api/health returns 200 (backend is running)."""
        try:
            resp = requests.get(f"{BASE_URL}/api/health", timeout=10)
            assert resp.status_code == 200, f"Health check returned {resp.status_code}"
            print("PASS: Health endpoint returns 200")
        except requests.exceptions.RequestException as e:
            pytest.skip(f"Health endpoint not reachable: {e}")


# ── 5. GET /api/meetings/{id} returns processing_error ────────────────────────

class TestMeetingApiProcessingErrorField:
    """Verify GET /api/meetings/{id} response includes processing_error key."""

    def test_create_and_get_meeting_has_processing_error(self, admin_headers):
        """GET /api/meetings/{id} must include 'processing_error' key (null for new meetings)."""
        meeting_data = {
            "title": f"TEST_jlist_{uuid.uuid4().hex[:8]}",
            "date": "2026-04-01",
            "meeting_type": "supervision",
        }
        create_resp = requests.post(
            f"{BASE_URL}/api/meetings/",
            json=meeting_data,
            headers=admin_headers,
            timeout=15,
        )
        assert create_resp.status_code in (200, 201), (
            f"Create meeting failed ({create_resp.status_code}): {create_resp.text}"
        )
        meeting_id = create_resp.json().get("id")
        assert meeting_id, f"No id in create response: {create_resp.json()}"

        try:
            get_resp = requests.get(
                f"{BASE_URL}/api/meetings/{meeting_id}",
                headers=admin_headers,
                timeout=15,
            )
            assert get_resp.status_code == 200, (
                f"GET /api/meetings/{meeting_id} returned {get_resp.status_code}: {get_resp.text}"
            )
            meeting = get_resp.json()
            assert "processing_error" in meeting, (
                f"'processing_error' key missing from GET /api/meetings/{{id}} response. "
                f"Keys: {sorted(meeting.keys())}"
            )
            assert meeting["processing_error"] is None, (
                f"New meeting should have processing_error=None, got: {meeting['processing_error']!r}"
            )
            print(f"PASS: GET /api/meetings/{{id}} includes processing_error=null for a fresh meeting")
        finally:
            requests.delete(
                f"{BASE_URL}/api/meetings/{meeting_id}",
                headers=admin_headers,
                timeout=10,
            )
            print(f"Cleanup: deleted test meeting {meeting_id}")

    def test_meeting_list_returns_200(self, admin_headers):
        """GET /api/meetings/ returns 200."""
        resp = requests.get(f"{BASE_URL}/api/meetings/", headers=admin_headers, timeout=15)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        print("PASS: GET /api/meetings/ returns 200")


# ── 6. POST /api/processing/{id}/retry ────────────────────────────────────────

class TestProcessingRetryEndpoint:
    """Verify POST /api/processing/{id}/retry behaviour."""

    def test_retry_nonexistent_meeting_returns_404(self, admin_headers):
        """POST /api/processing/{fake_id}/retry returns 404 for non-existent meeting."""
        fake_id = str(uuid.uuid4())
        resp = requests.post(
            f"{BASE_URL}/api/processing/{fake_id}/retry",
            headers=admin_headers,
            timeout=15,
        )
        assert resp.status_code == 404, (
            f"Expected 404 for non-existent meeting retry, got {resp.status_code}: {resp.text}"
        )
        print(f"PASS: retry on non-existent meeting returns 404")

    def test_retry_fresh_meeting_no_audio_returns_400(self, admin_headers):
        """POST /api/processing/{id}/retry returns 400 when meeting has no audio_file_id."""
        # Create a fresh meeting (status=pending, no audio)
        create_resp = requests.post(
            f"{BASE_URL}/api/meetings/",
            json={
                "title": f"TEST_jlist_retry_{uuid.uuid4().hex[:6]}",
                "date": "2026-04-01",
                "meeting_type": "supervision",
            },
            headers=admin_headers,
            timeout=15,
        )
        assert create_resp.status_code in (200, 201), (
            f"Create meeting failed: {create_resp.text}"
        )
        meeting_id = create_resp.json().get("id")
        assert meeting_id

        try:
            retry_resp = requests.post(
                f"{BASE_URL}/api/processing/{meeting_id}/retry",
                headers=admin_headers,
                timeout=15,
            )
            # A fresh meeting has status != processing_failed/processing/in_review/reviewed
            # so it should return 400 (bad status) OR 400 (no audio)
            assert retry_resp.status_code == 400, (
                f"Expected 400 for retry on pending meeting (status not eligible), "
                f"got {retry_resp.status_code}: {retry_resp.text}"
            )
            print(f"PASS: retry on fresh meeting (no audio) returns 400: {retry_resp.json().get('detail', '')}")
        finally:
            requests.delete(
                f"{BASE_URL}/api/meetings/{meeting_id}",
                headers=admin_headers,
                timeout=10,
            )
            print(f"Cleanup: deleted test meeting {meeting_id}")

    def test_retry_on_existing_processing_failed_meeting_returns_200(self, admin_headers):
        """If any processing_failed meetings with audio exist, retry should return 200."""
        # Get all meetings
        resp = requests.get(f"{BASE_URL}/api/meetings/", headers=admin_headers, timeout=15)
        assert resp.status_code == 200

        data = resp.json()
        meetings = data if isinstance(data, list) else data.get("meetings", [])

        # Find a processing_failed meeting with audio_file_id
        candidate = None
        for m in meetings:
            if m.get("status") == "processing_failed" and m.get("audio_file_id"):
                candidate = m
                break

        if not candidate:
            pytest.skip(
                "No processing_failed meetings with audio_file_id found in DB — "
                "skipping retry-200 test (requires a real failed meeting)"
            )

        meeting_id = candidate["id"]
        print(f"Found processing_failed meeting with audio: {meeting_id}")

        retry_resp = requests.post(
            f"{BASE_URL}/api/processing/{meeting_id}/retry",
            headers=admin_headers,
            timeout=15,
        )
        assert retry_resp.status_code == 200, (
            f"Expected 200 for retry on processing_failed meeting, "
            f"got {retry_resp.status_code}: {retry_resp.text}"
        )
        resp_data = retry_resp.json()
        assert "message" in resp_data or "status" in resp_data, (
            f"Expected message/status in retry response: {resp_data}"
        )
        print(f"PASS: retry on processing_failed meeting returns 200: {resp_data}")
