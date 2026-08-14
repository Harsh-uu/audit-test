"""
Regression test suite for iteration 63 — Schedule edit fix, JSONB guard, PII/evidence improvements
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

ADMIN_CREDS = {"email": "admin@supervision.com", "password": "Admin123!"}
MANAGER_CREDS = {"email": "manager@supervision.com", "password": "Manager123!"}
STAFF_CREDS = {"email": "user@supervision.com", "password": "Staff123!"}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN_CREDS)
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def manager_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=MANAGER_CREDS)
    assert r.status_code == 200, f"Manager login failed: {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def staff_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=STAFF_CREDS)
    assert r.status_code == 200, f"Staff login failed: {r.text}"
    return r.json()["token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# --- Auth / Login Tests ---
class TestLogin:
    def test_admin_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN_CREDS)
        assert r.status_code == 200
        data = r.json()
        assert "token" in data
        assert data.get("role") in ("admin", "super_admin", "manager")

    def test_manager_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json=MANAGER_CREDS)
        assert r.status_code == 200
        assert "token" in r.json()

    def test_staff_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json=STAFF_CREDS)
        assert r.status_code == 200
        assert "token" in r.json()


# --- Dashboard / Meetings List ---
class TestMeetings:
    def test_admin_meetings_list(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/meetings/", headers=auth_headers(admin_token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_staff_meetings_list(self, staff_token):
        r = requests.get(f"{BASE_URL}/api/meetings/", headers=auth_headers(staff_token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# --- Schedules Edit (PUT) ---
class TestSchedules:
    def test_get_schedules(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/schedules/", headers=auth_headers(admin_token))
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_edit_schedule_put(self, admin_token):
        """Verify PUT schedule does not crash with datetime.date vs text bug"""
        r = requests.get(f"{BASE_URL}/api/schedules/", headers=auth_headers(admin_token))
        assert r.status_code == 200
        schedules = r.json()
        if not schedules:
            pytest.skip("No schedules found to edit")
        
        schedule = schedules[0]
        sid = schedule["id"]
        # PUT with plain string start_date
        payload = {
            "frequency": schedule.get("frequency", "monthly"),
            "start_date": "2025-01-01"
        }
        if schedule.get("meeting_type_id"):
            payload["meeting_type_id"] = schedule["meeting_type_id"]
        
        r2 = requests.put(f"{BASE_URL}/api/schedules/{sid}", json=payload, headers=auth_headers(admin_token))
        assert r2.status_code == 200, f"PUT schedule failed: {r2.text}"
        # Response is {"ok": True} — verify no crash (no 500)
        data = r2.json()
        assert data.get("ok") is True or data.get("id") == sid or "start_date" in data


# --- Organisation / PeopleHub ---
class TestOrganisation:
    def test_get_users(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/users", headers=auth_headers(admin_token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_teams(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/teams", headers=auth_headers(admin_token))
        assert r.status_code in (200, 404)  # teams may not exist


# --- Team Insights ---
class TestTeamInsights:
    def test_team_insights_risks(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/team-insights/risks", headers=auth_headers(admin_token))
        assert r.status_code in (200, 404)

    def test_team_insights_actions(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/team-insights/actions", headers=auth_headers(admin_token))
        assert r.status_code in (200, 404)


# --- Meeting Report / Evidence ---
class TestMeetingReport:
    def test_get_meeting_report(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/meetings/", headers=auth_headers(admin_token))
        meetings = r.json()
        if not meetings:
            pytest.skip("No meetings available")
        
        meeting_id = meetings[0]["id"]
        r2 = requests.get(f"{BASE_URL}/api/review/{meeting_id}", headers=auth_headers(admin_token))
        assert r2.status_code in (200, 404)

    def test_evidence_endpoint(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/meetings/", headers=auth_headers(admin_token))
        meetings = r.json()
        if not meetings:
            pytest.skip("No meetings available")
        
        # Find a processed meeting
        processed = [m for m in meetings if m.get("status") in ("reviewed", "signed_off", "processing_complete")]
        if not processed:
            pytest.skip("No processed meetings with evidence")
        
        meeting_id = processed[0]["id"]
        r2 = requests.get(f"{BASE_URL}/api/portfolio/evidence/{meeting_id}", headers=auth_headers(admin_token))
        assert r2.status_code in (200, 404)

    def test_jsonb_guard_processing_status(self, admin_token):
        """Test that processing status endpoint works (uses jsonb_array_elements)"""
        r = requests.get(f"{BASE_URL}/api/meetings/", headers=auth_headers(admin_token))
        meetings = r.json()
        if not meetings:
            pytest.skip("No meetings available")
        meeting_id = meetings[0]["id"]
        r2 = requests.get(f"{BASE_URL}/api/processing/{meeting_id}/status", headers=auth_headers(admin_token))
        assert r2.status_code in (200, 404)
