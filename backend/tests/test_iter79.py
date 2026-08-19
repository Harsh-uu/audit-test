"""Iteration 79 regression suite.

Covers:
  * utils/ai._apply_uk_language safeguarding terminology safety-net
  * PDF export: UK date formatting, Done column, incomplete cross, transcript speaker labels
  * Audit trail logging of pdf_exported / transcript_exported
  * Actions add/remove persistence (optimistic UI backing API)
  * Backend RBAC for meeting delete + org rename (admin-only intent)
"""
import io
import sys

import pytest
import requests
from pypdf import PdfReader

sys.path.insert(0, "/app/backend/tests")
from _iter79_login import login, BASE  # noqa: E402

ADMIN = ("admin@supervision.com", "Admin123!")
MANAGER = ("manager@supervision.com", "Manager123!")
SIGNED_MEETING = "0f38f385-7c85-428e-923c-d7c365659192"  # signed_off + transcript


@pytest.fixture(scope="module")
def admin():
    return login(*ADMIN)


@pytest.fixture(scope="module")
def manager():
    return login(*MANAGER)


# ---------------- utils/ai UK language safety net ----------------
class TestSafeguardingTerminology:
    @pytest.mark.parametrize("src,expected", [
        ("Potential safeguarding indicator - resident fell", "Potential safeguarding - resident fell"),
        ("Potential safeguarding breach - no DBS check", "Potential safeguarding - no DBS check"),
        ("potential safeguarding concern - medication error", "Potential safeguarding - medication error"),
        ("Potential safeguarding indicators - repeated", "Potential safeguarding - repeated"),
    ])
    def test_rewrites(self, src, expected):
        sys.path.insert(0, "/app/backend")
        from utils.ai import _apply_uk_language
        assert _apply_uk_language(src) == expected

    def test_plain_safeguarding_untouched(self):
        sys.path.insert(0, "/app/backend")
        from utils.ai import _apply_uk_language
        assert _apply_uk_language("Safeguarding concern raised") == "Safeguarding concern raised"

    def test_risk_template_uses_new_phrasing(self):
        src = open("/app/backend/utils/ai.py", encoding="utf-8").read()
        assert "Potential safeguarding indicator" not in src
        assert "Potential safeguarding breach" not in src


# ---------------- PDF export ----------------
@pytest.fixture(scope="module")
def report_pdf(admin):
    r = admin.get(f"{BASE}/review/{SIGNED_MEETING}/export-pdf", timeout=180)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    assert r.headers.get("content-type", "").startswith("application/pdf")
    return r.content


@pytest.fixture(scope="module")
def report_text(report_pdf):
    reader = PdfReader(io.BytesIO(report_pdf))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


class TestReportPdf:
    def test_meta_dates_uk_formatted(self, report_text):
        import re
        assert re.search(r"\b\d{2}/\d{2}/\d{4}\b", report_text), "no DD/MM/YYYY date in PDF"
        # no raw ISO datetime strings like 2026-08-19T11:08
        iso = re.findall(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", report_text)
        assert not iso, f"raw ISO datetimes leaked into PDF: {iso[:5]}"

    def test_signed_at_has_time(self, report_text):
        import re
        assert re.search(r"\b\d{2}/\d{2}/\d{4} \d{2}:\d{2}\b", report_text), "Signed at missing DD/MM/YYYY HH:MM"

    def test_done_column_header_present(self, report_text):
        assert "Done" in report_text, "Done column header missing/broken"

    def test_transcript_speaker_labels_not_timestamps(self, report_text):
        import re
        # label boxes are rendered uppercase; a regression shows '[00' as the label
        bad = re.findall(r"^\[\d+\s*$", report_text, re.M)
        assert not bad, f"truncated timestamp used as speaker label: {bad[:5]}"

    def test_transcript_timestamp_prefix_in_message(self, report_text):
        import re
        if "[" not in report_text:
            pytest.skip("transcript has no timestamps")
        # timestamps should be complete e.g. [00:02]
        partial = re.findall(r"\[\d{1,2}(?![\d:\]])", report_text)
        assert not partial, f"partial timestamp fragments found: {partial[:5]}"


@pytest.fixture(scope="module")
def transcript_text(admin):
    r = admin.get(f"{BASE}/review/{SIGNED_MEETING}/export-transcript", timeout=180)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    reader = PdfReader(io.BytesIO(r.content))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


class TestTranscriptPdf:
    def test_speaker_labels_not_timestamps(self, transcript_text):
        import re
        bad = re.findall(r"^\[\d+\s*$", transcript_text, re.M)
        assert not bad, f"truncated timestamp used as speaker label: {bad[:5]}"

    def test_has_content(self, transcript_text):
        assert len(transcript_text.strip()) > 50


# ---------------- audit trail export logging ----------------
class TestAuditExportLogging:
    def _actions(self, s, mid):
        r = s.get(f"{BASE}/review/{mid}/audit-trail", timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        data = r.json()
        events = data.get("events", data if isinstance(data, list) else [])
        return [e.get("type") for e in events], events

    def test_pdf_export_logged(self, admin):
        before, _ = self._actions(admin, SIGNED_MEETING)
        n_before = before.count("pdf_exported")
        r = admin.get(f"{BASE}/review/{SIGNED_MEETING}/export-pdf", timeout=180)
        assert r.status_code == 200
        after, events = self._actions(admin, SIGNED_MEETING)
        assert after.count("pdf_exported") == n_before + 1, "pdf_exported not logged"
        lbl = [e for e in events if e.get("type") == "pdf_exported"][0]
        assert "PDF exported" in (lbl.get("label") or lbl.get("action_label") or ""), lbl

    def test_transcript_export_logged(self, admin):
        before, _ = self._actions(admin, SIGNED_MEETING)
        n_before = before.count("transcript_exported")
        r = admin.get(f"{BASE}/review/{SIGNED_MEETING}/export-transcript", timeout=180)
        assert r.status_code == 200
        after, events = self._actions(admin, SIGNED_MEETING)
        assert after.count("transcript_exported") == n_before + 1, "transcript_exported not logged"
        lbl = [e for e in events if e.get("type") == "transcript_exported"][0]
        assert "Transcript PDF exported" in (lbl.get("label") or lbl.get("action_label") or ""), lbl


# ---------------- actions add/remove persistence ----------------
IN_REVIEW_MEETING = "2f1cc088-0687-48b9-9f40-1dabb5285640"


class TestActionsPersistence:
    def test_add_then_remove_action(self, manager):
        r = manager.get(f"{BASE}/review/{IN_REVIEW_MEETING}", timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        analysis = r.json().get("analysis") or {}
        original = analysis.get("actions") or []
        new_item = {"id": "action_manual_TEST_iter79", "text": "TEST_ iter79 action from risk",
                    "assigned_to": "QA Bot", "due_date": "2026-09-01"}
        upd = manager.put(f"{BASE}/review/{IN_REVIEW_MEETING}/actions",
                          json={"actions": original + [new_item]}, timeout=60)
        assert upd.status_code == 200, f"{upd.status_code} {upd.text[:300]}"
        # verify persisted
        got = manager.get(f"{BASE}/review/{IN_REVIEW_MEETING}", timeout=60).json()
        ids = [a.get("id") for a in (got["analysis"].get("actions") or [])]
        assert "action_manual_TEST_iter79" in ids, ids
        # remove
        rm = manager.put(f"{BASE}/review/{IN_REVIEW_MEETING}/actions",
                         json={"actions": original}, timeout=60)
        assert rm.status_code == 200
        got2 = manager.get(f"{BASE}/review/{IN_REVIEW_MEETING}", timeout=60).json()
        ids2 = [a.get("id") for a in (got2["analysis"].get("actions") or [])]
        assert "action_manual_TEST_iter79" not in ids2, ids2


# ---------------- backend RBAC parity with new frontend gating ----------------
class TestRbacBackendParity:
    def test_manager_cannot_rename_org(self, manager):
        me = manager.get(f"{BASE}/auth/me", timeout=60).json()
        assert me["role"] == "manager"
        current = me.get("org_name")
        r = manager.patch(f"{BASE}/org/name", json={"name": current}, timeout=60)
        assert r.status_code == 403, f"manager rename allowed (status {r.status_code}) - RBAC not enforced server-side"

    def test_manager_cannot_delete_meeting(self, manager):
        # create a throwaway meeting as manager then attempt delete
        c = manager.post(f"{BASE}/meetings/", json={"title": "TEST_iter79 rbac delete",
                                                   "date": "2026-09-01T10:00", "attendees": []}, timeout=60)
        assert c.status_code in (200, 201), f"{c.status_code} {c.text[:200]}"
        mid = c.json().get("id") or c.json().get("meeting", {}).get("id")
        d = manager.delete(f"{BASE}/meetings/{mid}", timeout=60)
        if d.status_code != 403:
            # cleanup with admin-equivalent (manager already deleted it)
            pytest.fail(f"manager delete meeting returned {d.status_code}; expected 403 to match admin-only UI gating")
