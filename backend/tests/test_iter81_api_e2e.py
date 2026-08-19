"""
Iteration 81 — API-level end-to-end verification that meeting analysis (now routed
through Vertex AI Gemini 2.5 Flash with OpenAI fallback) still completes for a
real user via the HTTP API.

Flows covered:
  POST /api/review/{id}/rescan-evidence   (full re-analysis -> analyze_meeting)
  GET  /api/review/{id}                   (analysis JSON structure after rescan)
  POST /api/review/{id}/regenerate-summary (generate_meeting_summary)
"""
import sys
import time

import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend/tests")
from _iter79_login import login  # noqa: E402

BASE = dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"


@pytest.fixture(scope="module")
def admin():
    return login("admin@supervision.com", "Admin123!")


@pytest.fixture(scope="module")
def meeting_id(admin):
    r = admin.get(f"{BASE}/meetings/", timeout=60)
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    payload = r.json()
    meetings = payload if isinstance(payload, list) else payload.get("meetings", [])
    for m in meetings:
        if m.get("status") in ("signed_off", "scheduled", "analyzing"):
            continue  # rescan is blocked after sign-off / before analysis exists
        mid = m.get("id")
        rv = admin.get(f"{BASE}/review/{mid}", timeout=60)
        if rv.status_code != 200:
            continue
        data = rv.json()
        if (data.get("transcript") or {}).get("speaker_text") or (data.get("transcript") or {}).get("text"):
            return mid
    pytest.fail("No meeting with a transcript found for admin@supervision.com")


class TestAnalysisEndToEndViaApi:
    def test_health(self):
        r = requests.get(f"{BASE}/health", timeout=30)
        assert r.status_code in (200, 404), f"unexpected {r.status_code}"

    def test_rescan_evidence_completes(self, admin, meeting_id):
        r = admin.post(f"{BASE}/review/{meeting_id}/rescan-evidence", json={}, timeout=120)
        assert r.status_code == 200, f"rescan failed {r.status_code} {r.text[:400]}"
        assert r.json().get("status") == "processing"

        status = None
        deadline = time.time() + 420
        while time.time() < deadline:
            time.sleep(10)
            rv = admin.get(f"{BASE}/review/{meeting_id}", timeout=60)
            assert rv.status_code == 200, f"{rv.status_code} {rv.text[:300]}"
            status = (rv.json().get("meeting") or rv.json()).get("rescan_status")
            if status in (None, "", "complete", "completed", "done", "failed", "error"):
                break
        assert status not in ("failed", "error"), f"rescan ended with status={status}"
        assert status != "processing", "rescan did not finish within 7 minutes"

    def test_analysis_payload_valid_after_rescan(self, admin, meeting_id):
        rv = admin.get(f"{BASE}/review/{meeting_id}", timeout=60)
        assert rv.status_code == 200
        data = rv.json()
        analysis = data.get("analysis") or data
        assert analysis.get("summary"), "no summary in analysis"
        assert "could not be parsed" not in analysis["summary"], \
            "analysis JSON parse failed end-to-end"
        for key in ("actions", "risks", "cqc_mappings", "care_cert_mappings"):
            assert key in analysis, f"missing {key}"
            assert isinstance(analysis[key], list), f"{key} not a list"
        for r_item in analysis["risks"]:
            assert r_item.get("text")
            assert r_item.get("severity") in ("high", "medium", "low"), r_item

    def test_regenerate_summary(self, admin, meeting_id):
        r = admin.post(f"{BASE}/review/{meeting_id}/regenerate-summary", json={}, timeout=300)
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        summary = r.json().get("summary", "")
        assert len(summary) > 80, f"summary too short: {summary!r}"
        assert "pastoral" not in summary.lower()
        assert "caseload" not in summary.lower()

    def test_export_pdf_regression(self, admin):
        """PDF export only allowed for signed-off meetings — use one of those."""
        r = admin.get(f"{BASE}/meetings/", timeout=60)
        payload = r.json()
        meetings = payload if isinstance(payload, list) else payload.get("meetings", [])
        signed = [m["id"] for m in meetings if m.get("status") == "signed_off"]
        assert signed, "no signed-off meeting available for PDF export regression"
        r = admin.get(f"{BASE}/review/{signed[0]}/export-pdf", timeout=180)
        assert r.status_code == 200, f"pdf export {r.status_code} {r.text[:200]}"
        assert r.content[:4] == b"%PDF", "response is not a PDF"


class TestRbacRegression:
    def test_staff_cannot_access_admin_users(self):
        s = login("user@supervision.com", "Staff123!")
        r = s.get(f"{BASE}/admin/users", timeout=60)
        assert r.status_code == 403, f"expected 403 for attendee, got {r.status_code}"
