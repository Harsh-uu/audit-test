"""
Tests for POST /api/review/{meeting_id}/rescan-evidence
Verifies background task pattern: returns 200 immediately with status='processing'
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


@pytest.fixture(scope="module")
def jane_token():
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "jane@sunrisecare.com",
        "password": "Jane1two1!"
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["token"]


@pytest.fixture(scope="module")
def jane_headers(jane_token):
    return {"Authorization": f"Bearer {jane_token}"}


@pytest.fixture(scope="module")
def signed_off_meeting_id(jane_headers):
    """Find Jane's signed-off meeting with transcript_id set."""
    resp = requests.get(f"{BASE_URL}/api/meetings/", headers=jane_headers)
    assert resp.status_code == 200
    meetings = resp.json()
    for m in meetings:
        if m.get("status") in ("signed_off", "in_review", "reviewed") and m.get("transcript_id"):
            return m["id"]
    pytest.skip("No suitable meeting found for rescan test")


# Test 1: Endpoint returns 200 immediately with status='processing'
def test_rescan_returns_processing_immediately(jane_headers, signed_off_meeting_id):
    """Critical: endpoint must return quickly (no timeout) with status:processing."""
    start = time.time()
    resp = requests.post(
        f"{BASE_URL}/api/review/{signed_off_meeting_id}/rescan-evidence",
        headers=jane_headers,
        timeout=15  # Should return well within 15s
    )
    elapsed = time.time() - start

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data.get("status") == "processing", f"Expected status='processing', got: {data}"
    assert "message" in data, "Response should include a message"
    assert elapsed < 10, f"Endpoint took too long: {elapsed:.1f}s (should be < 10s)"
    print(f"PASS: rescan returned in {elapsed:.2f}s with status='processing'")


# Test 2: Meeting rescan_status is set to 'processing' in DB immediately
def test_rescan_status_set_to_processing_in_db(jane_headers, signed_off_meeting_id):
    """After calling rescan, meeting should have rescan_status='processing' in DB."""
    # Call rescan
    requests.post(
        f"{BASE_URL}/api/review/{signed_off_meeting_id}/rescan-evidence",
        headers=jane_headers,
        timeout=15
    )
    # Fetch meeting
    resp = requests.get(f"{BASE_URL}/api/meetings/{signed_off_meeting_id}", headers=jane_headers)
    assert resp.status_code == 200
    meeting = resp.json()
    rescan_status = meeting.get("rescan_status")
    # Should be 'processing' or 'done' (if background completed very fast)
    assert rescan_status in ("processing", "done"), f"rescan_status={rescan_status}"
    print(f"PASS: rescan_status in DB = '{rescan_status}'")


# Test 3: Auth - non-manager cannot rescan
def test_rescan_requires_manager_role():
    """Staff/attendee should not be able to trigger rescan."""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "steve.alex@1two.one",
        "password": "Steve1two1!"
    })
    if resp.status_code != 200:
        pytest.skip("Steve account not accessible")
    token = resp.json().get("token")
    headers = {"Authorization": f"Bearer {token}"}
    # Get a meeting id from jane's org — Steve might not have access; just test with any meeting
    meetings_resp = requests.get(f"{BASE_URL}/api/meetings/", headers=headers)
    if meetings_resp.status_code != 200 or not meetings_resp.json():
        pytest.skip("No meetings accessible for Steve")
    meeting_id = meetings_resp.json()[0]["id"]
    resp = requests.post(f"{BASE_URL}/api/review/{meeting_id}/rescan-evidence", headers=headers)
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
    print("PASS: Non-manager correctly gets 403")


# Test 4: Unauthenticated request rejected
def test_rescan_requires_auth(signed_off_meeting_id):
    resp = requests.post(f"{BASE_URL}/api/review/{signed_off_meeting_id}/rescan-evidence")
    assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"
    print("PASS: Unauthenticated request rejected")


# Test 5: Verify meeting report page data loads (regression)
def test_meeting_report_data_loads(jane_headers, signed_off_meeting_id):
    """Regression: GET /api/review/{meeting_id} should return full meeting with analysis."""
    resp = requests.get(f"{BASE_URL}/api/review/{signed_off_meeting_id}", headers=jane_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "analysis" in data or data.get("analysis_id"), "Meeting should have analysis data"
    print(f"PASS: Meeting report data loaded. Status: {data.get('status')}")
    if data.get("analysis"):
        cqc = len(data["analysis"].get("cqc_mappings", []))
        print(f"  CQC mappings: {cqc}")


# Test 6: Wait and verify background task completes (rescan_status becomes 'done')
def test_rescan_background_task_completes(jane_headers, signed_off_meeting_id):
    """
    After triggering rescan, wait up to 90s for rescan_status to become 'done'.
    This verifies the background task runs to completion.
    """
    # Trigger rescan
    resp = requests.post(
        f"{BASE_URL}/api/review/{signed_off_meeting_id}/rescan-evidence",
        headers=jane_headers,
        timeout=15
    )
    assert resp.status_code == 200
    assert resp.json().get("status") == "processing"

    # Poll for up to 90 seconds
    deadline = time.time() + 90
    final_status = None
    while time.time() < deadline:
        time.sleep(5)
        m_resp = requests.get(f"{BASE_URL}/api/meetings/{signed_off_meeting_id}", headers=jane_headers)
        if m_resp.status_code == 200:
            final_status = m_resp.json().get("rescan_status")
            if final_status in ("done", "failed"):
                break
        print(f"  Polling... rescan_status={final_status}")

    assert final_status == "done", f"Background task did not complete. Final status: {final_status}"
    print(f"PASS: Background rescan completed with status='{final_status}'")
