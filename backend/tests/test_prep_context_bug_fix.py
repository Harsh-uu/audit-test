"""
Test for the 'Failed to load prep data' bug fix.
Bug: supervision_uploads.full_text and standards_documents.extracted_text missing in production.
Fix: ALTER TABLE ADD COLUMN IF NOT EXISTS guards in init_db.py + try/except in prep.py.

Tests:
- GET /api/prep/{meetingId}/context must return 200 (not 500) for a new meeting
- GET /api/prep/{meetingId} must return 200 with exists:false, gen_status:idle for new meeting
- GET /api/prep/focus-topics must return 200 with an array
- init_db.py has correct ALTER TABLE IF NOT EXISTS guards
"""
import pytest
import requests
import os
import uuid

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "https://evidence-link-4.preview.emergentagent.com").rstrip("/")

ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PASS = "Admin123!"


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def admin_token():
    """Authenticate as admin and return bearer token."""
    resp = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    data = resp.json()
    token = data.get("access_token") or data.get("token")
    assert token, f"No token in response: {data}"
    return token


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def test_meeting_id(admin_headers):
    """Create a test meeting and clean it up after module tests finish."""
    # Fetch a supervisee user to use as attendee
    users_resp = requests.get(f"{BASE_URL}/api/admin/users", headers=admin_headers)
    supervisee_id = None
    supervisee_name = None
    if users_resp.status_code == 200:
        users = users_resp.json()
        # pick a non-admin attendee if available, otherwise fallback to any user
        for u in users:
            if u.get("role") in ("attendee", "staff", "user"):
                supervisee_id = u.get("id") or u.get("user_id")
                supervisee_name = u.get("name", "Test Supervisee")
                break
        if not supervisee_id and users:
            supervisee_id = users[0].get("id") or users[0].get("user_id")
            supervisee_name = users[0].get("name", "Test Supervisee")

    meeting_payload = {
        "title": f"TEST_PrepContextBugFix_{uuid.uuid4().hex[:8]}",
        "date": "2026-02-15",
        "status": "draft",
    }
    if supervisee_id:
        meeting_payload["attendees"] = [{"user_id": supervisee_id, "name": supervisee_name}]

    create_resp = requests.post(
        f"{BASE_URL}/api/meetings/",
        json=meeting_payload,
        headers=admin_headers
    )
    assert create_resp.status_code in (200, 201), f"Meeting creation failed: {create_resp.text}"
    data = create_resp.json()
    meeting_id = data.get("id") or data.get("meeting_id")
    assert meeting_id, f"No meeting id in response: {data}"
    print(f"Created test meeting: {meeting_id}")
    yield meeting_id

    # Cleanup
    try:
        requests.delete(f"{BASE_URL}/api/meetings/{meeting_id}", headers=admin_headers)
        print(f"Deleted test meeting: {meeting_id}")
    except Exception as e:
        print(f"Cleanup warning: {e}")


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestPrepContextEndpoint:
    """GET /api/prep/{meetingId}/context — core bug fix validation."""

    def test_context_returns_200_not_500(self, admin_headers, test_meeting_id):
        """The context endpoint must NOT return 500 for a freshly created meeting."""
        resp = requests.get(
            f"{BASE_URL}/api/prep/{test_meeting_id}/context",
            headers=admin_headers
        )
        assert resp.status_code == 200, (
            f"Context endpoint returned {resp.status_code} (expected 200). "
            f"This is the core bug being fixed. Response: {resp.text[:500]}"
        )

    def test_context_response_has_required_keys(self, admin_headers, test_meeting_id):
        """Response must include meeting_id, supervisees, sources, current_focus_topic."""
        resp = requests.get(
            f"{BASE_URL}/api/prep/{test_meeting_id}/context",
            headers=admin_headers
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:300]}"
        data = resp.json()

        # Required keys per the fix spec
        assert "meeting_id" in data, f"Missing 'meeting_id' key in context response: {data}"
        assert "supervisees" in data, f"Missing 'supervisees' key in context response: {data}"
        assert "sources" in data, f"Missing 'sources' key in context response: {data}"
        assert "current_focus_topic" in data, f"Missing 'current_focus_topic' key in context response: {data}"

    def test_context_meeting_id_matches(self, admin_headers, test_meeting_id):
        """The meeting_id in the response must match the requested ID."""
        resp = requests.get(
            f"{BASE_URL}/api/prep/{test_meeting_id}/context",
            headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["meeting_id"] == test_meeting_id, (
            f"meeting_id mismatch: expected {test_meeting_id}, got {data.get('meeting_id')}"
        )

    def test_context_sources_is_list(self, admin_headers, test_meeting_id):
        """sources must be a list (may be empty for a new meeting)."""
        resp = requests.get(
            f"{BASE_URL}/api/prep/{test_meeting_id}/context",
            headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["sources"], list), (
            f"Expected 'sources' to be a list, got: {type(data['sources'])}"
        )

    def test_context_supervisees_is_list(self, admin_headers, test_meeting_id):
        """supervisees must be a list."""
        resp = requests.get(
            f"{BASE_URL}/api/prep/{test_meeting_id}/context",
            headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["supervisees"], list), (
            f"Expected 'supervisees' to be a list, got: {type(data['supervisees'])}"
        )


class TestGetPrepEndpoint:
    """GET /api/prep/{meetingId} — verify new meeting returns idle state."""

    def test_get_prep_returns_200(self, admin_headers, test_meeting_id):
        """GET /api/prep/{meetingId} must return 200 for a new meeting."""
        resp = requests.get(
            f"{BASE_URL}/api/prep/{test_meeting_id}",
            headers=admin_headers
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:300]}"
        )

    def test_get_prep_new_meeting_exists_false(self, admin_headers, test_meeting_id):
        """New meeting has no prep yet — exists must be False."""
        resp = requests.get(
            f"{BASE_URL}/api/prep/{test_meeting_id}",
            headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("exists") is False, (
            f"Expected exists=False for a new meeting, got: {data.get('exists')}"
        )

    def test_get_prep_new_meeting_gen_status_idle(self, admin_headers, test_meeting_id):
        """New meeting gen_status must be 'idle'."""
        resp = requests.get(
            f"{BASE_URL}/api/prep/{test_meeting_id}",
            headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("gen_status") == "idle", (
            f"Expected gen_status='idle', got: {data.get('gen_status')}"
        )


class TestFocusTopicsEndpoint:
    """GET /api/prep/focus-topics — returns valid JSON array."""

    def test_focus_topics_returns_200(self, admin_headers):
        """Focus topics endpoint must return 200."""
        resp = requests.get(
            f"{BASE_URL}/api/prep/focus-topics",
            headers=admin_headers
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:300]}"
        )

    def test_focus_topics_returns_list(self, admin_headers):
        """Focus topics response must be a JSON array."""
        resp = requests.get(
            f"{BASE_URL}/api/prep/focus-topics",
            headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list), (
            f"Expected list response, got: {type(data)}"
        )

    def test_focus_topics_items_have_expected_fields(self, admin_headers):
        """If topics exist, each item should have at minimum id and topic/text fields."""
        resp = requests.get(
            f"{BASE_URL}/api/prep/focus-topics",
            headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        for item in data:
            assert "id" in item, f"Focus topic missing 'id': {item}"
            # The API maps 'text' column -> 'topic' field
            assert "topic" in item or "text" in item, (
                f"Focus topic missing 'topic'/'text' field: {item}"
            )


class TestInitDbGuards:
    """Verify init_db.py contains the ALTER TABLE IF NOT EXISTS guards."""

    def test_init_db_has_supervision_uploads_full_text_guard(self):
        """init_db.py must have ALTER TABLE guard for supervision_uploads.full_text"""
        with open("/app/backend/init_db.py", "r") as f:
            content = f.read()
        assert "supervision_uploads ADD COLUMN IF NOT EXISTS full_text" in content, (
            "Missing ALTER TABLE guard for supervision_uploads.full_text in init_db.py"
        )

    def test_init_db_has_supervision_uploads_doc_type_guard(self):
        """init_db.py must have ALTER TABLE guard for supervision_uploads.doc_type"""
        with open("/app/backend/init_db.py", "r") as f:
            content = f.read()
        assert "supervision_uploads ADD COLUMN IF NOT EXISTS doc_type" in content, (
            "Missing ALTER TABLE guard for supervision_uploads.doc_type in init_db.py"
        )

    def test_init_db_has_supervision_uploads_meeting_date_guard(self):
        """init_db.py must have ALTER TABLE guard for supervision_uploads.meeting_date"""
        with open("/app/backend/init_db.py", "r") as f:
            content = f.read()
        assert "supervision_uploads ADD COLUMN IF NOT EXISTS meeting_date" in content, (
            "Missing ALTER TABLE guard for supervision_uploads.meeting_date in init_db.py"
        )

    def test_init_db_has_supervision_uploads_label_guard(self):
        """init_db.py must have ALTER TABLE guard for supervision_uploads.label"""
        with open("/app/backend/init_db.py", "r") as f:
            content = f.read()
        assert "supervision_uploads ADD COLUMN IF NOT EXISTS label" in content, (
            "Missing ALTER TABLE guard for supervision_uploads.label in init_db.py"
        )

    def test_init_db_has_standards_documents_extracted_text_guard(self):
        """init_db.py must have ALTER TABLE guard for standards_documents.extracted_text"""
        with open("/app/backend/init_db.py", "r") as f:
            content = f.read()
        assert "standards_documents ADD COLUMN IF NOT EXISTS extracted_text" in content, (
            "Missing ALTER TABLE guard for standards_documents.extracted_text in init_db.py"
        )

    def test_init_db_has_standards_documents_parse_status_guard(self):
        """init_db.py must have ALTER TABLE guard for standards_documents.parse_status"""
        with open("/app/backend/init_db.py", "r") as f:
            content = f.read()
        assert "standards_documents ADD COLUMN IF NOT EXISTS parse_status" in content, (
            "Missing ALTER TABLE guard for standards_documents.parse_status in init_db.py"
        )

    def test_init_db_has_standards_documents_is_active_guard(self):
        """init_db.py must have ALTER TABLE guard for standards_documents.is_active"""
        with open("/app/backend/init_db.py", "r") as f:
            content = f.read()
        assert "standards_documents ADD COLUMN IF NOT EXISTS is_active" in content, (
            "Missing ALTER TABLE guard for standards_documents.is_active in init_db.py"
        )

    def test_init_db_has_focus_topics_active_month_guard(self):
        """init_db.py must have ALTER TABLE guard for focus_topics.active_month"""
        with open("/app/backend/init_db.py", "r") as f:
            content = f.read()
        assert "focus_topics ADD COLUMN IF NOT EXISTS active_month" in content, (
            "Missing ALTER TABLE guard for focus_topics.active_month in init_db.py"
        )

    def test_init_db_has_focus_topics_created_by_guard(self):
        """init_db.py must have ALTER TABLE guard for focus_topics.created_by"""
        with open("/app/backend/init_db.py", "r") as f:
            content = f.read()
        assert "focus_topics ADD COLUMN IF NOT EXISTS created_by" in content, (
            "Missing ALTER TABLE guard for focus_topics.created_by in init_db.py"
        )


class TestPrepTryExceptGuards:
    """Verify prep.py has try/except guards around all 4 dangerous queries."""

    def test_prep_has_try_except_for_supervision_uploads(self):
        """prep.py must have try/except around supervision_uploads query."""
        with open("/app/backend/routers/prep.py", "r") as f:
            content = f.read()
        assert "supervision_uploads" in content, "supervision_uploads query missing from prep.py"
        assert "could not load supervision_uploads" in content, (
            "Missing warning log for supervision_uploads try/except in prep.py"
        )

    def test_prep_has_try_except_for_standards_documents(self):
        """prep.py must have try/except around standards_documents query."""
        with open("/app/backend/routers/prep.py", "r") as f:
            content = f.read()
        assert "standards_documents" in content, "standards_documents query missing from prep.py"
        assert "could not load standards_documents" in content, (
            "Missing warning log for standards_documents try/except in prep.py"
        )

    def test_prep_has_try_except_for_previous_meetings(self):
        """prep.py must have try/except around previous meetings (analyses SELECT) query."""
        with open("/app/backend/routers/prep.py", "r") as f:
            content = f.read()
        assert "could not load previous meetings" in content, (
            "Missing warning log for previous_meetings try/except in prep.py"
        )

    def test_prep_has_try_except_for_focus_topics(self):
        """prep.py must have try/except around focus_topics query."""
        with open("/app/backend/routers/prep.py", "r") as f:
            content = f.read()
        assert "could not load focus_topics" in content, (
            "Missing warning log for focus_topics try/except in prep.py"
        )

    def test_prep_analyses_query_includes_edited_summary(self):
        """prep.py analyses SELECT must include edited_summary column."""
        with open("/app/backend/routers/prep.py", "r") as f:
            content = f.read()
        assert "edited_summary" in content, (
            "prep.py analyses SELECT is missing 'edited_summary' column — this was the root cause of the 500"
        )


class TestInitDbAnalysesGuards:
    """Verify init_db.py has the new ALTER TABLE IF NOT EXISTS guards for analyses."""

    def test_init_db_has_analyses_edited_summary_guard(self):
        """init_db.py must have ALTER TABLE guard for analyses.edited_summary"""
        with open("/app/backend/init_db.py", "r") as f:
            content = f.read()
        assert "analyses ADD COLUMN IF NOT EXISTS edited_summary" in content, (
            "Missing ALTER TABLE guard for analyses.edited_summary in init_db.py — "
            "this was the root cause: edited_summary column not in production DB"
        )

    def test_init_db_has_analyses_last_edited_at_guard(self):
        """init_db.py must have ALTER TABLE guard for analyses.last_edited_at"""
        with open("/app/backend/init_db.py", "r") as f:
            content = f.read()
        assert "analyses ADD COLUMN IF NOT EXISTS last_edited_at" in content, (
            "Missing ALTER TABLE guard for analyses.last_edited_at in init_db.py"
        )


class TestContextNoAttendees:
    """Test that GET /api/prep/{meetingId}/context returns 200 for a brand new meeting with no attendees."""

    @pytest.fixture(scope="class")
    def no_attendees_meeting_id(self, admin_headers):
        """Create a meeting with NO attendees."""
        import uuid
        payload = {
            "title": f"TEST_NoAttendees_{uuid.uuid4().hex[:8]}",
            "date": "2026-02-15",
            "status": "draft",
        }
        resp = requests.post(f"{BASE_URL}/api/meetings/", json=payload, headers=admin_headers)
        assert resp.status_code in (200, 201), f"Meeting creation failed: {resp.text}"
        data = resp.json()
        meeting_id = data.get("id") or data.get("meeting_id")
        assert meeting_id
        yield meeting_id
        try:
            requests.delete(f"{BASE_URL}/api/meetings/{meeting_id}", headers=admin_headers)
        except Exception:
            pass

    def test_context_returns_200_no_attendees(self, admin_headers, no_attendees_meeting_id):
        """Brand new meeting with NO attendees must return 200 not 500."""
        resp = requests.get(
            f"{BASE_URL}/api/prep/{no_attendees_meeting_id}/context",
            headers=admin_headers
        )
        assert resp.status_code == 200, (
            f"Context returned {resp.status_code} for no-attendees meeting. Response: {resp.text[:400]}"
        )

    def test_context_required_keys_no_attendees(self, admin_headers, no_attendees_meeting_id):
        """No-attendees meeting context response must still have required keys."""
        resp = requests.get(
            f"{BASE_URL}/api/prep/{no_attendees_meeting_id}/context",
            headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        for key in ("meeting_id", "supervisees", "sources", "current_focus_topic"):
            assert key in data, f"Missing key '{key}' in context response: {data}"

    def test_context_empty_supervisees_no_attendees(self, admin_headers, no_attendees_meeting_id):
        """supervisees must be an empty list for a meeting with no attendees."""
        resp = requests.get(
            f"{BASE_URL}/api/prep/{no_attendees_meeting_id}/context",
            headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["supervisees"], list), "supervisees must be a list"
        assert data["supervisees"] == [], (
            f"Expected empty supervisees list for meeting with no attendees, got: {data['supervisees']}"
        )


class TestContextExistingMeetingWithAnalysis:
    """Test context endpoint for an existing meeting that may have attendees + analysis_id.
    This specifically triggers the 'edited_summary' column path that caused the original 500."""

    def test_context_existing_meeting_with_attendees_returns_200(self, admin_headers):
        """Find an existing meeting with attendees/analysis_id and confirm context returns 200."""
        # Fetch meetings list to find a real meeting
        resp = requests.get(f"{BASE_URL}/api/meetings/", headers=admin_headers)
        if resp.status_code != 200:
            pytest.skip(f"Could not fetch meetings list: {resp.status_code}")
        meetings = resp.json()
        if isinstance(meetings, dict):
            meetings = meetings.get("meetings", meetings.get("items", []))
        # Find a meeting with attendees or analysis_id
        target_meeting = None
        for m in meetings:
            if m.get("attendees") or m.get("analysis_id"):
                target_meeting = m
                break
        if not target_meeting and meetings:
            target_meeting = meetings[0]
        if not target_meeting:
            pytest.skip("No meetings found to test against")

        meeting_id = target_meeting.get("id") or target_meeting.get("meeting_id")
        resp2 = requests.get(f"{BASE_URL}/api/prep/{meeting_id}/context", headers=admin_headers)
        assert resp2.status_code == 200, (
            f"Context returned {resp2.status_code} for existing meeting {meeting_id}. "
            f"This is the core bug. Response: {resp2.text[:500]}"
        )
