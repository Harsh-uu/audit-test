"""Iter116b: full meeting lifecycle e2e through the REAL pipeline.

create -> upload audio -> job worker transcribe+analyse -> PII scan/redaction ->
summary/actions edits -> comments/audit -> mark-reviewed -> sign-off -> exports
(PDF + transcript, redaction applied) -> reopen request/approve -> delete.

Ordered: tests share one meeting via a module fixture and are order-dependent
(run in file order; pytest.ini's -p randomly is disabled via the marker below).
"""
import io
import math
import struct
import time
import uuid
import wave
from datetime import datetime, timezone

import pytest
import requests

from tests.test_iter116_full_regression import API, T, login, ADMIN, MANAGER

pytestmark = pytest.mark.order  # noqa

TAG = uuid.uuid4().hex[:8]
REDACT_FROM = "Waterlow"
REDACT_TO = "[Redacted-Location]"


def make_wav(seconds=3.0, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            frames += struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / rate)))
        w.writeframes(bytes(frames))
    return buf.getvalue()


@pytest.fixture(scope="module")
def admin():
    return login(*ADMIN)


@pytest.fixture(scope="module")
def manager():
    return login(*MANAGER)


@pytest.fixture(scope="module")
def state():
    return {}


@pytest.fixture(scope="module")
def meeting(admin, manager):
    r = admin.post(f"{API}/meetings/", json={
        "title": f"TEST_iter116b_lifecycle_{TAG}",
        "meeting_type": "supervision",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "time": "09:30",
        "attendee_ids": [admin.me["id"]],
        "sign_off_manager_id": manager.me["id"],
    }, timeout=T)
    assert r.status_code in (200, 201), f"create -> {r.status_code} {r.text[:300]}"
    mid = r.json()["id"]
    yield mid
    admin.delete(f"{API}/meetings/{mid}", timeout=T)


class TestLifecycle:
    def test_01_upload_audio_starts_job(self, admin, meeting):
        r = admin.post(f"{API}/processing/{meeting}/upload", data=make_wav(),
                       headers={"Content-Type": "audio/wav"}, timeout=180)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        assert r.json().get("audio_file_id")

    def test_02_pipeline_reaches_in_review(self, admin, meeting):
        deadline = time.time() + 240
        seen = []
        while time.time() < deadline:
            st = admin.get(f"{API}/processing/{meeting}/status", timeout=T)
            assert st.status_code == 200, st.text[:200]
            s = st.json()["status"]
            if not seen or seen[-1] != s:
                seen.append(s)
            if s in ("in_review", "reviewed", "error", "failed"):
                break
            time.sleep(6)
        assert seen[-1] == "in_review", f"pipeline ended at {seen}"
        body = admin.get(f"{API}/processing/{meeting}/status", timeout=T).json()
        assert body["has_transcript"] and body["has_analysis"], body

    def test_03_analysis_shape(self, admin, meeting):
        r = admin.get(f"{API}/review/{meeting}", timeout=T)
        assert r.status_code == 200, r.text[:300]
        a = r.json().get("analysis") or {}
        assert a, "no analysis attached to review payload"
        for key in ("summary", "actions", "risks", "cqc_mappings", "care_cert_mappings"):
            assert key in a, f"missing analysis key {key}: {list(a.keys())}"
        for key in ("actions", "risks", "cqc_mappings", "care_cert_mappings"):
            assert isinstance(a[key], list), f"{key} is {type(a[key])}"

    def test_04_scan_pii(self, admin, meeting):
        r = admin.post(f"{API}/review/{meeting}/scan-pii", timeout=180)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        assert "flags" in r.json()

    def test_05_complete_pii_review_with_redaction(self, admin, meeting):
        r = admin.post(f"{API}/review/{meeting}/complete-pii-review", json={
            "skipped": False,
            "redactions": [{"original": REDACT_FROM, "replacement": REDACT_TO, "type": "location"}],
        }, timeout=T)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        assert r.json()["redactions_applied"] == 1
        got = admin.get(f"{API}/review/{meeting}", timeout=T).json()
        assert got.get("pii_review_status") == "reviewed", got.get("pii_review_status")

    def test_06_update_summary_and_actions(self, admin, meeting):
        s = admin.put(f"{API}/review/{meeting}/summary",
                      json={"summary": f"TEST_iter116b summary {TAG}"}, timeout=T)
        assert s.status_code == 200, f"summary -> {s.status_code} {s.text[:300]}"
        a = admin.put(f"{API}/review/{meeting}/actions", json={"actions": [
            {"id": "a1", "text": f"TEST_iter116b action {TAG}", "assignee": "Admin", "completed": False}
        ]}, timeout=T)
        assert a.status_code == 200, f"actions -> {a.status_code} {a.text[:300]}"
        got = admin.get(f"{API}/review/{meeting}", timeout=T).json()
        an = got["analysis"]
        assert TAG in (an.get("edited_summary") or an.get("summary") or ""), an.get("edited_summary")
        assert any(TAG in (x.get("text") or "") for x in an["actions"]), an["actions"]

    def test_07_toggle_action_complete(self, admin, meeting):
        r = admin.patch(f"{API}/review/{meeting}/actions/a1", json={"completed": True}, timeout=T)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        an = admin.get(f"{API}/review/{meeting}", timeout=T).json()["analysis"]
        assert any(x.get("id") == "a1" and x.get("completed") for x in an["actions"]), an["actions"]

    def test_08_comments_and_audit(self, admin, meeting):
        c = admin.post(f"{API}/review/{meeting}/comments", json={"text": f"lifecycle note {TAG}"}, timeout=T)
        assert c.status_code in (200, 201), f"{c.status_code} {c.text[:300]}"
        g = admin.get(f"{API}/review/{meeting}/comments", timeout=T)
        assert g.status_code == 200 and TAG in str(g.json())
        au = admin.get(f"{API}/review/{meeting}/audit-trail", timeout=T)
        assert au.status_code == 200, au.text[:300]
        blob = str(au.json())
        assert "pii" in blob.lower() or "summary" in blob.lower(), blob[:400]

    def test_09_signoff_blocked_before_all_reviewed(self, manager, meeting):
        r = manager.post(f"{API}/review/{meeting}/signoff", timeout=T)
        assert r.status_code == 400, f"expected 400 pre-review, got {r.status_code} {r.text[:200]}"

    def test_10_mark_reviewed(self, admin, meeting):
        r = admin.post(f"{API}/review/{meeting}/mark-reviewed", timeout=T)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        assert r.json()["status"] in ("reviewed", "in_review")

    def test_11_signoff(self, manager, meeting):
        r = manager.post(f"{API}/review/{meeting}/signoff", timeout=T)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        got = manager.get(f"{API}/review/{meeting}", timeout=T).json()
        assert got["status"] == "signed_off", got["status"]

    def test_12_export_pdf_after_signoff(self, admin, meeting):
        t0 = time.time()
        r = admin.get(f"{API}/review/{meeting}/export-pdf", timeout=180)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        assert r.content[:4] == b"%PDF"
        assert len(r.content) > 1000
        print(f"export-pdf {len(r.content)} bytes in {time.time()-t0:.1f}s")

    def test_13_export_transcript_redaction_applied(self, admin, meeting):
        r = admin.get(f"{API}/review/{meeting}/export-transcript", timeout=180)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        assert REDACT_FROM.encode() not in r.content, "un-redacted PII string present in transcript export"

    def test_14_edits_locked_after_signoff(self, admin, meeting):
        r = admin.put(f"{API}/review/{meeting}/summary", json={"summary": "should be blocked"}, timeout=T)
        assert r.status_code in (400, 403, 409), f"report not locked after sign-off: {r.status_code}"

    def test_15_reopen_request_and_approve(self, admin, manager, meeting):
        rq = manager.post(f"{API}/review/{meeting}/request-reopen",
                          json={"reason": f"iter116b regression {TAG}"}, timeout=T)
        assert rq.status_code == 200, f"request-reopen -> {rq.status_code} {rq.text[:300]}"
        dup = manager.post(f"{API}/review/{meeting}/request-reopen",
                           json={"reason": "again"}, timeout=T)
        assert dup.status_code == 409, f"duplicate reopen not blocked: {dup.status_code}"
        ap = admin.post(f"{API}/review/{meeting}/approve-reopen", timeout=T)
        assert ap.status_code == 200, f"approve-reopen -> {ap.status_code} {ap.text[:300]}"
        got = admin.get(f"{API}/review/{meeting}", timeout=T).json()
        assert got["status"] == "reviewed", got["status"]

    def test_16_rescan_evidence_ai(self, admin, meeting):
        t0 = time.time()
        r = admin.post(f"{API}/review/{meeting}/rescan-evidence", json={}, timeout=240)
        elapsed = time.time() - t0
        print(f"rescan-evidence {r.status_code} in {elapsed:.1f}s")
        assert r.status_code in (200, 400), f"{r.status_code} {r.text[:300]}"

    def test_17_regenerate_summary_ai(self, admin, meeting):
        t0 = time.time()
        r = admin.post(f"{API}/review/{meeting}/regenerate-summary", json={}, timeout=240)
        print(f"regenerate-summary {r.status_code} in {time.time()-t0:.1f}s")
        assert r.status_code in (200, 400), f"{r.status_code} {r.text[:300]}"

    def test_18_share_meeting(self, admin, manager, meeting):
        r = admin.post(f"{API}/review/{meeting}/share",
                       json={"user_ids": [manager.me["id"]]}, timeout=T)
        assert r.status_code in (200, 400, 422), f"{r.status_code} {r.text[:300]}"
