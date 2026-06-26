"""
Test: Reject/Accept/Flag buttons for all evidence types (CQC, Care Certificate, Custom/Organisational)
Tests the fix where custom_mappings were not being updated in the evidence update loop.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s

@pytest.fixture(scope="module")
def auth_token(session):
    resp = session.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@supervision.com",
        "password": "Admin123!"
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json().get("access_token") or resp.json().get("token")
    assert token, f"No token in response: {resp.json()}"
    return token

@pytest.fixture(scope="module")
def authed(session, auth_token):
    session.headers.update({"Authorization": f"Bearer {auth_token}"})
    return session

@pytest.fixture(scope="module")
def meeting_with_analysis(authed):
    """Find a processed meeting with analysis that has custom_mappings"""
    resp = authed.get(f"{BASE_URL}/api/meetings/")
    assert resp.status_code == 200
    meetings = resp.json()
    # Find meeting in in_review or reviewed status
    for m in meetings:
        status = m.get("status", "")
        if status in ["in_review", "reviewed", "signed_off"]:
            meeting_id = m.get("id") or str(m.get("_id", ""))
            if meeting_id:
                # Get review data
                review_resp = authed.get(f"{BASE_URL}/api/review/{meeting_id}")
                if review_resp.status_code == 200:
                    return meeting_id, review_resp.json()
    return None, None


class TestEvidenceUpdateFix:
    """Test evidence accept/reject/flag for all mapping types"""

    def test_login_works(self, auth_token):
        assert auth_token is not None
        print("Login successful")

    def test_meeting_with_analysis_exists(self, meeting_with_analysis):
        meeting_id, review_data = meeting_with_analysis
        if meeting_id is None:
            pytest.skip("No processed meeting found in in_review/reviewed state")
        print(f"Found meeting: {meeting_id}")
        assert review_data is not None

    def test_cqc_evidence_reject(self, authed, meeting_with_analysis):
        meeting_id, review_data = meeting_with_analysis
        if meeting_id is None:
            pytest.skip("No processed meeting")
        
        analysis = review_data.get("analysis", {})
        cqc_mappings = analysis.get("cqc_mappings", [])
        if not cqc_mappings:
            pytest.skip("No CQC mappings found")
        
        evidence_id = cqc_mappings[0].get("id")
        resp = authed.put(f"{BASE_URL}/api/review/{meeting_id}/evidence/{evidence_id}",
                          json={"status": "rejected"})
        assert resp.status_code == 200, f"CQC reject failed: {resp.text}"
        print(f"CQC reject passed: {resp.json()}")

    def test_cqc_evidence_accept(self, authed, meeting_with_analysis):
        meeting_id, review_data = meeting_with_analysis
        if meeting_id is None:
            pytest.skip("No processed meeting")
        
        analysis = review_data.get("analysis", {})
        cqc_mappings = analysis.get("cqc_mappings", [])
        if not cqc_mappings:
            pytest.skip("No CQC mappings found")
        
        evidence_id = cqc_mappings[0].get("id")
        resp = authed.put(f"{BASE_URL}/api/review/{meeting_id}/evidence/{evidence_id}",
                          json={"status": "accepted"})
        assert resp.status_code == 200, f"CQC accept failed: {resp.text}"
        print(f"CQC accept passed: {resp.json()}")

    def test_care_cert_evidence_reject(self, authed, meeting_with_analysis):
        meeting_id, review_data = meeting_with_analysis
        if meeting_id is None:
            pytest.skip("No processed meeting")
        
        analysis = review_data.get("analysis", {})
        care_cert_mappings = analysis.get("care_cert_mappings", [])
        if not care_cert_mappings:
            pytest.skip("No care_cert_mappings found")
        
        evidence_id = care_cert_mappings[0].get("id")
        resp = authed.put(f"{BASE_URL}/api/review/{meeting_id}/evidence/{evidence_id}",
                          json={"status": "rejected"})
        assert resp.status_code == 200, f"Care cert reject failed: {resp.text}"
        print(f"Care cert reject passed")

    def test_custom_evidence_reject(self, authed, meeting_with_analysis):
        """THE KEY FIX: custom_mappings now included in update loop"""
        meeting_id, review_data = meeting_with_analysis
        if meeting_id is None:
            pytest.skip("No processed meeting")
        
        analysis = review_data.get("analysis", {})
        custom_mappings = analysis.get("custom_mappings", [])
        if not custom_mappings:
            pytest.skip("No custom_mappings found - need a meeting with organisational standards")
        
        evidence_id = custom_mappings[0].get("id")
        resp = authed.put(f"{BASE_URL}/api/review/{meeting_id}/evidence/{evidence_id}",
                          json={"status": "rejected"})
        assert resp.status_code == 200, f"Custom reject failed: {resp.text}"
        
        # Verify status persisted by re-fetching review
        review_resp = authed.get(f"{BASE_URL}/api/review/{meeting_id}")
        assert review_resp.status_code == 200
        updated_analysis = review_resp.json().get("analysis", {})
        updated_custom = updated_analysis.get("custom_mappings", [])
        matching = [m for m in updated_custom if m.get("id") == evidence_id]
        assert matching, "Evidence not found after update"
        assert matching[0].get("status") == "rejected", f"Status not persisted: {matching[0].get('status')}"
        print(f"Custom reject persisted correctly!")

    def test_custom_evidence_accept(self, authed, meeting_with_analysis):
        meeting_id, review_data = meeting_with_analysis
        if meeting_id is None:
            pytest.skip("No processed meeting")
        
        analysis = review_data.get("analysis", {})
        custom_mappings = analysis.get("custom_mappings", [])
        if not custom_mappings:
            pytest.skip("No custom_mappings found")
        
        evidence_id = custom_mappings[0].get("id")
        resp = authed.put(f"{BASE_URL}/api/review/{meeting_id}/evidence/{evidence_id}",
                          json={"status": "accepted"})
        assert resp.status_code == 200, f"Custom accept failed: {resp.text}"
        
        review_resp = authed.get(f"{BASE_URL}/api/review/{meeting_id}")
        updated_custom = review_resp.json().get("analysis", {}).get("custom_mappings", [])
        matching = [m for m in updated_custom if m.get("id") == evidence_id]
        assert matching[0].get("status") == "accepted", f"Status not accepted: {matching[0]}"
        print("Custom accept persisted correctly!")

    def test_custom_evidence_flag(self, authed, meeting_with_analysis):
        meeting_id, review_data = meeting_with_analysis
        if meeting_id is None:
            pytest.skip("No processed meeting")
        
        analysis = review_data.get("analysis", {})
        custom_mappings = analysis.get("custom_mappings", [])
        if not custom_mappings:
            pytest.skip("No custom_mappings found")
        
        evidence_id = custom_mappings[0].get("id")
        resp = authed.put(f"{BASE_URL}/api/review/{meeting_id}/evidence/{evidence_id}",
                          json={"status": "flagged"})
        assert resp.status_code == 200, f"Custom flag failed: {resp.text}"
        print("Custom flag passed!")
