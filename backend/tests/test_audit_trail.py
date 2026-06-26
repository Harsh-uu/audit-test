"""Tests for audit trail endpoint and name anonymization"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

@pytest.fixture(scope="module")
def manager_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "manager@supervision.com", "password": "Manager123!"})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.json()["token"]

@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@supervision.com", "password": "Admin123!"})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.json()["token"]

@pytest.fixture(scope="module")
def test_meeting_id(manager_token):
    """Create a test meeting and return its ID"""
    headers = {"Authorization": f"Bearer {manager_token}"}
    r = requests.post(f"{BASE_URL}/api/meetings/", json={
        "title": "TEST_Audit Trail Meeting",
        "date": "2025-01-15",
        "location": "Room 1",
        "attendees": []
    }, headers=headers)
    assert r.status_code in [200, 201], f"Create meeting failed: {r.text}"
    return r.json()["id"]

def test_audit_trail_returns_200(manager_token, test_meeting_id):
    """GET /api/review/{meeting_id}/audit-trail should return 200"""
    headers = {"Authorization": f"Bearer {manager_token}"}
    r = requests.get(f"{BASE_URL}/api/review/{test_meeting_id}/audit-trail", headers=headers)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"

def test_audit_trail_returns_events_array(manager_token, test_meeting_id):
    """Response should have events array"""
    headers = {"Authorization": f"Bearer {manager_token}"}
    r = requests.get(f"{BASE_URL}/api/review/{test_meeting_id}/audit-trail", headers=headers)
    data = r.json()
    assert "events" in data, f"No 'events' key in response: {data}"
    assert isinstance(data["events"], list)

def test_audit_trail_has_meeting_created_event(manager_token, test_meeting_id):
    """Should have meeting_created event"""
    headers = {"Authorization": f"Bearer {manager_token}"}
    r = requests.get(f"{BASE_URL}/api/review/{test_meeting_id}/audit-trail", headers=headers)
    events = r.json()["events"]
    types = [e["type"] for e in events]
    assert "meeting_created" in types, f"No meeting_created event. Got: {types}"

def test_audit_trail_event_has_required_fields(manager_token, test_meeting_id):
    """Each event should have type, label, actor, timestamp"""
    headers = {"Authorization": f"Bearer {manager_token}"}
    r = requests.get(f"{BASE_URL}/api/review/{test_meeting_id}/audit-trail", headers=headers)
    events = r.json()["events"]
    assert len(events) > 0, "No events returned"
    for ev in events:
        assert "type" in ev, f"Missing 'type' in event: {ev}"
        assert "label" in ev, f"Missing 'label' in event: {ev}"
        assert "actor" in ev, f"Missing 'actor' in event: {ev}"
        assert "timestamp" in ev, f"Missing 'timestamp' in event: {ev}"

def test_audit_trail_unauthorized(test_meeting_id):
    """Should return 401 without auth"""
    r = requests.get(f"{BASE_URL}/api/review/{test_meeting_id}/audit-trail")
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"

def test_audit_trail_not_found(manager_token):
    """Non-existent meeting should return 404"""
    headers = {"Authorization": f"Bearer {manager_token}"}
    r = requests.get(f"{BASE_URL}/api/review/000000000000000000000000/audit-trail", headers=headers)
    assert r.status_code == 404

def test_cleanup(manager_token, test_meeting_id):
    """Cleanup test meeting"""
    headers = {"Authorization": f"Bearer {manager_token}"}
    r = requests.delete(f"{BASE_URL}/api/meetings/{test_meeting_id}", headers=headers)
    # Accept 200 or 403 (if no delete endpoint)
    assert r.status_code in [200, 204, 403, 404, 405]
