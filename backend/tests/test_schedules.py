"""
Backend tests for Schedules feature and Speaker Panel badge
Tests: meeting types CRUD, schedule CRUD, bulk assign, due endpoint, speaker-text PATCH
"""
import pytest
import requests
import os
from datetime import date, timedelta

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

ADMIN = {"email": "admin@supervision.com", "password": "Admin123!"}
MANAGER = {"email": "manager@supervision.com", "password": "Manager123!"}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN)
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def manager_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=MANAGER)
    assert r.status_code == 200, f"Manager login failed: {r.text}"
    return r.json()["token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


class TestMeetingTypes:
    """Meeting Types CRUD tests"""

    def test_list_meeting_types_seeds_defaults(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/schedules/meeting-types", headers=auth(admin_token))
        assert r.status_code == 200
        data = r.json()
        names = [t["name"] for t in data]
        for expected in ["Monthly Supervision", "Quarterly Team Meeting", "Quarterly Appraisal", "Annual Performance Review"]:
            assert expected in names, f"Default type '{expected}' not found in {names}"
        print(f"PASS: {len(data)} meeting types returned, defaults present")

    def test_create_meeting_type(self, admin_token):
        payload = {"name": "TEST_Custom Type", "default_frequency": "monthly", "color": "#FF0000"}
        r = requests.post(f"{BASE_URL}/api/schedules/meeting-types", json=payload, headers=auth(admin_token))
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "TEST_Custom Type"
        assert "id" in data
        TestMeetingTypes._created_type_id = data["id"]
        print(f"PASS: Created meeting type {data['id']}")

    def test_delete_meeting_type(self, admin_token):
        type_id = getattr(TestMeetingTypes, "_created_type_id", None)
        if not type_id:
            pytest.skip("No type to delete")
        r = requests.delete(f"{BASE_URL}/api/schedules/meeting-types/{type_id}", headers=auth(admin_token))
        assert r.status_code == 200
        print("PASS: Deleted meeting type")


class TestSchedules:
    """Schedule CRUD tests"""

    _schedule_id = None
    _staff_id = None
    _type_id = None

    @pytest.fixture(autouse=True, scope="class")
    def setup(self, admin_token):
        # Get meeting types
        r = requests.get(f"{BASE_URL}/api/schedules/meeting-types", headers=auth(admin_token))
        types = r.json()
        assert len(types) > 0
        TestSchedules._type_id = types[0]["id"]

        # Get staff user
        r2 = requests.get(f"{BASE_URL}/api/admin/users", headers=auth(admin_token))
        assert r2.status_code == 200
        users = r2.json()
        staff_users = [u for u in users if u.get("role") == "attendee"]
        assert len(staff_users) > 0, "Need at least one staff user"
        TestSchedules._staff_id = staff_users[0]["id"]
        yield

    def test_create_schedule(self, admin_token):
        past_date = (date.today() - timedelta(days=30)).isoformat()
        payload = {
            "staff_user_id": TestSchedules._staff_id,
            "meeting_type_id": TestSchedules._type_id,
            "frequency": "monthly",
            "start_date": past_date,
        }
        r = requests.post(f"{BASE_URL}/api/schedules/", json=payload, headers=auth(admin_token))
        # Allow 400 if schedule already exists
        if r.status_code == 400:
            print("SKIP: Schedule already exists for this staff/type combo")
            return
        assert r.status_code == 200, f"Failed: {r.text}"
        data = r.json()
        assert "id" in data
        TestSchedules._schedule_id = data["id"]
        print(f"PASS: Created schedule {data['id']}")

    def test_list_schedules(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/schedules/", headers=auth(admin_token))
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        print(f"PASS: {len(data)} schedules returned")
        if data:
            s = data[0]
            assert "next_due" in s
            assert "staff_name" in s
            assert "meeting_type_name" in s

    def test_due_endpoint_manager(self, manager_token):
        r = requests.get(f"{BASE_URL}/api/schedules/due", headers=auth(manager_token))
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        print(f"PASS: /schedules/due returned {len(data)} items")
        for s in data:
            assert "next_due" in s
            assert "is_overdue" in s
            assert "staff_name" in s

    def test_delete_schedule(self, admin_token):
        sid = TestSchedules._schedule_id
        if not sid:
            # Find one to delete
            r = requests.get(f"{BASE_URL}/api/schedules/", headers=auth(admin_token))
            schedules = r.json()
            if not schedules:
                pytest.skip("No schedules to delete")
            sid = schedules[0]["id"]
        r = requests.delete(f"{BASE_URL}/api/schedules/{sid}", headers=auth(admin_token))
        assert r.status_code == 200
        print(f"PASS: Deleted schedule {sid}")


class TestBulkAssign:
    """Bulk schedule creation tests"""

    def test_bulk_create_schedules(self, admin_token):
        # Get meeting type and staff users
        r = requests.get(f"{BASE_URL}/api/schedules/meeting-types", headers=auth(admin_token))
        types = r.json()
        type_id = types[0]["id"]

        r2 = requests.get(f"{BASE_URL}/api/admin/users", headers=auth(admin_token))
        users = r2.json()
        staff_ids = [u["id"] for u in users if u.get("role") == "attendee"][:2]

        past_date = (date.today() - timedelta(days=60)).isoformat()
        payload = {
            "meeting_type_id": type_id,
            "frequency": "monthly",
            "start_date": past_date,
            "staff_user_ids": staff_ids,
        }
        r = requests.post(f"{BASE_URL}/api/schedules/bulk", json=payload, headers=auth(admin_token))
        assert r.status_code == 200
        data = r.json()
        assert "created" in data
        assert "skipped" in data
        print(f"PASS: Bulk created {data['created']}, skipped {data['skipped']}")


class TestSpeakerTextBadge:
    """Speaker panel last-edited badge — backend API tests"""

    def test_speaker_text_patch_returns_edited_fields(self, manager_token):
        # Get a meeting that has a transcript
        r = requests.get(f"{BASE_URL}/api/meetings/", headers=auth(manager_token))
        assert r.status_code == 200
        meetings = r.json()
        meeting_with_transcript = None
        for m in meetings:
            if m.get("status") in ["in_review", "reviewed", "signed_off"]:
                meeting_with_transcript = m
                break
        if not meeting_with_transcript:
            pytest.skip("No processed meeting found to test speaker-text PATCH")

        mid = meeting_with_transcript["id"]
        r2 = requests.get(f"{BASE_URL}/api/review/{mid}", headers=auth(manager_token))
        if r2.status_code != 200:
            pytest.skip(f"Cannot fetch review for meeting {mid}")
        review_data = r2.json()
        speaker_text = review_data.get("transcript", {}).get("speaker_text") or review_data.get("speaker_text")
        if not speaker_text:
            pytest.skip("No speaker_text found in meeting transcript")

        patch_r = requests.patch(
            f"{BASE_URL}/api/review/{mid}/speaker-text",
            json={"speaker_text": speaker_text},
            headers=auth(manager_token),
        )
        assert patch_r.status_code == 200
        data = patch_r.json()
        assert "edited_by_name" in data, f"edited_by_name missing from response: {data}"
        assert "edited_at" in data, f"edited_at missing from response: {data}"
        assert data["edited_by_name"] != ""
        print(f"PASS: speaker-text PATCH returns edited_by_name='{data['edited_by_name']}', edited_at='{data['edited_at']}'")
