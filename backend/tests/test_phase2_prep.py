"""Phase 2 Dynamic Supervision Prep — backend API tests."""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def manager_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "manager@supervision.com", "password": "Manager123!"})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.json()["token"]

@pytest.fixture(scope="module")
def mgr_headers(manager_token):
    return {"Authorization": f"Bearer {manager_token}", "Content-Type": "application/json"}

@pytest.fixture(scope="module")
def jane_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "jane@sunrisecare.com", "password": "Jane1two1!"})
    assert r.status_code == 200, f"Jane login failed: {r.text}"
    return r.json()["token"]

@pytest.fixture(scope="module")
def jane_headers(jane_token):
    return {"Authorization": f"Bearer {jane_token}", "Content-Type": "application/json"}

@pytest.fixture(scope="module")
def a_meeting_id(mgr_headers):
    """Get a meeting ID for the manager's org."""
    r = requests.get(f"{BASE_URL}/api/meetings/", headers=mgr_headers)
    assert r.status_code == 200
    meetings = r.json()
    assert len(meetings) > 0, "No meetings found for manager"
    return str(meetings[0]["id"])

@pytest.fixture(scope="module")
def jane_meeting_id(jane_headers):
    """Get a meeting ID for Jane's org."""
    r = requests.get(f"{BASE_URL}/api/meetings/", headers=jane_headers)
    assert r.status_code == 200
    meetings = r.json()
    assert len(meetings) > 0, "No meetings found for Jane"
    return str(meetings[0]["id"])


# ── Focus Topics ───────────────────────────────────────────────────────────────

class TestFocusTopics:
    """Focus topic CRUD scoped per org."""

    created_topic_id = None

    def test_get_focus_topics_returns_list(self, mgr_headers):
        r = requests.get(f"{BASE_URL}/api/prep/focus-topics", headers=mgr_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        print(f"Focus topics count: {len(r.json())}")

    def test_create_focus_topic_sets_org_and_creator(self, mgr_headers):
        r = requests.post(f"{BASE_URL}/api/prep/focus-topics", json={"topic": "TEST_Prep_FocusTopic", "is_current": True}, headers=mgr_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["topic"] == "TEST_Prep_FocusTopic"
        assert data["is_current"] is True
        assert "org_id" in data and data["org_id"]
        assert "created_by" in data and data["created_by"]
        assert "id" in data
        TestFocusTopics.created_topic_id = data["id"]
        print(f"Created topic id: {TestFocusTopics.created_topic_id}")

    def test_create_current_topic_unsets_previous(self, mgr_headers):
        # Create another is_current topic
        r = requests.post(f"{BASE_URL}/api/prep/focus-topics", json={"topic": "TEST_Prep_FocusTopic2", "is_current": True}, headers=mgr_headers)
        assert r.status_code == 200
        new_id = r.json()["id"]

        # Verify previous is no longer current
        topics = requests.get(f"{BASE_URL}/api/prep/focus-topics", headers=mgr_headers).json()
        current_topics = [t for t in topics if t["is_current"]]
        assert len(current_topics) == 1, f"Expected 1 current topic, got {len(current_topics)}"
        assert current_topics[0]["id"] == new_id

        # Cleanup second
        requests.delete(f"{BASE_URL}/api/prep/focus-topics/{new_id}", headers=mgr_headers)

    def test_put_focus_topic_sets_current(self, mgr_headers):
        tid = TestFocusTopics.created_topic_id
        r = requests.put(f"{BASE_URL}/api/prep/focus-topics/{tid}", json={"topic": "TEST_Prep_FocusTopic", "is_current": True}, headers=mgr_headers)
        assert r.status_code == 200
        print(f"PUT response: {r.json()}")

    def test_delete_focus_topic(self, mgr_headers):
        tid = TestFocusTopics.created_topic_id
        r = requests.delete(f"{BASE_URL}/api/prep/focus-topics/{tid}", headers=mgr_headers)
        assert r.status_code == 200
        # Verify deleted
        topics = requests.get(f"{BASE_URL}/api/prep/focus-topics", headers=mgr_headers).json()
        ids = [t["id"] for t in topics]
        assert tid not in ids
        print("Deleted successfully")

    def test_org_isolation_focus_topics(self, mgr_headers, jane_headers):
        """Manager org topics should not appear in Jane's org."""
        r1 = requests.post(f"{BASE_URL}/api/prep/focus-topics", json={"topic": "TEST_IsolationTopic", "is_current": False}, headers=mgr_headers)
        assert r1.status_code == 200
        new_id = r1.json()["id"]

        jane_topics = requests.get(f"{BASE_URL}/api/prep/focus-topics", headers=jane_headers).json()
        jane_ids = [t["id"] for t in jane_topics]
        assert new_id not in jane_ids, "Org isolation broken: topic visible in another org"
        print("Org isolation verified")

        # Cleanup
        requests.delete(f"{BASE_URL}/api/prep/focus-topics/{new_id}", headers=mgr_headers)


# ── Prep Context ───────────────────────────────────────────────────────────────

class TestPrepContext:

    def test_get_prep_context_structure(self, mgr_headers, a_meeting_id):
        r = requests.get(f"{BASE_URL}/api/prep/{a_meeting_id}/context", headers=mgr_headers)
        assert r.status_code == 200
        data = r.json()
        assert "meeting_id" in data
        assert "supervisees" in data
        assert "sources" in data
        assert isinstance(data["sources"], list)
        # current_focus_topic can be None
        assert "current_focus_topic" in data
        print(f"Context: supervisees={len(data['supervisees'])}, sources={len(data['sources'])}, focus={data['current_focus_topic']}")


# ── Prep CRUD ──────────────────────────────────────────────────────────────────

class TestPrepCRUD:

    def test_get_prep_when_none_exists(self, mgr_headers, a_meeting_id):
        r = requests.get(f"{BASE_URL}/api/prep/{a_meeting_id}", headers=mgr_headers)
        assert r.status_code == 200
        data = r.json()
        assert "gen_status" in data
        assert "sections" in data
        print(f"Prep status: {data['gen_status']}, sections: {len(data['sections'])}")

    def test_generate_returns_generating_immediately(self, mgr_headers, a_meeting_id):
        r = requests.post(
            f"{BASE_URL}/api/prep/{a_meeting_id}/generate",
            params={"focus_topic": "TEST_Focus_Temp"},
            headers=mgr_headers
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "generating", f"Expected status=generating, got: {data}"
        print(f"Generate response: {data}")

    def test_get_prep_after_generate_shows_gen_status(self, mgr_headers, a_meeting_id):
        import time
        # Brief wait to ensure DB write
        time.sleep(1)
        r = requests.get(f"{BASE_URL}/api/prep/{a_meeting_id}", headers=mgr_headers)
        assert r.status_code == 200
        data = r.json()
        assert data.get("gen_status") in ("generating", "done", "failed"), f"Unexpected gen_status: {data}"
        print(f"gen_status after generate: {data.get('gen_status')}")

    def test_put_prep_saves_focus_topic(self, mgr_headers, a_meeting_id):
        r = requests.put(
            f"{BASE_URL}/api/prep/{a_meeting_id}",
            json={"focus_topic": "TEST_SavedTopic", "sections": [], "shared_with_attendees": False},
            headers=mgr_headers
        )
        assert r.status_code == 200
        data = r.json()
        assert "message" in data
        print(f"Save response: {data}")

    def test_put_prep_persists_in_db(self, mgr_headers, a_meeting_id):
        requests.put(
            f"{BASE_URL}/api/prep/{a_meeting_id}",
            json={"focus_topic": "TEST_PersistTopic"},
            headers=mgr_headers
        )
        r = requests.get(f"{BASE_URL}/api/prep/{a_meeting_id}", headers=mgr_headers)
        data = r.json()
        assert data.get("focus_topic") == "TEST_PersistTopic", f"focus_topic not persisted: {data.get('focus_topic')}"
        print("focus_topic persisted correctly")

    def test_share_prep_sets_shared_flag(self, mgr_headers, a_meeting_id):
        r = requests.post(f"{BASE_URL}/api/prep/{a_meeting_id}/share", headers=mgr_headers)
        assert r.status_code == 200
        # Verify shared flag in DB
        prep = requests.get(f"{BASE_URL}/api/prep/{a_meeting_id}", headers=mgr_headers).json()
        assert prep.get("shared_with_attendees") is True, f"shared_with_attendees not set: {prep}"
        print("shared_with_attendees=True verified")

    def test_share_prep_without_prep_returns_404(self, mgr_headers):
        """Sharing a meeting with no prep should return 404."""
        # Use a fake meeting ID to test
        r = requests.post(f"{BASE_URL}/api/prep/000000000000000000000001/share", headers=mgr_headers)
        assert r.status_code in (404, 400)
        print(f"Expected error response: {r.status_code}")


# ── Access control ─────────────────────────────────────────────────────────────

class TestPrepAccessControl:

    def test_attendee_cannot_create_focus_topic(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "staff@supervision.com", "password": "Staff123!"})
        if r.status_code != 200:
            pytest.skip("Staff login failed")
        token = r.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        r2 = requests.post(f"{BASE_URL}/api/prep/focus-topics", json={"topic": "Unauthorized", "is_current": False}, headers=headers)
        assert r2.status_code == 403
        print(f"Attendee correctly blocked: {r2.status_code}")
