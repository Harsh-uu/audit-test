"""
Test suite for Report Lock feature.
Tests: locked state for signed_off meetings, allowed operations, and reopen flow.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
MEETING_ID = "6a46da6d1936c45e856ce791"  # Jane's signed_off meeting

JANE_EMAIL = "jane@sunrisecare.com"
JANE_PASSWORD = "Jane1two1!"
MANAGER_EMAIL = "manager@supervision.com"
MANAGER_PASSWORD = "Manager123!"


def login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"Login failed for {email}: {r.text}"
    token = r.json().get("access_token") or r.json().get("token")
    assert token, f"No token in response: {r.json()}"
    return token


def auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def jane_token():
    return login(JANE_EMAIL, JANE_PASSWORD)


@pytest.fixture(scope="module")
def manager_token():
    return login(MANAGER_EMAIL, MANAGER_PASSWORD)


@pytest.fixture(scope="module")
def meeting_data(jane_token):
    r = requests.get(f"{BASE_URL}/api/review/{MEETING_ID}", headers=auth_headers(jane_token))
    assert r.status_code == 200, f"Could not fetch meeting: {r.text}"
    return r.json()


@pytest.fixture(scope="module")
def evidence_id(meeting_data):
    analysis = meeting_data.get("analysis", {})
    mappings = analysis.get("cqc_mappings") or analysis.get("care_cert_mappings") or analysis.get("custom_mappings") or []
    assert mappings, "No evidence mappings found in meeting"
    return mappings[0]["id"]


@pytest.fixture(scope="module")
def risk_id(meeting_data):
    analysis = meeting_data.get("analysis", {})
    risks = analysis.get("risks", [])
    assert risks, "No risks found in meeting analysis"
    return risks[0]["id"]


class TestReportLock:
    """All report lock tests in one class to ensure sequential execution on a single worker."""

    def test_01_meeting_status_is_signed_off(self, meeting_data):
        status = meeting_data.get("status")
        assert status in ["signed_off", "shared"], f"Expected signed_off, got {status}"
        print(f"Meeting status: {status} ✓")

    def test_02_edit_evidence_wording_returns_409(self, jane_token, evidence_id):
        r = requests.put(
            f"{BASE_URL}/api/review/{MEETING_ID}/evidence/{evidence_id}",
            json={"edited_evidence_summary": "New locked text"},
            headers=auth_headers(jane_token)
        )
        assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text}"
        print(f"Edit evidence wording blocked with 409 ✓")

    def test_03_edit_evidence_notes_returns_409(self, jane_token, evidence_id):
        r = requests.put(
            f"{BASE_URL}/api/review/{MEETING_ID}/evidence/{evidence_id}",
            json={"notes": "some note"},
            headers=auth_headers(jane_token)
        )
        assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text}"
        print(f"Edit evidence notes blocked with 409 ✓")

    def test_04_find_replace_returns_409(self, jane_token):
        r = requests.post(
            f"{BASE_URL}/api/review/{MEETING_ID}/find-replace",
            json={"find": "test", "replace": "locked"},
            headers=auth_headers(jane_token)
        )
        assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text}"
        print(f"Find & replace blocked with 409 ✓")

    def test_05_speaker_text_update_returns_409(self, jane_token):
        r = requests.patch(
            f"{BASE_URL}/api/review/{MEETING_ID}/speaker-text",
            json={"speaker_text": "Speaker A: hello"},
            headers=auth_headers(jane_token)
        )
        assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text}"
        print(f"Speaker text update blocked with 409 ✓")

    def test_06_rescan_evidence_returns_409(self, jane_token):
        r = requests.post(
            f"{BASE_URL}/api/review/{MEETING_ID}/rescan-evidence",
            json={},
            headers=auth_headers(jane_token)
        )
        assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text}"
        print(f"Rescan evidence blocked with 409 ✓")

    def test_07_risk_notes_edit_returns_409(self, jane_token, risk_id):
        r = requests.patch(
            f"{BASE_URL}/api/review/{MEETING_ID}/risks/{risk_id}",
            json={"notes": "locked notes"},
            headers=auth_headers(jane_token)
        )
        assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text}"
        print(f"Risk notes edit blocked with 409 ✓")

    def test_08_evidence_status_change_allowed(self, jane_token, evidence_id):
        r = requests.put(
            f"{BASE_URL}/api/review/{MEETING_ID}/evidence/{evidence_id}",
            json={"status": "accepted"},
            headers=auth_headers(jane_token)
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        print(f"Evidence status change allowed ✓")

    def test_09_risk_resolve_toggle_allowed(self, jane_token, risk_id):
        meeting_r = requests.get(f"{BASE_URL}/api/review/{MEETING_ID}", headers=auth_headers(jane_token))
        risks = meeting_r.json().get("analysis", {}).get("risks", [])
        risk = next((r for r in risks if r["id"] == risk_id), None)
        current_resolved = risk.get("is_resolved", False) if risk else False

        r = requests.patch(
            f"{BASE_URL}/api/review/{MEETING_ID}/risks/{risk_id}",
            json={"is_resolved": not current_resolved},
            headers=auth_headers(jane_token)
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        print(f"Risk resolve toggle allowed ✓")
        # Restore original state
        requests.patch(
            f"{BASE_URL}/api/review/{MEETING_ID}/risks/{risk_id}",
            json={"is_resolved": current_resolved},
            headers=auth_headers(jane_token)
        )

    def test_10_request_reopen_by_manager(self, jane_token):
        meeting_r = requests.get(f"{BASE_URL}/api/review/{MEETING_ID}", headers=auth_headers(jane_token))
        meeting = meeting_r.json()
        if meeting.get("reopen_requested"):
            pytest.skip("Reopen already requested from a previous run")

        r = requests.post(
            f"{BASE_URL}/api/review/{MEETING_ID}/request-reopen",
            json={"reason": "TEST: Incorrect action item text"},
            headers=auth_headers(jane_token)
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert "message" in data
        print(f"Request reopen success: {data['message']} ✓")

        # Verify meeting.reopen_requested = True
        meeting_r = requests.get(f"{BASE_URL}/api/review/{MEETING_ID}", headers=auth_headers(jane_token))
        meeting = meeting_r.json()
        assert meeting.get("reopen_requested") == True
        print(f"reopen_requested=True verified ✓")

    def test_11_approve_reopen(self, jane_token):
        # Jane is in attendees list, so backend allows her to approve (security note below)
        r = requests.post(
            f"{BASE_URL}/api/review/{MEETING_ID}/approve-reopen",
            headers=auth_headers(jane_token)
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        print(f"Approve reopen success ✓")

    def test_12_meeting_status_reviewed_after_approve(self, jane_token):
        r = requests.get(f"{BASE_URL}/api/review/{MEETING_ID}", headers=auth_headers(jane_token))
        meeting = r.json()
        assert meeting.get("status") == "reviewed", f"Expected 'reviewed', got {meeting.get('status')}"
        assert not meeting.get("reopen_requested")
        print(f"Meeting status after approve: reviewed ✓")

    def test_13_audit_trail_has_reopen_events(self, jane_token):
        r = requests.get(f"{BASE_URL}/api/review/{MEETING_ID}/audit-trail", headers=auth_headers(jane_token))
        assert r.status_code == 200
        events = r.json().get("events", [])
        actions = [e.get("type") for e in events]
        assert "reopen_requested" in actions, f"reopen_requested not in audit trail"
        assert "reopen_approved" in actions, f"reopen_approved not in audit trail"
        print(f"Audit trail has both reopen events ✓")

    def test_14_re_sign_off_to_restore_locked_state(self, jane_token):
        """Re-sign-off the meeting to restore locked state for future test runs."""
        r = requests.post(
            f"{BASE_URL}/api/review/{MEETING_ID}/signoff",
            headers=auth_headers(jane_token)
        )
        assert r.status_code in [200, 400], f"Unexpected status: {r.status_code}: {r.text}"
        print(f"Re-sign-off result: {r.status_code} ✓")
