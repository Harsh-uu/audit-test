"""
Tests for iteration 57:
Verify that INSERT INTO analyses in processing.py does NOT include
edited_summary or last_edited_at columns (which may not exist in older schemas).
The INSERT must have exactly 10 columns: id, meeting_id, org_id, summary,
actions, risks, cqc_mappings, care_cert_mappings, custom_mappings, created_at
and exactly 10 parameters ($1–$10).
"""

import pytest
import requests
import os
import re
import uuid

# ── Base URL ──────────────────────────────────────────────────────────────────

def _get_base_url():
    """Try public URL first; fall back to localhost if 502/unreachable."""
    public = (os.environ.get("REACT_APP_BACKEND_URL") or "https://evidence-link-4.preview.emergentagent.com").rstrip("/")
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

PROCESSING_PY = os.path.join(os.path.dirname(__file__), "..", "routers", "processing.py")


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


# ── Static Code Verification ──────────────────────────────────────────────────

class TestInsertAnalysesStatement:
    """Verify the INSERT INTO analyses statement in processing.py is correct."""

    def _load_processing_py(self):
        with open(PROCESSING_PY, "r") as f:
            return f.read()

    def test_insert_does_not_contain_edited_summary(self):
        """INSERT INTO analyses must NOT include edited_summary column."""
        content = self._load_processing_py()

        # Find the INSERT INTO analyses block
        insert_match = re.search(
            r'INSERT INTO analyses\s*\(.*?\)\s*VALUES\s*\(.*?\)',
            content,
            re.DOTALL | re.IGNORECASE,
        )
        assert insert_match, "Could not find INSERT INTO analyses block in processing.py"

        insert_text = insert_match.group(0)
        assert "edited_summary" not in insert_text, (
            f"INSERT INTO analyses must NOT contain 'edited_summary', found:\n{insert_text}"
        )
        print("PASS: edited_summary is NOT in INSERT INTO analyses")

    def test_insert_does_not_contain_last_edited_at(self):
        """INSERT INTO analyses must NOT include last_edited_at column."""
        content = self._load_processing_py()

        insert_match = re.search(
            r'INSERT INTO analyses\s*\(.*?\)\s*VALUES\s*\(.*?\)',
            content,
            re.DOTALL | re.IGNORECASE,
        )
        assert insert_match, "Could not find INSERT INTO analyses block in processing.py"

        insert_text = insert_match.group(0)
        assert "last_edited_at" not in insert_text, (
            f"INSERT INTO analyses must NOT contain 'last_edited_at', found:\n{insert_text}"
        )
        print("PASS: last_edited_at is NOT in INSERT INTO analyses")

    def test_insert_has_exactly_10_columns(self):
        """INSERT INTO analyses must have exactly 10 columns."""
        content = self._load_processing_py()

        # Extract just the column list (between first pair of parens after INSERT INTO analyses)
        col_match = re.search(
            r'INSERT INTO analyses\s*\(([^)]+)\)',
            content,
            re.DOTALL | re.IGNORECASE,
        )
        assert col_match, "Could not find INSERT INTO analyses column list in processing.py"

        col_text = col_match.group(1)
        columns = [c.strip() for c in col_text.split(",") if c.strip()]
        print(f"Columns found: {columns}")

        assert len(columns) == 10, (
            f"Expected 10 columns in INSERT INTO analyses, found {len(columns)}: {columns}"
        )
        print(f"PASS: INSERT INTO analyses has exactly 10 columns: {columns}")

    def test_insert_has_expected_columns(self):
        """INSERT INTO analyses must have exactly the expected 10 columns."""
        content = self._load_processing_py()

        col_match = re.search(
            r'INSERT INTO analyses\s*\(([^)]+)\)',
            content,
            re.DOTALL | re.IGNORECASE,
        )
        assert col_match, "Could not find INSERT INTO analyses column list in processing.py"

        col_text = col_match.group(1)
        columns = [c.strip() for c in col_text.split(",") if c.strip()]

        expected_columns = {
            "id", "meeting_id", "org_id", "summary", "actions",
            "risks", "cqc_mappings", "care_cert_mappings", "custom_mappings", "created_at"
        }
        found_set = set(columns)

        assert found_set == expected_columns, (
            f"Column mismatch.\n  Expected: {sorted(expected_columns)}\n  Found: {sorted(found_set)}"
        )
        print(f"PASS: INSERT INTO analyses has exactly the expected columns: {sorted(found_set)}")

    def test_insert_has_exactly_10_parameters(self):
        """INSERT INTO analyses VALUES clause must have exactly 10 parameters ($1–$10)."""
        content = self._load_processing_py()

        # Find the VALUES(...) clause of INSERT INTO analyses
        values_match = re.search(
            r'INSERT INTO analyses\s*\([^)]+\)\s*VALUES\s*\(([^)]+)\)',
            content,
            re.DOTALL | re.IGNORECASE,
        )
        assert values_match, "Could not find INSERT INTO analyses VALUES clause in processing.py"

        values_text = values_match.group(1)
        # Find all $N parameters
        params = re.findall(r'\$\d+', values_text)
        print(f"Parameters found: {params}")

        assert len(params) == 10, (
            f"Expected 10 parameters in VALUES clause, found {len(params)}: {params}"
        )
        print(f"PASS: INSERT INTO analyses VALUES has exactly 10 parameters: {params}")

    def test_insert_parameters_are_1_through_10(self):
        """INSERT INTO analyses VALUES must use $1 through $10 (no gaps, no extras)."""
        content = self._load_processing_py()

        values_match = re.search(
            r'INSERT INTO analyses\s*\([^)]+\)\s*VALUES\s*\(([^)]+)\)',
            content,
            re.DOTALL | re.IGNORECASE,
        )
        assert values_match, "Could not find INSERT INTO analyses VALUES clause in processing.py"

        values_text = values_match.group(1)
        params = re.findall(r'\$(\d+)', values_text)
        param_nums = sorted([int(p) for p in params])

        assert param_nums == list(range(1, 11)), (
            f"Expected params $1–$10 in order, found: {['$' + str(p) for p in param_nums]}"
        )
        print(f"PASS: Parameters are exactly $1–$10: {['$' + str(p) for p in param_nums]}")

    def test_backend_syntax_valid(self):
        """Backend (server.py) must import cleanly — no syntax or import errors."""
        import subprocess
        result = subprocess.run(
            ["python", "-c", "import server; print('imports OK')"],
            capture_output=True, text=True,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        assert result.returncode == 0, (
            f"Backend import error:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
        assert "imports OK" in result.stdout
        print("PASS: Backend imports without errors")

    def test_processing_router_imports_valid(self):
        """routers/processing.py must import without syntax errors."""
        import subprocess
        result = subprocess.run(
            ["python", "-c", "from routers.processing import router; print('processing OK')"],
            capture_output=True, text=True,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        assert result.returncode == 0, (
            f"processing.py import error:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
        assert "processing OK" in result.stdout
        print("PASS: routers/processing.py imports cleanly")


# ── API Tests ──────────────────────────────────────────────────────────────────

class TestRetryEndpointAfterFix:
    """Verify the retry endpoint is reachable and returns expected status codes."""

    def test_backend_is_running(self, admin_headers):
        """GET /api/meetings/ returns 200."""
        resp = requests.get(f"{BASE_URL}/api/meetings/", headers=admin_headers)
        assert resp.status_code == 200, f"Backend not running: {resp.status_code} {resp.text}"
        print(f"PASS: Backend running — GET /api/meetings/ returned 200")

    def test_retry_nonexistent_meeting_returns_404(self, admin_headers):
        """POST /api/processing/{fake_id}/retry returns 404 for non-existent meeting."""
        fake_id = str(uuid.uuid4())
        resp = requests.post(
            f"{BASE_URL}/api/processing/{fake_id}/retry",
            headers=admin_headers,
        )
        assert resp.status_code == 404, (
            f"Expected 404 for non-existent meeting, got {resp.status_code}: {resp.text}"
        )
        print(f"PASS: Non-existent meeting retry returns 404")

    def test_retry_unauthenticated_returns_401_or_403(self):
        """POST /api/processing/{fake_id}/retry without auth returns 401/403."""
        fake_id = str(uuid.uuid4())
        resp = requests.post(
            f"{BASE_URL}/api/processing/{fake_id}/retry",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code in (401, 403), (
            f"Expected 401/403 for unauthenticated retry, got {resp.status_code}: {resp.text}"
        )
        print(f"PASS: Unauthenticated retry returns {resp.status_code}")

    def test_retry_wrong_status_meeting_returns_400(self, admin_headers):
        """Retry a newly-created (non-failed) meeting returns 400."""
        meeting_data = {
            "title": f"TEST_InsertFix_Retry_{uuid.uuid4().hex[:6]}",
            "date": "2026-04-01",
            "meeting_type": "supervision",
        }
        create_resp = requests.post(
            f"{BASE_URL}/api/meetings/",
            json=meeting_data,
            headers=admin_headers,
        )
        assert create_resp.status_code in (200, 201), (
            f"Failed to create test meeting: {create_resp.text}"
        )
        meeting_id = create_resp.json().get("id")
        assert meeting_id, "No meeting ID in create response"

        try:
            retry_resp = requests.post(
                f"{BASE_URL}/api/processing/{meeting_id}/retry",
                headers=admin_headers,
            )
            assert retry_resp.status_code == 400, (
                f"Expected 400 for non-failed meeting retry, got {retry_resp.status_code}: {retry_resp.text}"
            )
            print(f"PASS: Wrong-status meeting retry returns 400: {retry_resp.json().get('detail')}")
        finally:
            requests.delete(f"{BASE_URL}/api/meetings/{meeting_id}", headers=admin_headers)
            print(f"Cleanup: deleted test meeting {meeting_id}")
