"""Backend tests for Supervision 2.0 - auth, meetings, recording, admin"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

ADMIN = {"email": "admin@supervision.com", "password": "Admin123!"}
MANAGER = {"email": "manager@supervision.com", "password": "Manager123!"}
STAFF = {"email": "staff@supervision.com", "password": "Staff123!"}


def login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    return r


def auth_header(email, password):
    r = login(email, password)
    token = r.json().get("token")
    return {"Authorization": f"Bearer {token}"}


# --- Auth Tests ---

class TestAuth:
    def test_health(self):
        r = requests.get(f"{BASE_URL}/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_login_admin(self):
        r = login(ADMIN["email"], ADMIN["password"])
        assert r.status_code == 200
        data = r.json()
        assert "token" in data
        assert data["email"] == ADMIN["email"]
        assert data["role"] == "admin"

    def test_login_manager(self):
        r = login(MANAGER["email"], MANAGER["password"])
        assert r.status_code == 200
        data = r.json()
        assert data["role"] == "manager"
        assert "token" in data

    def test_login_staff(self):
        r = login(STAFF["email"], STAFF["password"])
        assert r.status_code == 200
        data = r.json()
        assert "token" in data

    def test_login_invalid(self):
        r = login("bad@bad.com", "wrongpass")
        assert r.status_code == 401

    def test_me_endpoint(self):
        headers = auth_header(ADMIN["email"], ADMIN["password"])
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=headers)
        assert r.status_code == 200
        assert r.json()["email"] == ADMIN["email"]


# --- Meetings Tests ---

class TestMeetings:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.headers = auth_header(ADMIN["email"], ADMIN["password"])

    def test_list_meetings(self):
        r = requests.get(f"{BASE_URL}/api/meetings/", headers=self.headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_meeting(self):
        payload = {
            "title": "TEST_Meeting_pytest",
            "date": "2025-06-15",
            "location": "Room A",
            "meeting_type": "supervision",
            "attendee_ids": [],
        }
        r = requests.post(f"{BASE_URL}/api/meetings/", json=payload, headers=self.headers)
        assert r.status_code == 200
        data = r.json()
        assert "id" in data
        assert data["title"] == "TEST_Meeting_pytest"
        assert data["status"] == "draft"
        TestMeetings.meeting_id = data["id"]

    def test_get_meeting(self):
        if not hasattr(TestMeetings, 'meeting_id'):
            pytest.skip("No meeting created")
        r = requests.get(f"{BASE_URL}/api/meetings/{TestMeetings.meeting_id}", headers=self.headers)
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == TestMeetings.meeting_id

    def test_get_meeting_invalid_id(self):
        r = requests.get(f"{BASE_URL}/api/meetings/invalidid", headers=self.headers)
        assert r.status_code == 400


# --- Recording Tests ---

class TestRecording:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.headers = auth_header(ADMIN["email"], ADMIN["password"])
        # Create a meeting for recording tests
        payload = {
            "title": "TEST_Recording_pytest",
            "date": "2025-06-15",
            "meeting_type": "supervision",
            "attendee_ids": [],
        }
        r = requests.post(f"{BASE_URL}/api/meetings/", json=payload, headers=self.headers)
        self.meeting_id = r.json()["id"]

    def test_recording_notice(self):
        r = requests.post(f"{BASE_URL}/api/recording/{self.meeting_id}/notice", headers=self.headers)
        assert r.status_code == 200

    def test_recording_start(self):
        requests.post(f"{BASE_URL}/api/recording/{self.meeting_id}/notice", headers=self.headers)
        r = requests.post(f"{BASE_URL}/api/recording/{self.meeting_id}/start", json={}, headers=self.headers)
        assert r.status_code == 200

    def test_recording_pause(self):
        requests.post(f"{BASE_URL}/api/recording/{self.meeting_id}/notice", headers=self.headers)
        requests.post(f"{BASE_URL}/api/recording/{self.meeting_id}/start", json={}, headers=self.headers)
        r = requests.post(f"{BASE_URL}/api/recording/{self.meeting_id}/pause", json={}, headers=self.headers)
        assert r.status_code == 200

    def test_recording_resume(self):
        requests.post(f"{BASE_URL}/api/recording/{self.meeting_id}/notice", headers=self.headers)
        requests.post(f"{BASE_URL}/api/recording/{self.meeting_id}/start", json={}, headers=self.headers)
        requests.post(f"{BASE_URL}/api/recording/{self.meeting_id}/pause", json={}, headers=self.headers)
        r = requests.post(f"{BASE_URL}/api/recording/{self.meeting_id}/resume", json={}, headers=self.headers)
        assert r.status_code == 200

    def test_recording_stop(self):
        requests.post(f"{BASE_URL}/api/recording/{self.meeting_id}/notice", headers=self.headers)
        requests.post(f"{BASE_URL}/api/recording/{self.meeting_id}/start", json={}, headers=self.headers)
        r = requests.post(f"{BASE_URL}/api/recording/{self.meeting_id}/stop", json={}, headers=self.headers)
        assert r.status_code == 200

    def test_processing_status(self):
        r = requests.get(f"{BASE_URL}/api/processing/{self.meeting_id}/status", headers=self.headers)
        assert r.status_code == 200


# --- Admin Tests ---

class TestAdmin:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.headers = auth_header(ADMIN["email"], ADMIN["password"])

    def test_list_users(self):
        r = requests.get(f"{BASE_URL}/api/admin/users", headers=self.headers)
        assert r.status_code == 200
        users = r.json()
        assert len(users) >= 3
        emails = [u["email"] for u in users]
        assert "admin@supervision.com" in emails

    def test_list_standards(self):
        r = requests.get(f"{BASE_URL}/api/admin/standards", headers=self.headers)
        assert r.status_code == 200
        standards = r.json()
        assert len(standards) >= 30
        types = {s["type"] for s in standards}
        assert "cqc" in types
        assert "care_cert" in types

    def test_standards_cqc_count(self):
        r = requests.get(f"{BASE_URL}/api/admin/standards?type=cqc", headers=self.headers)
        assert r.status_code == 200
        assert len(r.json()) >= 14

    def test_standards_care_cert_count(self):
        r = requests.get(f"{BASE_URL}/api/admin/standards?type=care_cert", headers=self.headers)
        assert r.status_code == 200
        assert len(r.json()) >= 16
