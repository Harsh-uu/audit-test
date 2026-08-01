"""
PostgreSQL Migration Verification Tests
Tests all key flows after MongoDB -> PostgreSQL migration
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

ADMIN_CREDS = {"email": "admin@supervision.com", "password": "Admin123!"}
MANAGER_CREDS = {"email": "manager@supervision.com", "password": "Manager123!"}
STAFF_CREDS = {"email": "staff@supervision.com", "password": "Staff123!"}
SUPER_ADMIN_CREDS = {"email": "superadmin@1two.one", "password": "SuperAdmin123!"}

STAFF_USER_ID = "043d55cd-beb9-45e6-809f-4ce9b59bcaab"
MANAGER_USER_ID = "1125f43c-1706-48d8-8c2d-fdca7e33da90"
ORG_ID = "683ddc1c-36ac-4857-93f3-55098ab3c9c0"
EXISTING_MEETING_ID = "d81c9f24-d419-49f1-b9a1-b7a22c2d0bc7"


def get_token(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds)
    if r.status_code == 200:
        data = r.json()
        return data.get("token") or data.get("access_token")
    return None


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# --- Auth Tests ---
class TestAuthentication:
    """Test login for all user roles"""

    def test_admin_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN_CREDS)
        assert r.status_code == 200, f"Admin login failed: {r.text}"
        data = r.json()
        assert "token" in data, f"No token in response: {list(data.keys())}"
        assert data.get("role") in ["admin", "super_admin"]

    def test_manager_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json=MANAGER_CREDS)
        assert r.status_code == 200, f"Manager login failed: {r.text}"
        assert "token" in r.json()

    def test_staff_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json=STAFF_CREDS)
        assert r.status_code == 200, f"Staff login failed: {r.text}"
        assert "token" in r.json()

    def test_superadmin_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json=SUPER_ADMIN_CREDS)
        assert r.status_code == 200, f"SuperAdmin login failed: {r.text}"
        assert "token" in r.json()


# --- Meetings Tests ---
class TestMeetings:
    """Test meetings list and creation"""

    def setup_method(self):
        self.token = get_token(MANAGER_CREDS)
        self.headers = auth_headers(self.token)
        self.created_id = None

    def test_meetings_list(self):
        r = requests.get(f"{BASE_URL}/api/meetings/", headers=self.headers)
        assert r.status_code == 200, f"Meetings list failed: {r.text}"
        data = r.json()
        assert isinstance(data, list)
        # Verify attendees are lists not strings
        for m in data:
            if "attendees" in m:
                assert isinstance(m["attendees"], list), f"attendees should be list, got {type(m['attendees'])}: {m['attendees']}"

    def test_create_meeting(self):
        payload = {
            "title": "TEST_PG Migration Test Meeting",
            "date": "2026-02-15",
            "attendee_ids": [STAFF_USER_ID],
            "notes": "Testing PG migration"
        }
        r = requests.post(f"{BASE_URL}/api/meetings/", json=payload, headers=self.headers)
        assert r.status_code in [200, 201], f"Create meeting failed: {r.text}"
        data = r.json()
        assert "id" in data or "meeting_id" in data
        meeting_id = data.get("id") or data.get("meeting_id")
        assert data.get("status") == "draft"
        # Attendees should be a list
        attendees = data.get("attendees", [])
        assert isinstance(attendees, list), f"attendees should be list, got: {type(attendees)}"
        self.__class__.created_meeting_id = meeting_id
        return meeting_id


# --- Review Tests ---
class TestReview:
    """Test review page GET"""

    def setup_method(self):
        self.token = get_token(MANAGER_CREDS)
        self.headers = auth_headers(self.token)

    def test_review_existing_meeting(self):
        r = requests.get(f"{BASE_URL}/api/review/{EXISTING_MEETING_ID}", headers=self.headers)
        assert r.status_code == 200, f"Review GET failed: {r.text}"
        data = r.json()
        assert "attendees" in data or "meeting" in data
        # Verify attendees are list not string
        attendees = data.get("attendees") or data.get("meeting", {}).get("attendees", [])
        assert isinstance(attendees, list), f"attendees must be list, got: {type(attendees)}"


# --- Prep Context ---
class TestPrepContext:
    """Test prep context returns supervisees list"""

    def setup_method(self):
        self.token = get_token(MANAGER_CREDS)
        self.headers = auth_headers(self.token)

    def test_prep_context(self):
        r = requests.get(f"{BASE_URL}/api/prep/{EXISTING_MEETING_ID}/context", headers=self.headers)
        assert r.status_code == 200, f"Prep context failed: {r.text}"
        data = r.json()
        assert "supervisees" in data, f"Missing supervisees in: {data}"
        assert isinstance(data["supervisees"], list), f"supervisees must be list, got: {type(data['supervisees'])}"


# --- Standards ---
class TestStandards:
    """Test standards return proper list of objects"""

    def setup_method(self):
        self.token = get_token(ADMIN_CREDS)
        self.headers = auth_headers(self.token)

    def test_standards_list(self):
        r = requests.get(f"{BASE_URL}/api/admin/standards", headers=self.headers)
        assert r.status_code == 200, f"Standards failed: {r.text}"
        data = r.json()
        assert isinstance(data, list), f"Standards must be list, got: {type(data)}"
        assert len(data) == 63, f"Expected 63 standards, got {len(data)}"
        # Check items are objects (dicts) not strings
        for item in data:
            assert isinstance(item, dict), f"Standard item must be dict, got: {type(item)}: {item}"
        # Check care cert standards have sub_outcomes as list
        care_cert = [s for s in data if s.get("framework") == "care_cert" or "care_cert" in str(s.get("type", ""))]
        for s in care_cert[:3]:
            if "sub_outcomes" in s:
                assert isinstance(s["sub_outcomes"], list), f"sub_outcomes must be list: {s}"


# --- Team Insights ---
class TestTeamInsights:
    """Test team insights returns matrix"""

    def setup_method(self):
        self.token = get_token(ADMIN_CREDS)
        self.headers = auth_headers(self.token)

    def test_team_insights(self):
        r = requests.get(f"{BASE_URL}/api/admin/team-insights", headers=self.headers)
        assert r.status_code == 200, f"Team insights failed: {r.text}"
        data = r.json()
        assert "matrix" in data, f"Missing 'matrix' key in: {list(data.keys())}"


# --- Portfolio ---
class TestPortfolio:
    """Test portfolio endpoint"""

    def setup_method(self):
        self.token = get_token(ADMIN_CREDS)
        self.headers = auth_headers(self.token)

    def test_portfolio_staff(self):
        r = requests.get(f"{BASE_URL}/api/portfolio/{STAFF_USER_ID}", headers=self.headers)
        assert r.status_code == 200, f"Portfolio failed: {r.text}"
        data = r.json()
        assert "meetings" in data or "user" in data, f"Unexpected response: {list(data.keys())}"


# --- Doc Uploads ---
class TestDocUploads:
    """Test doc uploads list"""

    def setup_method(self):
        self.token = get_token(ADMIN_CREDS)
        self.headers = auth_headers(self.token)

    def test_doc_uploads_list(self):
        r = requests.get(f"{BASE_URL}/api/doc-uploads/", headers=self.headers)
        assert r.status_code == 200, f"Doc uploads failed: {r.text}"
        data = r.json()
        assert isinstance(data, list)


# --- Recording Flow ---
class TestRecording:
    """Test recording start/stop flow"""

    def setup_method(self):
        self.token = get_token(MANAGER_CREDS)
        self.headers = auth_headers(self.token)

    def test_recording_start_stop(self):
        # First create a meeting to record
        payload = {
            "title": "TEST_Recording Flow Meeting",
            "date": "2026-02-15",
            "attendee_ids": [STAFF_USER_ID],
        }
        cr = requests.post(f"{BASE_URL}/api/meetings/", json=payload, headers=self.headers)
        assert cr.status_code in [200, 201], f"Create failed: {cr.text}"
        meeting_id = cr.json().get("id") or cr.json().get("meeting_id")

        # Start recording (notice first)
        nr = requests.post(f"{BASE_URL}/api/recording/{meeting_id}/notice", headers=self.headers)
        print(f"Notice response: {nr.status_code} {nr.text[:200]}")

        sr = requests.post(f"{BASE_URL}/api/recording/{meeting_id}/start", headers=self.headers)
        print(f"Start recording: {sr.status_code} {sr.text[:200]}")
        assert sr.status_code != 500, f"Recording start 500 error: {sr.text}"

        # Stop recording
        stopr = requests.post(f"{BASE_URL}/api/recording/{meeting_id}/stop", headers=self.headers)
        print(f"Stop recording: {stopr.status_code} {stopr.text[:200]}")
        assert stopr.status_code != 500, f"Recording stop 500 error: {stopr.text}"


# --- Super Admin ---
class TestSuperAdmin:
    """Test super admin org listing"""

    def setup_method(self):
        self.token = get_token(SUPER_ADMIN_CREDS)
        self.headers = auth_headers(self.token)

    def test_super_admin_orgs(self):
        r = requests.get(f"{BASE_URL}/api/super-admin/orgs", headers=self.headers)
        assert r.status_code == 200, f"Super admin orgs failed: {r.text}"
        data = r.json()
        assert isinstance(data, list)
        # Find Test Company org
        test_org = next((o for o in data if o.get("id") == ORG_ID or "Test Company" in o.get("name", "")), None)
        assert test_org is not None, f"Test Company org not found in: {[o.get('name') for o in data]}"
        assert test_org.get("user_count", 0) >= 3, f"Expected user_count>=3, got: {test_org.get('user_count')}"
