"""
Test Team Intelligence Registers API endpoints:
- GET /api/admin/team-insights/registers
- PATCH /api/admin/team-insights/actions/{meeting_id}/{action_id}
- PATCH /api/admin/team-insights/learning_needs/{meeting_id}/{ln_id}
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

ADMIN_CREDS = {"email": "admin@supervision.com", "password": "Admin123!"}
MANAGER_CREDS = {"email": "manager@supervision.com", "password": "Manager123!"}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN_CREDS)
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def manager_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=MANAGER_CREDS)
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def manager_headers(manager_token):
    return {"Authorization": f"Bearer {manager_token}"}


class TestGetRegisters:
    """Tests for GET /api/admin/team-insights/registers"""

    def test_admin_can_access(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/team-insights/registers", headers=admin_headers)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"

    def test_response_structure(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/team-insights/registers", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert "actions" in data, "Missing 'actions' key"
        assert "risks" in data, "Missing 'risks' key"
        assert "learning_needs" in data, "Missing 'learning_needs' key"
        assert isinstance(data["actions"], list)
        assert isinstance(data["risks"], list)
        assert isinstance(data["learning_needs"], list)

    def test_manager_can_access(self, manager_headers):
        r = requests.get(f"{BASE_URL}/api/admin/team-insights/registers", headers=manager_headers)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"

    def test_unauthenticated_blocked(self):
        r = requests.get(f"{BASE_URL}/api/admin/team-insights/registers")
        assert r.status_code in [401, 403], f"Expected 401/403, got {r.status_code}"

    def test_actions_item_structure(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/team-insights/registers", headers=admin_headers)
        data = r.json()
        actions = data.get("actions", [])
        if actions:
            a = actions[0]
            assert "id" in a
            assert "text" in a
            assert "completed" in a
            assert "meeting_id" in a
            assert "meeting_title" in a
            assert "meeting_date" in a
            assert "staff_names" in a

    def test_risks_item_structure(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/team-insights/registers", headers=admin_headers)
        data = r.json()
        risks = data.get("risks", [])
        if risks:
            risk = risks[0]
            assert "id" in risk
            assert "text" in risk
            assert "severity" in risk
            assert "is_resolved" in risk
            assert "meeting_id" in risk

    def test_learning_needs_item_structure(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/team-insights/registers", headers=admin_headers)
        data = r.json()
        lns = data.get("learning_needs", [])
        if lns:
            ln = lns[0]
            assert "id" in ln
            assert "text" in ln
            assert "completed" in ln
            assert "meeting_id" in ln

    def test_date_filter_accepted(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/team-insights/registers",
            headers=admin_headers,
            params={"date_from": "2024-01-01", "date_to": "2026-12-31"},
        )
        assert r.status_code == 200


class TestToggleAction:
    """Tests for PATCH /api/admin/team-insights/actions/{meeting_id}/{action_id}"""

    def test_invalid_meeting_returns_404(self, admin_headers):
        r = requests.patch(
            f"{BASE_URL}/api/admin/team-insights/actions/00000000-0000-0000-0000-000000000000/fake_action",
            json={"completed": True},
            headers=admin_headers,
        )
        assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"

    def test_missing_completed_field_returns_400(self, admin_headers):
        r = requests.patch(
            f"{BASE_URL}/api/admin/team-insights/actions/00000000-0000-0000-0000-000000000000/fake_action",
            json={},
            headers=admin_headers,
        )
        assert r.status_code in [400, 404], f"Expected 400 or 404, got {r.status_code}: {r.text}"

    def test_unauthenticated_blocked(self):
        r = requests.patch(
            f"{BASE_URL}/api/admin/team-insights/actions/fake_meeting/fake_action",
            json={"completed": True},
        )
        assert r.status_code in [401, 403]


class TestToggleLearningNeed:
    """Tests for PATCH /api/admin/team-insights/learning_needs/{meeting_id}/{ln_id}"""

    def test_invalid_meeting_returns_404(self, admin_headers):
        r = requests.patch(
            f"{BASE_URL}/api/admin/team-insights/learning_needs/00000000-0000-0000-0000-000000000000/fake_ln",
            json={"completed": True},
            headers=admin_headers,
        )
        assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"

    def test_missing_completed_field_returns_400(self, admin_headers):
        r = requests.patch(
            f"{BASE_URL}/api/admin/team-insights/learning_needs/00000000-0000-0000-0000-000000000000/fake_ln",
            json={},
            headers=admin_headers,
        )
        assert r.status_code in [400, 404]

    def test_unauthenticated_blocked(self):
        r = requests.patch(
            f"{BASE_URL}/api/admin/team-insights/learning_needs/fake_meeting/fake_ln",
            json={"completed": True},
        )
        assert r.status_code in [401, 403]
