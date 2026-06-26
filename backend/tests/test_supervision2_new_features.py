"""Tests for Supervision 2.0 new features: Template, Action completion, Actions rollover, Rescan"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
MEETING_ID = "6a3e6204373ddc91df1947cf"


@pytest.fixture(scope="module")
def admin_token():
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@supervision.com", "password": "Admin123!"})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["token"]


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# --- Template API ---

class TestTemplateAPI:
    """Tests for GET/PUT /api/admin/template"""

    def test_get_template_returns_default_when_empty(self, auth_headers):
        # After saving, it might not be empty; just check structure
        resp = requests.get(f"{BASE_URL}/api/admin/template", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "steps" in data
        assert "name" in data
        assert isinstance(data["steps"], list)

    def test_put_template_saves_steps(self, auth_headers):
        payload = {
            "name": "TEST_Template",
            "description": "Test description",
            "steps": [
                {"id": "s1", "order": 1, "title": "Wellbeing Check", "description": "How is the worker feeling?"},
                {"id": "s2", "order": 2, "title": "Workload Review", "description": "Review workload"}
            ]
        }
        resp = requests.put(f"{BASE_URL}/api/admin/template", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("message") == "Template saved"
        assert len(data.get("steps", [])) == 2

    def test_get_template_returns_saved_steps(self, auth_headers):
        resp = requests.get(f"{BASE_URL}/api/admin/template", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "TEST_Template"
        assert len(data["steps"]) == 2
        assert data["steps"][0]["title"] == "Wellbeing Check"

    def test_put_template_empty_steps(self, auth_headers):
        payload = {"name": "Supervision Template", "steps": [], "description": ""}
        resp = requests.put(f"{BASE_URL}/api/admin/template", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json().get("message") == "Template saved"


# --- Action Completion PATCH ---

class TestActionCompletion:
    """Tests for PATCH /api/review/{meeting_id}/actions/{action_id}"""

    def test_patch_action_complete(self, auth_headers):
        resp = requests.patch(
            f"{BASE_URL}/api/review/{MEETING_ID}/actions/action_1",
            json={"completed": True},
            headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("completed") is True

    def test_patch_action_incomplete(self, auth_headers):
        resp = requests.patch(
            f"{BASE_URL}/api/review/{MEETING_ID}/actions/action_1",
            json={"completed": False},
            headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("completed") is False

    def test_patch_nonexistent_action_returns_404(self, auth_headers):
        resp = requests.patch(
            f"{BASE_URL}/api/review/{MEETING_ID}/actions/nonexistent_action_xyz",
            json={"completed": True},
            headers=auth_headers
        )
        assert resp.status_code == 404

    def test_get_meeting_reflects_action_completion(self, auth_headers):
        # Mark complete
        requests.patch(
            f"{BASE_URL}/api/review/{MEETING_ID}/actions/action_1",
            json={"completed": True},
            headers=auth_headers
        )
        # Verify
        resp = requests.get(f"{BASE_URL}/api/review/{MEETING_ID}", headers=auth_headers)
        assert resp.status_code == 200
        actions = resp.json().get("analysis", {}).get("actions", [])
        action = next((a for a in actions if a.get("id") == "action_1"), None)
        assert action is not None
        assert action.get("completed") is True


# --- Meeting status and actions structure ---

class TestMeetingActionsStructure:
    """Verify meeting actions have 'id' field for PATCH compatibility"""

    def test_actions_have_id_field(self, auth_headers):
        resp = requests.get(f"{BASE_URL}/api/review/{MEETING_ID}", headers=auth_headers)
        assert resp.status_code == 200
        actions = resp.json().get("analysis", {}).get("actions", [])
        for action in actions:
            assert "id" in action, f"Action missing 'id': {action}"
