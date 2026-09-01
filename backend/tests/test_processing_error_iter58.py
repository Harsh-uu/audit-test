"""
Tests for iteration 58:
Verify that:
1. INSERT INTO analyses uses exactly 9 guaranteed-core columns (custom_mappings removed).
2. A separate try/except UPDATE for custom_mappings exists after the core INSERT.
3. Exception handler stores error message in meetings.processing_error.
4. init_db.py has ALTER TABLE guards for processing_error (meetings) and custom_mappings/pii_redactions (analyses).
5. MeetingReport.js shows meeting.processing_error in a red box when status is processing_failed.
6. GET /api/meetings/{id} returns processing_error field.
7. Backend starts cleanly.
"""

import pytest
import requests
import os
import re
import uuid

# ── Base URL ──────────────────────────────────────────────────────────────────

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
if not BASE_URL:
    BASE_URL = "https://supervision-preview.preview.emergentagent.com"

ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PASS = "Admin123!"

PROCESSING_PY = os.path.join(os.path.dirname(__file__), "..", "routers", "processing.py")
BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")
MEETING_REPORT_JS = os.path.join(
    os.path.dirname(__file__), "..", "..", "frontend", "src", "pages", "MeetingReport.js"
)


def _load_schema_source():
    """Concatenate init_db.py + every migrations/*.py chunk (schema SQL now lives there)."""
    content = open(os.path.join(BACKEND_DIR, "init_db.py"), "r").read()
    migrations_dir = os.path.join(BACKEND_DIR, "migrations")
    for fname in sorted(os.listdir(migrations_dir)):
        if fname.endswith(".py"):
            content += open(os.path.join(migrations_dir, fname), "r").read()
    return content


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def admin_token():
    """Authenticate as admin and return bearer token."""
    resp = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
        timeout=10,
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    data = resp.json()
    token = data.get("access_token") or data.get("token")
    assert token, f"No token in response: {data}"
    return token


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# ── Static Code Verification: processing.py INSERT ────────────────────────────

class TestInsert9Columns:
    """Verify INSERT INTO analyses uses exactly 9 core columns (no custom_mappings in INSERT)."""

    def _load_file(self, path):
        with open(path, "r") as f:
            return f.read()

    def test_insert_has_exactly_9_columns(self):
        """INSERT INTO analyses must have exactly 9 columns (custom_mappings removed from INSERT)."""
        content = self._load_file(PROCESSING_PY)

        col_match = re.search(
            r'INSERT INTO analyses\s*\(([^)]+)\)',
            content,
            re.DOTALL | re.IGNORECASE,
        )
        assert col_match, "Could not find INSERT INTO analyses column list in processing.py"

        col_text = col_match.group(1)
        columns = [c.strip() for c in col_text.split(",") if c.strip()]
        print(f"Columns found in INSERT: {columns}")

        assert len(columns) == 9, (
            f"Expected 9 columns in INSERT INTO analyses, found {len(columns)}: {columns}"
        )
        print(f"PASS: INSERT INTO analyses has exactly 9 columns: {columns}")

    def test_insert_has_exactly_9_parameters(self):
        """INSERT INTO analyses VALUES clause must have exactly 9 parameters ($1–$9)."""
        content = self._load_file(PROCESSING_PY)

        values_match = re.search(
            r'INSERT INTO analyses\s*\([^)]+\)\s*VALUES\s*\(([^)]+)\)',
            content,
            re.DOTALL | re.IGNORECASE,
        )
        assert values_match, "Could not find INSERT INTO analyses VALUES clause in processing.py"

        values_text = values_match.group(1)
        params = re.findall(r'\$\d+', values_text)
        print(f"Parameters found in VALUES: {params}")

        assert len(params) == 9, (
            f"Expected 9 parameters in VALUES clause, found {len(params)}: {params}"
        )
        print(f"PASS: INSERT INTO analyses VALUES has exactly 9 parameters: {params}")

    def test_insert_parameters_are_1_through_9(self):
        """INSERT INTO analyses VALUES must use $1 through $9."""
        content = self._load_file(PROCESSING_PY)

        values_match = re.search(
            r'INSERT INTO analyses\s*\([^)]+\)\s*VALUES\s*\(([^)]+)\)',
            content,
            re.DOTALL | re.IGNORECASE,
        )
        assert values_match, "Could not find INSERT INTO analyses VALUES clause in processing.py"

        values_text = values_match.group(1)
        params = re.findall(r'\$(\d+)', values_text)
        param_nums = sorted([int(p) for p in params])

        assert param_nums == list(range(1, 10)), (
            f"Expected params $1–$9, found: {['$' + str(p) for p in param_nums]}"
        )
        print(f"PASS: Parameters are exactly $1–$9: {['$' + str(p) for p in param_nums]}")

    def test_insert_has_9_expected_columns(self):
        """INSERT INTO analyses must have exactly the 9 expected core columns."""
        content = self._load_file(PROCESSING_PY)

        col_match = re.search(
            r'INSERT INTO analyses\s*\(([^)]+)\)',
            content,
            re.DOTALL | re.IGNORECASE,
        )
        assert col_match, "Could not find INSERT INTO analyses column list in processing.py"

        col_text = col_match.group(1)
        columns = {c.strip() for c in col_text.split(",") if c.strip()}

        expected_9_columns = {
            "id", "meeting_id", "org_id", "summary", "actions",
            "risks", "cqc_mappings", "care_cert_mappings", "created_at"
        }

        assert columns == expected_9_columns, (
            f"Column mismatch.\n  Expected: {sorted(expected_9_columns)}\n  Found: {sorted(columns)}"
        )
        print(f"PASS: INSERT columns exactly match 9-column set: {sorted(columns)}")

    def test_insert_does_not_contain_custom_mappings(self):
        """INSERT INTO analyses must NOT include custom_mappings (moved to separate UPDATE)."""
        content = self._load_file(PROCESSING_PY)

        col_match = re.search(
            r'INSERT INTO analyses\s*\(([^)]+)\)',
            content,
            re.DOTALL | re.IGNORECASE,
        )
        assert col_match, "Could not find INSERT INTO analyses column list in processing.py"

        col_text = col_match.group(1)
        assert "custom_mappings" not in col_text, (
            f"INSERT INTO analyses must NOT contain 'custom_mappings', found it in: {col_text}"
        )
        print("PASS: custom_mappings is NOT in the INSERT column list")

    def test_insert_does_not_contain_edited_summary(self):
        """INSERT INTO analyses must NOT include edited_summary."""
        content = self._load_file(PROCESSING_PY)

        col_match = re.search(
            r'INSERT INTO analyses\s*\(([^)]+)\)',
            content,
            re.DOTALL | re.IGNORECASE,
        )
        assert col_match, "Could not find INSERT INTO analyses column list in processing.py"

        col_text = col_match.group(1)
        assert "edited_summary" not in col_text, (
            f"INSERT must NOT contain 'edited_summary', found it in: {col_text}"
        )
        print("PASS: edited_summary is NOT in the INSERT column list")

    def test_insert_does_not_contain_last_edited_at(self):
        """INSERT INTO analyses must NOT include last_edited_at."""
        content = self._load_file(PROCESSING_PY)

        col_match = re.search(
            r'INSERT INTO analyses\s*\(([^)]+)\)',
            content,
            re.DOTALL | re.IGNORECASE,
        )
        assert col_match, "Could not find INSERT INTO analyses column list in processing.py"

        col_text = col_match.group(1)
        assert "last_edited_at" not in col_text, (
            f"INSERT must NOT contain 'last_edited_at', found it in: {col_text}"
        )
        print("PASS: last_edited_at is NOT in the INSERT column list")


# ── Static Code Verification: separate custom_mappings UPDATE ─────────────────

class TestCustomMappingsSeparateUpdate:
    """Verify a separate try/except UPDATE for custom_mappings exists after the INSERT."""

    def _load_file(self, path):
        with open(path, "r") as f:
            return f.read()

    def test_separate_custom_mappings_update_exists(self):
        """There must be a separate UPDATE analyses SET custom_mappings statement after the INSERT."""
        content = self._load_file(PROCESSING_PY)

        update_match = re.search(
            r'UPDATE analyses SET custom_mappings\s*=',
            content,
            re.IGNORECASE,
        )
        assert update_match, (
            "Could not find 'UPDATE analyses SET custom_mappings=' in processing.py. "
            "Expected a separate UPDATE after the core INSERT."
        )
        print("PASS: Separate 'UPDATE analyses SET custom_mappings' exists in processing.py")

    def test_custom_mappings_update_is_in_try_except(self):
        """The custom_mappings UPDATE must be wrapped in a try/except block."""
        content = self._load_file(PROCESSING_PY)

        # Find the UPDATE analyses SET custom_mappings block and check it's inside a try block
        # Look for pattern: try: ... UPDATE analyses SET custom_mappings ... except Exception
        try_custom_match = re.search(
            r'try\s*:.*?UPDATE analyses SET custom_mappings.*?except\s+Exception',
            content,
            re.DOTALL | re.IGNORECASE,
        )
        assert try_custom_match, (
            "The custom_mappings UPDATE must be wrapped in a try/except Exception block, "
            "but no such pattern was found in processing.py."
        )
        print("PASS: custom_mappings UPDATE is wrapped in try/except Exception block")

    def test_custom_mappings_update_has_warning_log(self):
        """The except block for custom_mappings UPDATE must log a warning (not silently ignore)."""
        content = self._load_file(PROCESSING_PY)

        # Look for the warning message about custom_mappings
        warning_match = re.search(
            r'custom_mappings.*(update\s+skipped|may not exist)',
            content,
            re.IGNORECASE,
        )
        assert warning_match, (
            "Expected a warning log like 'custom_mappings update skipped (column may not exist yet)' "
            "in the except block, but found nothing matching."
        )
        print("PASS: custom_mappings except block logs a warning")


# ── Static Code Verification: processing_error stored on failure ───────────────

class TestProcessingErrorStoredOnFailure:
    """Verify the exception handler stores the error in meetings.processing_error."""

    def _load_file(self, path):
        with open(path, "r") as f:
            return f.read()

    def test_exception_handler_updates_processing_error(self):
        """The outer except block must store the error in meetings.processing_error."""
        content = self._load_file(PROCESSING_PY)

        # Check that at least one line has BOTH UPDATE meetings SET and processing_error
        lines = content.splitlines()
        update_with_processing_error = [
            line for line in lines
            if "UPDATE meetings SET" in line and "processing_error" in line
        ]
        has_processing_failed_status = any(
            "processing_failed" in line for line in lines
        )
        assert update_with_processing_error, (
            "Could not find a line with both 'UPDATE meetings SET' and 'processing_error' in processing.py. "
            "Expected the exception handler to update meetings.processing_error on failure."
        )
        assert has_processing_failed_status, (
            "Could not find 'processing_failed' status in processing.py exception handler."
        )
        print(f"PASS: Found line: {update_with_processing_error[0].strip()}")
        print("PASS: Exception handler stores error in meetings.processing_error with status='processing_failed'")

    def test_exception_handler_sets_processing_failed_status(self):
        """The except block must set status='processing_failed' in meetings table."""
        content = self._load_file(PROCESSING_PY)

        assert "processing_failed" in content, (
            "Expected 'processing_failed' status to be set in the exception handler."
        )
        print("PASS: 'processing_failed' status is used in exception handler")

    def test_exception_handler_truncates_error_message(self):
        """Error message should be truncated to avoid DB overflow (str(e)[:N])."""
        content = self._load_file(PROCESSING_PY)

        truncate_match = re.search(r'str\(e\)\[:\d+\]', content)
        assert truncate_match, (
            "Expected error message truncation like str(e)[:500] in exception handler."
        )
        print(f"PASS: Error message is truncated: {truncate_match.group(0)}")


# ── Static Code Verification: init_db.py ALTER TABLE guards ──────────────────

class TestInitDbAlterTableGuards:
    """Verify init_db.py has the required ALTER TABLE IF NOT EXISTS guards."""

    def _load_file(self, path):
        with open(path, "r") as f:
            return f.read()

    def test_alter_meetings_processing_error_exists(self):
        """init_db.py must have: ALTER TABLE meetings ADD COLUMN IF NOT EXISTS processing_error TEXT"""
        content = _load_schema_source()

        match = re.search(
            r'ALTER TABLE meetings ADD COLUMN IF NOT EXISTS processing_error\s+TEXT',
            content,
            re.IGNORECASE,
        )
        assert match, (
            "Expected 'ALTER TABLE meetings ADD COLUMN IF NOT EXISTS processing_error TEXT' in init_db.py, "
            "but it was not found."
        )
        print("PASS: init_db.py has ALTER TABLE meetings ADD COLUMN IF NOT EXISTS processing_error TEXT")

    def test_alter_analyses_custom_mappings_exists(self):
        """init_db.py must have: ALTER TABLE analyses ADD COLUMN IF NOT EXISTS custom_mappings"""
        content = _load_schema_source()

        match = re.search(
            r'ALTER TABLE analyses ADD COLUMN IF NOT EXISTS custom_mappings',
            content,
            re.IGNORECASE,
        )
        assert match, (
            "Expected 'ALTER TABLE analyses ADD COLUMN IF NOT EXISTS custom_mappings' in init_db.py, "
            "but it was not found."
        )
        print("PASS: init_db.py has ALTER TABLE analyses ADD COLUMN IF NOT EXISTS custom_mappings")

    def test_alter_analyses_pii_redactions_exists(self):
        """init_db.py must have: ALTER TABLE analyses ADD COLUMN IF NOT EXISTS pii_redactions"""
        content = _load_schema_source()

        match = re.search(
            r'ALTER TABLE analyses ADD COLUMN IF NOT EXISTS pii_redactions',
            content,
            re.IGNORECASE,
        )
        assert match, (
            "Expected 'ALTER TABLE analyses ADD COLUMN IF NOT EXISTS pii_redactions' in init_db.py, "
            "but it was not found."
        )
        print("PASS: init_db.py has ALTER TABLE analyses ADD COLUMN IF NOT EXISTS pii_redactions")


# ── Static Code Verification: MeetingReport.js processing_error UI ────────────

class TestMeetingReportProcessingError:
    """Verify MeetingReport.js shows processing_error in a red box when processing_failed."""

    def _load_file(self, path):
        with open(path, "r") as f:
            return f.read()

    def test_meetingreport_shows_processing_error(self):
        """MeetingReport.js must render meeting.processing_error when it's present."""
        content = self._load_file(MEETING_REPORT_JS)

        assert "meeting.processing_error" in content or "processing_error" in content, (
            "Expected 'meeting.processing_error' or 'processing_error' in MeetingReport.js"
        )
        print("PASS: MeetingReport.js references processing_error field")

    def test_meetingreport_processing_error_in_red_style(self):
        """MeetingReport.js must render processing_error with red styling."""
        content = self._load_file(MEETING_REPORT_JS)

        # Check for red color classes (text-red or bg-red)
        red_with_error_match = re.search(
            r'(text-red|bg-red|border-red).*processing_error|processing_error.*?(text-red|bg-red|border-red)',
            content,
            re.DOTALL,
        )
        assert red_with_error_match, (
            "Expected processing_error to be shown with red styling (text-red/bg-red/border-red) "
            "in MeetingReport.js"
        )
        print("PASS: MeetingReport.js shows processing_error with red styling")

    def test_meetingreport_processing_error_conditional(self):
        """MeetingReport.js must conditionally show processing_error (only when present)."""
        content = self._load_file(MEETING_REPORT_JS)

        # Should have an &&  or conditional check before rendering
        cond_match = re.search(
            r'meeting\?\.processing_error|meeting\.processing_error\s*&&',
            content,
        )
        assert cond_match, (
            "Expected conditional rendering like 'meeting?.processing_error &&' or "
            "'meeting.processing_error &&' in MeetingReport.js"
        )
        print("PASS: MeetingReport.js conditionally renders processing_error")


# ── Backend Import Verification ───────────────────────────────────────────────

class TestBackendStartsCleanly:
    """Verify backend server imports without errors."""

    def test_server_imports_cleanly(self):
        """server.py must import without syntax or module errors."""
        import subprocess
        result = subprocess.run(
            ["python", "-c", "import server; print('server OK')"],
            capture_output=True, text=True,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        assert result.returncode == 0, (
            f"Backend server import error:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
        assert "server OK" in result.stdout
        print("PASS: server.py imports cleanly")

    def test_processing_router_imports_cleanly(self):
        """routers/processing.py must import without errors."""
        import subprocess
        result = subprocess.run(
            ["python", "-c", "from routers.processing import router; print('processing router OK')"],
            capture_output=True, text=True,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        assert result.returncode == 0, (
            f"processing.py import error:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
        assert "processing router OK" in result.stdout
        print("PASS: routers/processing.py imports cleanly")


# ── API Tests: processing_error field in GET /api/meetings/{id} ───────────────

class TestMeetingApiProcessingError:
    """Verify GET /api/meetings/{id} includes processing_error in response."""

    def test_meeting_list_returns_200(self, admin_headers):
        """GET /api/meetings/ returns 200."""
        resp = requests.get(f"{BASE_URL}/api/meetings/", headers=admin_headers, timeout=10)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        print(f"PASS: GET /api/meetings/ returns 200")

    def test_get_meeting_includes_processing_error_field(self, admin_headers):
        """GET /api/meetings/{id} response dict must include processing_error key."""
        # Create a test meeting
        meeting_data = {
            "title": f"TEST_ProcessingError_{uuid.uuid4().hex[:6]}",
            "date": "2026-04-01",
            "meeting_type": "supervision",
        }
        create_resp = requests.post(
            f"{BASE_URL}/api/meetings/",
            json=meeting_data,
            headers=admin_headers,
            timeout=10,
        )
        assert create_resp.status_code in (200, 201), f"Create meeting failed: {create_resp.text}"
        meeting_id = create_resp.json().get("id")
        assert meeting_id

        try:
            # GET the meeting
            get_resp = requests.get(
                f"{BASE_URL}/api/meetings/{meeting_id}",
                headers=admin_headers,
                timeout=10,
            )
            assert get_resp.status_code == 200, f"GET meeting failed: {get_resp.text}"

            meeting = get_resp.json()
            # processing_error should be present (either None or a string)
            assert "processing_error" in meeting, (
                f"GET /api/meetings/{{id}} response does not include 'processing_error' key. "
                f"Keys found: {list(meeting.keys())}"
            )
            # For a new meeting it should be None
            assert meeting["processing_error"] is None, (
                f"Expected processing_error=None for a fresh meeting, got: {meeting['processing_error']}"
            )
            print(f"PASS: GET /api/meetings/{{id}} includes processing_error=None for a new meeting")
        finally:
            requests.delete(f"{BASE_URL}/api/meetings/{meeting_id}", headers=admin_headers, timeout=10)
            print(f"Cleanup: deleted test meeting {meeting_id}")

    def test_processing_failed_meeting_shows_error_or_none(self, admin_headers):
        """Any processing_failed meetings in the DB should have processing_error populated or NULL."""
        resp = requests.get(f"{BASE_URL}/api/meetings/", headers=admin_headers, timeout=10)
        assert resp.status_code == 200

        data = resp.json()
        # Handle both list response and {"meetings": [...]} shapes
        if isinstance(data, list):
            meetings = data
        else:
            meetings = data.get("meetings", [])

        failed_meetings = [m for m in meetings if m.get("status") == "processing_failed"]
        print(f"Found {len(failed_meetings)} processing_failed meetings")

        for m in failed_meetings:
            assert "processing_error" in m, (
                f"Meeting {m.get('id')} has status='processing_failed' but no 'processing_error' key in response"
            )
            print(f"  Meeting {m.get('id')}: processing_error = {m.get('processing_error')!r}")

        if not failed_meetings:
            print("INFO: No processing_failed meetings found in the DB — field presence test skipped")
        else:
            print(f"PASS: All {len(failed_meetings)} processing_failed meetings include 'processing_error' key")

    def test_retry_nonexistent_meeting_returns_404(self, admin_headers):
        """POST /api/processing/{fake_id}/retry returns 404 for non-existent meeting."""
        fake_id = str(uuid.uuid4())
        resp = requests.post(
            f"{BASE_URL}/api/processing/{fake_id}/retry",
            headers=admin_headers,
            timeout=10,
        )
        assert resp.status_code == 404, (
            f"Expected 404 for non-existent meeting retry, got {resp.status_code}: {resp.text}"
        )
        print(f"PASS: Non-existent meeting retry returns 404")
