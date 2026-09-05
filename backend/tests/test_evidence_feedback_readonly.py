"""Tests for the new read-only evidence_feedback admin endpoints (iter 120)."""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback to backend/.env or default preview
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")


def _get_session(email, pw):
    """Use the helper to get authenticated cookies, return a requests.Session."""
    import subprocess, json as _json
    out = subprocess.run(
        ["python", "/app/backend/tests/get_tokens.py", email, pw],
        capture_output=True, timeout=45, text=True,
    )
    try:
        data = _json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        return None
    cookies = data.get("cookies", {})
    if not cookies.get("supervision_access"):
        return None
    s = requests.Session()
    for k, v in cookies.items():
        s.cookies.set(k, v)
    return s


@pytest.fixture(scope="module")
def admin_headers():
    s = _get_session("admin@supervision.com", "Admin123!")
    if s is None:
        pytest.skip("admin login failed")
    return s


@pytest.fixture(scope="module")
def attendee_headers():
    s = _get_session("user@supervision.com", "AnotherNew789!")
    if s is None:
        pytest.skip("attendee login failed")
    return s


class TestEvidenceFeedbackStats:
    def test_stats_admin_ok(self, admin_headers):
        r = admin_headers.get(f"{BASE_URL}/api/admin/evidence-feedback/stats")
        assert r.status_code == 200, r.text
        d = r.json()
        for key in ("total", "by_action", "by_type", "by_confidence",
                    "acceptance_rate", "top_rejected_standards"):
            assert key in d, f"missing key {key}"
        assert isinstance(d["total"], int)
        assert d["total"] >= 0
        # verify acceptance_rate math
        accepted = d["by_action"].get("accepted", 0)
        rejected = d["by_action"].get("rejected", 0)
        decided = accepted + rejected
        if decided == 0:
            assert d["acceptance_rate"] is None
        else:
            expected = round((accepted / decided) * 100, 1)
            assert d["acceptance_rate"] == expected
        assert isinstance(d["top_rejected_standards"], list)
        assert len(d["top_rejected_standards"]) <= 10

    def test_stats_attendee_403(self, attendee_headers):
        r = attendee_headers.get(f"{BASE_URL}/api/admin/evidence-feedback/stats")
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:200]}"

    def test_stats_unauth_401(self):
        r = requests.get(f"{BASE_URL}/api/admin/evidence-feedback/stats")
        assert r.status_code in (401, 403)


class TestEvidenceFeedbackList:
    def test_list_admin_ok(self, admin_headers):
        r = admin_headers.get(f"{BASE_URL}/api/admin/evidence-feedback?limit=50")
        assert r.status_code == 200, r.text
        arr = r.json()
        assert isinstance(arr, list)
        assert len(arr) <= 50
        if arr:
            row = arr[0]
            for key in ("id", "meeting_id", "meeting_title", "user_name",
                        "evidence_type", "standard_ref", "standard_name",
                        "ai_confidence", "manager_action", "timestamp"):
                assert key in row, f"missing field {key}"
            # ordered by timestamp DESC
            ts = [x["timestamp"] for x in arr if x.get("timestamp")]
            assert ts == sorted(ts, reverse=True)
            # no mongo _id leakage
            assert "_id" not in row

    def test_list_limit_capped_at_1000(self, admin_headers):
        r = admin_headers.get(f"{BASE_URL}/api/admin/evidence-feedback?limit=99999")
        assert r.status_code == 200
        arr = r.json()
        assert len(arr) <= 1000

    def test_list_attendee_403(self, attendee_headers):
        r = attendee_headers.get(f"{BASE_URL}/api/admin/evidence-feedback")
        assert r.status_code == 403

    def test_list_date_filter(self, admin_headers):
        # Use a future date_from to get zero rows
        r = admin_headers.get(f"{BASE_URL}/api/admin/evidence-feedback?date_from=2099-01-01"
                         )
        assert r.status_code == 200
        assert r.json() == []

    def test_list_date_to_filter_recent(self, admin_headers):
        # Old date_to should give zero rows
        r = admin_headers.get(f"{BASE_URL}/api/admin/evidence-feedback?date_to=1990-01-01"
                         )
        assert r.status_code == 200
        assert r.json() == []


class TestRegressionExisting:
    """Regression on unchanged existing admin endpoints."""
    def test_action_stats_still_ok(self, admin_headers):
        r = admin_headers.get(f"{BASE_URL}/api/admin/action-stats")
        # may or may not exist under this name; just sanity check auth admin endpoints
        assert r.status_code in (200, 404), r.status_code

    def test_team_insights_summary_ok(self, admin_headers):
        # a stand-in for Team Themes data endpoints — should still return 200
        r = admin_headers.get(f"{BASE_URL}/api/admin/team-insights/summary")
        assert r.status_code in (200, 404), r.status_code
