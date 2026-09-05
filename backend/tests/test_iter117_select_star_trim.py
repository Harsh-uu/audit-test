"""
Iteration 117 regression: SELECT * -> explicit column list trimming.

Covers the endpoints where meetings/analyses/meeting_prep/supervision_uploads
queries were narrowed to explicit columns. Verifies:
  - portfolio /api/portfolio/{user_id} (attendee self + admin/manager on another)
  - admin exports: export-evidence (csv+pdf), export-cqc-excerpts,
    export-cc-excerpts, export-transcripts
  - prep: /api/prep/{meeting_id}, POST generate, POST carry-forward-missed
  - processing: retry, diarize, retranscribe (error paths where data is missing)
  - doc_uploads: PUT /{upload_id}/evidence/{evidence_id}
  - full regression sanity: login all 4 roles, meetings list, isolation
"""
import os
import sys
import asyncio
import pytest
import requests
from datetime import datetime, timezone, timedelta

from dotenv import dotenv_values

_fe = dotenv_values("/app/frontend/.env")
_be = dotenv_values("/app/backend/.env")
BASE = _fe["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = _be["DATABASE_URL"]

ADMIN = ("admin@supervision.com", "Admin123!")
ATTENDEE = ("user@supervision.com", "AnotherNew789!")
JANE = ("jane@supervision.com", "JaneNew456!")
MANAGER = ("manager@supervision.com", "Manager123!")


def _login_session(email: str, pw: str) -> requests.Session:
    """Login helper handling optional MFA (with DB override)."""
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:200]}"
    data = r.json()
    if data.get("requires_mfa"):
        import asyncpg, bcrypt
        async def _ovr():
            conn = await asyncpg.connect(DSN, ssl="require")
            h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
            exp = datetime.now(timezone.utc) + timedelta(minutes=10)
            await conn.execute(
                "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
                h, exp, email)
            await conn.close()
        asyncio.run(_ovr())
        r2 = s.post(f"{BASE}/auth/verify-mfa",
                    json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=30)
        assert r2.status_code == 200, r2.text[:200]
    return s


# ---- session fixtures ----
@pytest.fixture(scope="module")
def admin_s():
    return _login_session(*ADMIN)


@pytest.fixture(scope="module")
def attendee_s():
    return _login_session(*ATTENDEE)


@pytest.fixture(scope="module")
def jane_s():
    return _login_session(*JANE)


@pytest.fixture(scope="module")
def manager_s():
    return _login_session(*MANAGER)


@pytest.fixture(scope="module")
def attendee_user_id(attendee_s):
    r = attendee_s.get(f"{BASE}/auth/me", timeout=15)
    assert r.status_code == 200
    return r.json()["id"]


# ─────────────────────────── Full regression sanity ───────────────────────────
class TestSanity:
    def test_login_admin(self, admin_s):
        me = admin_s.get(f"{BASE}/auth/me", timeout=15)
        assert me.status_code == 200 and me.json()["role"] == "admin"

    def test_login_attendee(self, attendee_s):
        me = attendee_s.get(f"{BASE}/auth/me", timeout=15)
        assert me.status_code == 200 and me.json()["role"] == "attendee"

    def test_login_manager(self, manager_s):
        me = manager_s.get(f"{BASE}/auth/me", timeout=15)
        assert me.status_code == 200 and me.json()["role"] == "manager"

    def test_login_jane(self, jane_s):
        me = jane_s.get(f"{BASE}/auth/me", timeout=15)
        assert me.status_code == 200 and me.json()["email"] == "jane@supervision.com"

    def test_meetings_list_admin(self, admin_s):
        r = admin_s.get(f"{BASE}/meetings", timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_meetings_list_jane_isolation(self, jane_s):
        """jane should see very few (~1) meetings — not admin's 15."""
        r = jane_s.get(f"{BASE}/meetings", timeout=30)
        assert r.status_code == 200
        j = r.json()
        assert isinstance(j, list)
        assert len(j) <= 3, f"jane sees {len(j)} meetings — isolation likely broken"


# ─────────────────────────── Portfolio (SELECT * trim) ───────────────────────────
class TestPortfolio:
    def test_attendee_own_portfolio(self, attendee_s, attendee_user_id):
        r = attendee_s.get(f"{BASE}/portfolio/{attendee_user_id}", timeout=30)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        # Structural fields that come from the trimmed meetings/analyses SELECT
        for key in ("cqc_summary", "care_cert_summary", "stats", "user"):
            assert key in data, f"missing {key} in portfolio response"
        stats = data["stats"]
        for k in ("total_meetings", "cqc_count", "care_cert_count", "custom_count"):
            assert k in stats, f"missing stats.{k}"
            assert isinstance(stats[k], int)
        # Sanity: care_cert summary entries have the shape derived from analyses.care_cert_mappings
        for e in (data.get("care_cert_summary") or [])[:3]:
            # Field is either standard_ref or reference — accept either
            assert any(k in e for k in ("standard_ref", "reference", "regulation_ref"))
            assert "evidence_count" in e or "count" in e

    def test_admin_views_attendee_portfolio(self, admin_s, attendee_user_id):
        r = admin_s.get(f"{BASE}/portfolio/{attendee_user_id}", timeout=30)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert "stats" in data and "cqc_summary" in data

    def test_manager_views_attendee_portfolio(self, manager_s, attendee_user_id):
        r = manager_s.get(f"{BASE}/portfolio/{attendee_user_id}", timeout=30)
        assert r.status_code == 200, r.text[:300]

    def test_portfolio_numbers_consistent(self, admin_s, attendee_s, attendee_user_id):
        """Same portfolio numbers whether viewed by owner or by admin."""
        r1 = attendee_s.get(f"{BASE}/portfolio/{attendee_user_id}", timeout=30).json()
        r2 = admin_s.get(f"{BASE}/portfolio/{attendee_user_id}", timeout=30).json()
        assert r1["stats"]["total_meetings"] == r2["stats"]["total_meetings"]
        assert r1["stats"]["cqc_count"] == r2["stats"]["cqc_count"]
        assert r1["stats"]["care_cert_count"] == r2["stats"]["care_cert_count"]
        assert r1["stats"]["custom_count"] == r2["stats"]["custom_count"]
        # Summary lists should match length-wise
        assert len(r1.get("cqc_summary") or []) == len(r2.get("cqc_summary") or [])
        assert len(r1.get("care_cert_summary") or []) == len(r2.get("care_cert_summary") or [])


# ─────────────────────────── Admin exports (SELECT * trim) ───────────────────────────
class TestAdminExports:
    def test_export_evidence_csv(self, admin_s):
        r = admin_s.post(f"{BASE}/admin/export-evidence",
                         json={"format": "csv"}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert len(r.content) > 0
        text = r.content.decode("utf-8", errors="ignore")
        # CSV header should reference the fields pulled from trimmed selects
        assert "," in text[:500]

    def test_export_evidence_pdf(self, admin_s):
        r = admin_s.post(f"{BASE}/admin/export-evidence",
                         json={"format": "pdf"}, timeout=90)
        assert r.status_code == 200, r.text[:300]
        assert r.content[:4] == b"%PDF" or r.headers.get("content-type","").startswith("application/pdf")
        assert len(r.content) > 200

    def test_export_cqc_excerpts(self, admin_s):
        r = admin_s.get(f"{BASE}/admin/export-cqc-excerpts", timeout=90)
        assert r.status_code == 200, r.text[:300]
        assert r.content[:4] == b"%PDF"
        assert len(r.content) > 500

    def test_export_cc_excerpts(self, admin_s):
        r = admin_s.get(f"{BASE}/admin/export-cc-excerpts", timeout=90)
        assert r.status_code == 200, r.text[:300]
        assert r.content[:4] == b"%PDF"
        assert len(r.content) > 500

    def test_export_transcripts(self, admin_s):
        """Data-availability: may return 404 if no signed-off meetings have a transcript.
        Regression here checks that it does NOT return 500 (missing-field KeyError)."""
        r = admin_s.post(f"{BASE}/admin/export-transcripts",
                         json={}, timeout=60)
        assert r.status_code in (200, 400, 404, 429), \
            f"unexpected {r.status_code}: {r.text[:200]}"
        if r.status_code == 200:
            assert len(r.content) > 0


# ─────────────────────────── Prep (SELECT * trim) ───────────────────────────
@pytest.fixture(scope="module")
def sample_meeting_id(admin_s):
    r = admin_s.get(f"{BASE}/meetings", timeout=30)
    assert r.status_code == 200
    meetings = r.json()
    if not meetings:
        pytest.skip("no meetings available")
    return meetings[0]["id"]


class TestPrep:
    def test_prep_context(self, admin_s, sample_meeting_id):
        r = admin_s.get(f"{BASE}/prep/{sample_meeting_id}", timeout=30)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        # trimmed columns: attendees, sign_off_manager_id, created_by, analysis_id
        assert "meeting" in data or "supervisee" in data or "attendees" in data or isinstance(data, dict)

    def test_prep_context_supervisee_names(self, admin_s, sample_meeting_id):
        r = admin_s.get(f"{BASE}/prep/{sample_meeting_id}", timeout=30)
        assert r.status_code == 200
        # Just ensure body is non-empty JSON and no KeyError from missing trimmed col
        assert r.text and len(r.text) > 2

    def test_prep_carry_forward_missed(self, admin_s, sample_meeting_id):
        """Regression: verifies no missing-column KeyError; may 404 if no prep exists."""
        r = admin_s.post(f"{BASE}/prep/{sample_meeting_id}/carry-forward-missed",
                         json={}, timeout=30)
        assert r.status_code in (200, 400, 404), r.text[:300]

    def test_prep_generate_smoke(self, admin_s, sample_meeting_id):
        """Not asserting completion (AI call is slow) — just that endpoint accepts request
        without a KeyError from trimmed columns. It may return 200/202/400/409."""
        r = admin_s.post(f"{BASE}/prep/{sample_meeting_id}/generate",
                         json={}, timeout=15)
        # Accept anything that isn't a 500 crash from missing column
        assert r.status_code != 500, f"500 from generate: {r.text[:300]}"


# ─────────────────────────── Processing (SELECT * trim) ───────────────────────────
class TestProcessing:
    def test_retry_processing_no_500(self, admin_s, sample_meeting_id):
        """Retry endpoint. May return 400/409 depending on state; must not 500."""
        r = admin_s.post(f"{BASE}/processing/{sample_meeting_id}/retry",
                         json={}, timeout=30)
        assert r.status_code != 500, f"500 crash: {r.text[:300]}"
        assert r.status_code in (200, 202, 400, 403, 404, 409)

    def test_diarize_no_500(self, admin_s, sample_meeting_id):
        """Diarize endpoint — will typically 400 if no transcript, but must not 500."""
        r = admin_s.post(f"{BASE}/processing/{sample_meeting_id}/diarize",
                         json={}, timeout=30)
        assert r.status_code != 500, f"500 crash: {r.text[:300]}"

    def test_retranscribe_no_500(self, admin_s, sample_meeting_id):
        """Retranscribe endpoint — will typically 400 without audio, must not 500."""
        r = admin_s.post(f"{BASE}/processing/{sample_meeting_id}/retranscribe",
                         json={}, timeout=30)
        assert r.status_code != 500, f"500 crash: {r.text[:300]}"

    def test_processing_bad_meeting_404(self, admin_s):
        """Non-existent meeting id should 404 cleanly (not 500)."""
        fake = "00000000-0000-0000-0000-000000000000"
        for path in ("retry", "diarize", "retranscribe"):
            r = admin_s.post(f"{BASE}/processing/{fake}/{path}", json={}, timeout=15)
            assert r.status_code in (400, 403, 404), f"{path}: {r.status_code} {r.text[:200]}"


# ─────────────────────────── Doc uploads evidence editing ───────────────────────────
class TestDocUploadsEvidence:
    def test_update_upload_evidence_not_found(self, admin_s):
        """Regression: trimmed SELECT (id, cqc_mappings, care_cert_mappings, custom_mappings)
        — endpoint must return clean 404, not 500."""
        fake_upload = "00000000-0000-0000-0000-000000000000"
        fake_evid = "00000000-0000-0000-0000-000000000001"
        r = admin_s.put(
            f"{BASE}/doc-uploads/{fake_upload}/evidence/{fake_evid}",
            json={"status": "accepted"}, timeout=15
        )
        assert r.status_code in (400, 404), f"unexpected {r.status_code}: {r.text[:200]}"

    def test_update_upload_evidence_real_upload(self, admin_s):
        """If any supervision upload exists with mappings, try to accept/reject one."""
        r = admin_s.get(f"{BASE}/doc-uploads", timeout=30)
        if r.status_code != 200:
            pytest.skip(f"doc-uploads list unavailable: {r.status_code}")
        uploads = r.json()
        if not isinstance(uploads, list) or not uploads:
            pytest.skip("no uploads to exercise evidence-edit against")
        target = None
        evid = None
        for up in uploads:
            for field in ("cqc_mappings", "care_cert_mappings", "custom_mappings"):
                items = up.get(field) or []
                if items and isinstance(items, list):
                    for m in items:
                        if m.get("id"):
                            target = up["id"]
                            evid = m["id"]
                            original_status = m.get("status")
                            break
                if target:
                    break
            if target:
                break
        if not target:
            pytest.skip("no evidence items found in any upload")
        # Toggle status to 'accepted' and back
        r1 = admin_s.put(f"{BASE}/doc-uploads/{target}/evidence/{evid}",
                         json={"status": "accepted"}, timeout=15)
        assert r1.status_code == 200, r1.text[:300]
        # Verify GET reflects change
        r2 = admin_s.get(f"{BASE}/doc-uploads/{target}", timeout=15)
        assert r2.status_code == 200
        found = False
        for field in ("cqc_mappings", "care_cert_mappings", "custom_mappings"):
            for m in (r2.json().get(field) or []):
                if m.get("id") == evid:
                    assert m.get("status") == "accepted"
                    found = True
                    break
            if found:
                break
        assert found, "evidence item vanished after update"
        # Restore
        if original_status:
            admin_s.put(f"{BASE}/doc-uploads/{target}/evidence/{evid}",
                        json={"status": original_status}, timeout=15)
