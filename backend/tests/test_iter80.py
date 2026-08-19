"""Iteration 80 regression suite.

Covers:
  1. RBAC: DELETE /api/meetings/{id} + PATCH /api/org/name -> 403 for manager, OK for admin
  2. Standalone transcript PDF 'Date: DD/MM/YYYY' UK format
  3. utils/ai._apply_uk_language safeguarding regex (dash-anchored only)
  4. Audit trail export detail no longer duplicates the label
  5. MFA login response returns a masked email
"""
import io
import re
import sys

import pytest
import requests
from pypdf import PdfReader

sys.path.insert(0, "/app/backend/tests")
sys.path.insert(0, "/app/backend")
from _iter79_login import login, BASE  # noqa: E402

ADMIN = ("admin@supervision.com", "Admin123!")
MANAGER = ("manager@supervision.com", "Manager123!")
SIGNED_MEETING = "0f38f385-7c85-428e-923c-d7c365659192"


@pytest.fixture(scope="module")
def admin():
    return login(*ADMIN)


@pytest.fixture(scope="module")
def manager():
    return login(*MANAGER)


# ---------------- 1. RBAC parity ----------------
class TestRBAC:
    def test_manager_cannot_delete_meeting(self, manager):
        r = manager.delete(f"{BASE}/meetings/{SIGNED_MEETING}", timeout=60)
        assert r.status_code == 403, f"expected 403 got {r.status_code} {r.text[:200]}"

    def test_manager_cannot_rename_org(self, manager):
        r = manager.patch(f"{BASE}/org/name", json={"name": "TEST_ShouldFail"}, timeout=60)
        assert r.status_code == 403, f"expected 403 got {r.status_code} {r.text[:200]}"

    def test_admin_can_rename_org(self, admin):
        me = admin.get(f"{BASE}/auth/me", timeout=60)
        original = me.json().get("org_name") if me.status_code == 200 else None
        r = admin.patch(f"{BASE}/org/name", json={"name": "TEST_Rename_Org"}, timeout=60)
        assert r.status_code == 200, f"admin rename failed {r.status_code} {r.text[:300]}"
        assert r.json().get("name") == "TEST_Rename_Org"
        # restore
        if original:
            back = admin.patch(f"{BASE}/org/name", json={"name": original}, timeout=60)
            assert back.status_code == 200
            assert back.json().get("name") == original

    def test_admin_delete_meeting_not_403(self, admin):
        """Admin must not be blocked by RBAC; use a bogus id so nothing is destroyed."""
        r = admin.delete(f"{BASE}/meetings/00000000-0000-0000-0000-000000000000", timeout=60)
        assert r.status_code != 403, "admin unexpectedly blocked from delete"
        assert r.status_code == 404, f"expected 404 for unknown meeting, got {r.status_code}"


# ---------------- 2. Transcript PDF UK date ----------------
class TestTranscriptPdfDate:
    def test_header_date_uk_format(self, admin):
        r = admin.get(f"{BASE}/review/{SIGNED_MEETING}/export-transcript", timeout=180)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        assert r.headers.get("content-type", "").startswith("application/pdf")
        text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(r.content)).pages[:2])
        m = re.search(r"Date:\s*([0-9]{2}/[0-9]{2}/[0-9]{4})", text)
        assert m, f"UK 'Date: DD/MM/YYYY' not found. Header text: {text[:400]!r}"
        assert not re.search(r"Date:\s*\d{4}-\d{2}-\d{2}", text), "raw ISO date still present"


# ---------------- 3. Safeguarding regex ----------------
class TestSafeguardingRegex:
    @pytest.mark.parametrize("src,expected", [
        ("Potential safeguarding indicator — visitor unaccounted for",
         "Potential safeguarding — visitor unaccounted for"),
        ("Potential safeguarding breach - no DBS check",
         "Potential safeguarding - no DBS check"),
        ("potential safeguarding concern — medication error",
         "Potential safeguarding — medication error"),
    ])
    def test_template_rewritten(self, src, expected):
        from utils.ai import _apply_uk_language
        assert _apply_uk_language(src) == expected

    @pytest.mark.parametrize("prose", [
        "a potential safeguarding concern was noted during the session",
        "The manager flagged a potential safeguarding indicator in the notes.",
        "There were potential safeguarding concerns about the visitor.",
    ])
    def test_prose_untouched(self, prose):
        from utils.ai import _apply_uk_language
        assert _apply_uk_language(prose) == prose


# ---------------- 4. Audit trail detail text ----------------
class TestAuditTrailDetail:
    def test_export_events_detail(self, admin):
        # trigger both export types
        r1 = admin.get(f"{BASE}/review/{SIGNED_MEETING}/export-pdf?include_transcript=true", timeout=180)
        assert r1.status_code == 200, f"export-pdf {r1.status_code} {r1.text[:200]}"
        r2 = admin.get(f"{BASE}/review/{SIGNED_MEETING}/export-transcript", timeout=180)
        assert r2.status_code == 200

        a = admin.get(f"{BASE}/review/{SIGNED_MEETING}/audit-trail", timeout=60)
        assert a.status_code == 200, f"{a.status_code} {a.text[:200]}"
        payload = a.json()
        events = payload if isinstance(payload, list) else payload.get("events", payload.get("entries", []))
        assert events, f"no audit events returned: {str(payload)[:300]}"

        pdf_events = [e for e in events if e.get("type") == "pdf_exported"]
        ts_events = [e for e in events if e.get("type") == "transcript_exported"]
        assert pdf_events, f"no pdf_exported event: {str(events)[:400]}"
        assert ts_events, f"no transcript_exported event: {str(events)[:400]}"

        # Only the newest events reflect the fix; older rows were written before it.
        newest_pdf = max(pdf_events, key=lambda e: e.get("timestamp", ""))
        newest_ts = max(ts_events, key=lambda e: e.get("timestamp", ""))
        d = (newest_pdf.get("detail") or "").strip()
        assert d in ("Includes transcript", "Summary only"), f"bad pdf detail {d!r}"
        assert (newest_ts.get("detail") or "").strip() == "", \
            f"transcript detail should be empty, got {newest_ts.get('detail')!r}"


# ---------------- 5. Masked email on MFA response ----------------
class TestMaskedEmail:
    def test_manager_mfa_email_masked(self):
        r = requests.post(f"{BASE}/auth/login",
                          json={"email": MANAGER[0], "password": MANAGER[1]}, timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        data = r.json()
        assert data.get("requires_mfa") is True, f"expected MFA gate: {data}"
        email = data.get("email", "")
        assert email != MANAGER[0], "full email leaked in MFA response"
        assert re.match(r"^m\*+@supervision\.com$", email), f"unexpected mask: {email!r}"
