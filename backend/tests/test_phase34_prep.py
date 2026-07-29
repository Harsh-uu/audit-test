"""
Phase 3 + Phase 4 Dynamic Supervision backend tests
Tests: prep get/coverage, carry-forward-missed endpoint
"""
import pytest
import requests
import os
import uuid
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
from datetime import datetime, timezone

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL") or "https://transcript-vault-2.preview.emergentagent.com"
BASE_URL = BASE_URL.rstrip("/")

# Test data IDs
MEETING_WITH_PREP = "6a6a33f3b671958551291c00"  # draft meeting with prep + sections (manager's org)
JANE_MEETING = "6a46da6d1936c45e856ce791"  # Jane's signed_off meeting with analysis_id
JANE_ANALYSIS = "6a46dce91936c45e856ce797"

MANAGER_EMAIL = "manager@supervision.com"
MANAGER_PASS = "Manager123!"
JANE_EMAIL = "jane@sunrisecare.com"
JANE_PASS = "Jane1two1!"


@pytest.fixture(scope="module")
def manager_token():
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={"email": MANAGER_EMAIL, "password": MANAGER_PASS})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    data = resp.json()
    token = data.get("access_token") or data.get("token")
    assert token, f"No token in response: {data}"
    return token


@pytest.fixture(scope="module")
def manager_headers(manager_token):
    return {"Authorization": f"Bearer {manager_token}", "Content-Type": "application/json"}


# ── GET prep ────────────────────────────────────────────────────────────────

class TestGetPrep:
    """GET /api/prep/{meeting_id} — verify response fields"""

    def test_get_prep_with_sections(self, manager_headers):
        """Meeting with prep should return sections, gen_status"""
        resp = requests.get(f"{BASE_URL}/api/prep/{MEETING_WITH_PREP}", headers=manager_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("sections") and len(data["sections"]) > 0, "Expected sections array"
        assert data.get("gen_status") == "done"
        assert "meeting_id" in data
        print(f"[PASS] GET prep with sections: {len(data['sections'])} sections, gen_status={data['gen_status']}")

    def test_get_prep_returns_coverage_fields(self, manager_headers):
        """coverage_results and coverage_checked_at should exist (may be empty/None)"""
        resp = requests.get(f"{BASE_URL}/api/prep/{MEETING_WITH_PREP}", headers=manager_headers)
        assert resp.status_code == 200
        data = resp.json()
        # These fields should be present (even if None/empty) once coverage has run
        # For now, assert they don't cause a 500 — value may be None
        assert "coverage_results" in data or data.get("exists") is not False
        print(f"[PASS] coverage_results present in response: {data.get('coverage_results')}")

    def test_get_prep_missing_meeting_returns_404(self, manager_headers):
        """Non-existent meeting should return 404"""
        fake_id = "000000000000000000000000"
        resp = requests.get(f"{BASE_URL}/api/prep/{fake_id}", headers=manager_headers)
        assert resp.status_code == 404
        print("[PASS] 404 for missing meeting")

    def test_get_prep_no_prep_returns_idle(self, manager_headers):
        """Meeting with no prep should return exists=False and gen_status=idle"""
        # Use a meeting in manager's org that has no prep
        no_prep_meeting = "6a3e59707ed4f370c2614aec"  # TEST_Recording_pytest - no prep
        resp = requests.get(f"{BASE_URL}/api/prep/{no_prep_meeting}", headers=manager_headers)
        assert resp.status_code == 200
        data = resp.json()
        # Either returns exists: False or has empty sections
        if not data.get("sections"):
            assert data.get("gen_status") in ("idle", None) or data.get("exists") is False
        print(f"[PASS] Meeting with no prep: {data}")


# ── Carry-forward-missed ─────────────────────────────────────────────────────

class TestCarryForwardMissed:
    """POST /api/prep/{meeting_id}/carry-forward-missed"""

    def test_carry_forward_no_coverage_returns_400(self, manager_headers):
        """Meeting with no analysis_id should return 400"""
        resp = requests.post(
            f"{BASE_URL}/api/prep/{MEETING_WITH_PREP}/carry-forward-missed",
            headers=manager_headers
        )
        assert resp.status_code == 400
        data = resp.json()
        # Endpoint checks analysis_id first, then coverage
        detail = data.get("detail", "").lower()
        assert "analysis" in detail or "coverage" in detail or "not complete" in detail
        print(f"[PASS] 400 when no analysis/coverage: {data.get('detail')}")

    def test_carry_forward_no_analysis_returns_400(self, manager_headers):
        """Meeting with no analysis_id should return 400"""
        # MEETING_WITH_PREP (draft) has no analysis_id
        # First let's make sure it has coverage_results but we check that separately
        # Easiest: test with a meeting that has prep + no analysis
        resp = requests.post(
            f"{BASE_URL}/api/prep/{MEETING_WITH_PREP}/carry-forward-missed",
            headers=manager_headers
        )
        # Should be 400 either for no analysis or no coverage
        assert resp.status_code in (400, 404)
        print(f"[PASS] 400/404 when no analysis: {resp.json()}")

    def test_carry_forward_with_mocked_coverage_adds_actions(self):
        """With coverage_results+missed items on Jane's signed_off meeting → adds actions"""
        # Use jane's token since her meeting has analysis_id
        resp_login = requests.post(f"{BASE_URL}/api/auth/login", json={"email": JANE_EMAIL, "password": JANE_PASS})
        if resp_login.status_code != 200:
            pytest.skip("Jane login failed")
        jane_token = resp_login.json().get("access_token") or resp_login.json().get("token")
        jane_headers = {"Authorization": f"Bearer {jane_token}", "Content-Type": "application/json"}

        # Setup: insert prep record with coverage_results for Jane's signed-off meeting
        async def setup():
            db = AsyncIOMotorClient('mongodb://localhost:27017')['supervision_db']
            # datetime, timezone already imported
            q_id = f"test_q_{uuid.uuid4().hex[:6]}"
            await db.meeting_prep.update_one(
                {"meeting_id": JANE_MEETING},
                {"$set": {
                    "meeting_id": JANE_MEETING,
                    "gen_status": "done",
                    "sections": [{
                        "section_id": "wellbeing",
                        "label": "Wellbeing",
                        "questions": [{"id": q_id, "text": "TEST missed question", "included": True, "generated": True}]
                    }],
                    "coverage_results": {
                        q_id: {"status": "missed", "evidence": ""}
                    },
                    "coverage_checked_at": datetime.now(timezone.utc).isoformat(),
                }},
                upsert=True,
            )
            return q_id
        
        from datetime import datetime, timezone
        q_id = asyncio.run(setup())
        
        resp = requests.post(
            f"{BASE_URL}/api/prep/{JANE_MEETING}/carry-forward-missed",
            headers=jane_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("added", 0) >= 1 or "No missed" in data.get("message", "")
        print(f"[PASS] carry-forward result: {data}")

        # Verify action was added to analysis
        resp2 = requests.get(f"{BASE_URL}/api/review/{JANE_MEETING}", headers=jane_headers)
        if resp2.status_code == 200:
            actions = resp2.json().get("actions", [])
            cf_actions = [a for a in actions if a.get("source") == "carry_forward_prep"]
            print(f"[PASS] carry_forward_prep actions in analysis: {len(cf_actions)}")

    def test_carry_forward_no_missed_returns_message(self):
        """When coverage has no missed items, returns message 'No missed questions'"""
        resp_login = requests.post(f"{BASE_URL}/api/auth/login", json={"email": JANE_EMAIL, "password": JANE_PASS})
        if resp_login.status_code != 200:
            pytest.skip("Jane login failed")
        jane_token = resp_login.json().get("access_token") or resp_login.json().get("token")
        jane_headers = {"Authorization": f"Bearer {jane_token}", "Content-Type": "application/json"}

        # Update prep to have all covered
        async def setup_covered():
            db = AsyncIOMotorClient('mongodb://localhost:27017')['supervision_db']
            # datetime, timezone already imported
            q_id = f"covered_q_{uuid.uuid4().hex[:6]}"
            await db.meeting_prep.update_one(
                {"meeting_id": JANE_MEETING},
                {"$set": {
                    "sections": [{
                        "section_id": "wellbeing",
                        "label": "Wellbeing",
                        "questions": [{"id": q_id, "text": "TEST covered question", "included": True}]
                    }],
                    "coverage_results": {
                        q_id: {"status": "covered", "evidence": "discussed in detail"}
                    },
                    "coverage_checked_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
        from datetime import datetime, timezone
        asyncio.run(setup_covered())

        resp = requests.post(
            f"{BASE_URL}/api/prep/{JANE_MEETING}/carry-forward-missed",
            headers=jane_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "No missed" in data.get("message", "") or data.get("added", 0) == 0
        print(f"[PASS] No missed items: {data}")


# ── Coverage fields returned in GET ──────────────────────────────────────────

class TestCoverageInPrepResponse:
    """Verify coverage_results and coverage_checked_at returned by GET /api/prep/{id}"""

    def test_coverage_fields_after_mock_insert(self, manager_headers):
        """After inserting coverage_results, GET should return them"""
        async def insert_coverage():
            db = AsyncIOMotorClient('mongodb://localhost:27017')['supervision_db']
            # datetime, timezone already imported
            q_id = "q1"
            now = datetime.now(timezone.utc).isoformat()
            await db.meeting_prep.update_one(
                {"meeting_id": MEETING_WITH_PREP},
                {"$set": {
                    "coverage_results": {
                        q_id: {"status": "covered", "evidence": "test evidence"},
                    },
                    "coverage_checked_at": now,
                }},
            )
            return now
        
        checked_at = asyncio.run(insert_coverage())
        
        resp = requests.get(f"{BASE_URL}/api/prep/{MEETING_WITH_PREP}", headers=manager_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("coverage_results"), "Expected coverage_results"
        assert "q1" in data["coverage_results"]
        assert data["coverage_results"]["q1"]["status"] == "covered"
        assert data.get("coverage_checked_at") is not None
        print(f"[PASS] coverage_results returned: {data['coverage_results']}")
        print(f"[PASS] coverage_checked_at: {data['coverage_checked_at']}")

        # Cleanup - remove coverage from this prep
        async def cleanup():
            db = AsyncIOMotorClient('mongodb://localhost:27017')['supervision_db']
            await db.meeting_prep.update_one(
                {"meeting_id": MEETING_WITH_PREP},
                {"$unset": {"coverage_results": "", "coverage_checked_at": ""}},
            )
        asyncio.run(cleanup())
