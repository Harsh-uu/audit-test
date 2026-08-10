"""Test achievements feature - analyses.achievements column and API response"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

@pytest.fixture(scope="module")
def auth_token():
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@supervision.com",
        "password": "Admin123!"
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["token"]

@pytest.fixture(scope="module")
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}

def test_login(auth_token):
    assert auth_token is not None and len(auth_token) > 0
    print("Login OK")

def test_meetings_list_returns_achievements(auth_headers):
    """GET /api/meetings/ - check meetings exist"""
    resp = requests.get(f"{BASE_URL}/api/meetings/", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    print(f"Found {len(data)} meetings")

def test_meeting_detail_has_achievements(auth_headers):
    """GET /api/meetings/{id} - check achievements key present"""
    # Get list first
    resp = requests.get(f"{BASE_URL}/api/meetings/", headers=auth_headers)
    assert resp.status_code == 200
    meetings = resp.json()
    
    # Find an analysed meeting
    analysed = [m for m in meetings if m.get("status") in ("analysed", "reviewed", "signed_off")]
    if not analysed:
        pytest.skip("No analysed meetings found")
    
    meeting_id = analysed[0]["id"]
    print(f"Testing meeting {meeting_id}")
    
    detail_resp = requests.get(f"{BASE_URL}/api/meetings/{meeting_id}", headers=auth_headers)
    assert detail_resp.status_code == 200, f"Meeting detail failed: {detail_resp.text}"
    detail = detail_resp.json()
    
    # Check analysis object
    analysis = detail.get("analysis")
    assert analysis is not None, "No analysis object in meeting detail"
    
    # Check achievements key exists
    assert "achievements" in analysis, f"achievements key missing from analysis. Keys: {list(analysis.keys())}"
    
    # Check it's a list (not string)
    achievements = analysis["achievements"]
    assert isinstance(achievements, list), f"achievements should be a list, got {type(achievements)}: {achievements}"
    
    print(f"achievements = {achievements} (type: {type(achievements).__name__})")
    print("PASS: achievements key exists and is a list")

def test_achievements_not_string(auth_headers):
    """Ensure achievements is not returned as a JSON string (JSONB parsing issue)"""
    resp = requests.get(f"{BASE_URL}/api/meetings/", headers=auth_headers)
    meetings = resp.json()
    analysed = [m for m in meetings if m.get("status") in ("analysed", "reviewed", "signed_off")]
    if not analysed:
        pytest.skip("No analysed meetings")
    
    meeting_id = analysed[0]["id"]
    detail = requests.get(f"{BASE_URL}/api/meetings/{meeting_id}", headers=auth_headers).json()
    analysis = detail.get("analysis", {})
    achievements = analysis.get("achievements")
    
    assert not isinstance(achievements, str), f"achievements is a string instead of list: {achievements}"
    print("PASS: achievements is not a string")
