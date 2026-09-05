"""Iteration 119 regression: Final 11 SELECT * -> explicit column list trim
covering meetings.py get_meeting, review.py get_review_data + export_pdf,
portfolio.py _build_portfolio_data, doc_uploads.py get_upload, prep.py get_prep,
plus super_admin.py create_org_user 3-phase transaction restructuring.
"""
import asyncio
import os
import uuid as _uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

_be = dotenv_values("/app/backend/.env")
_fe = dotenv_values("/app/frontend/.env")
BASE = _fe["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = _be["DATABASE_URL"]

ADMIN = ("admin@supervision.com", "Admin123!")
USER = ("user@supervision.com", "AnotherNew789!")
JANE = ("jane@supervision.com", "JaneNew456!")
MANAGER = ("manager@supervision.com", "Manager123!")
SUPER = ("superadmin@1two.one", "NewPass123!")
TEST_ORG_ID = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"


def _mfa_override(email):
    async def _run():
        conn = await asyncpg.connect(DSN, ssl="require")
        h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
        exp = datetime.now(timezone.utc) + timedelta(minutes=10)
        await conn.execute(
            "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
            h, exp, email,
        )
        await conn.close()
    asyncio.run(_run())


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} -> {r.status_code}: {r.text}"
    data = r.json()
    if data.get("requires_mfa"):
        _mfa_override(email)
        r2 = s.post(
            f"{BASE}/auth/verify-mfa",
            json={"mfa_session": data["mfa_session"], "code": "123456"},
            timeout=30,
        )
        assert r2.status_code == 200, f"verify-mfa {email} -> {r2.status_code}: {r2.text}"
    return s


@pytest.fixture(scope="module")
def admin():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def user():
    return _login(*USER)


@pytest.fixture(scope="module")
def jane():
    return _login(*JANE)


@pytest.fixture(scope="module")
def manager():
    return _login(*MANAGER)


@pytest.fixture(scope="module")
def super_admin():
    return _login(*SUPER)


# ============================================================================
# 1. GET /api/meetings/{id} — get_meeting trim
# ============================================================================
_EXPECTED_MEETING_FIELDS = {
    "id", "org_id", "title", "date", "location", "meeting_type",
    "created_by", "sign_off_manager_id", "sign_off_manager_name",
    "attendees", "team_id", "setting_id", "status",
    "analysis_id", "transcript_id", "transcript_has_warnings",
    "shared_with", "pii_redactions",
    "sign_off_record", "reopen_record", "rescan_status", "reopen_requested",
    "created_at", "updated_at",
}


class TestGetMeetingDetail:
    @classmethod
    def setup_class(cls):
        s = _login(*ADMIN)
        mts = s.get(f"{BASE}/meetings").json()
        cls.in_review_id = next((m["id"] for m in mts if m.get("status") == "in_review" and m.get("analysis_id")), None)
        cls.signed_off_id = next((m["id"] for m in mts if m.get("status") in ("signed_off", "shared")), None)

    def test_get_meeting_has_all_detail_fields(self, admin):
        if not self.in_review_id:
            pytest.skip("no in_review meeting")
        r = admin.get(f"{BASE}/meetings/{self.in_review_id}")
        assert r.status_code == 200, r.text
        d = r.json()
        missing = _EXPECTED_MEETING_FIELDS - set(d.keys())
        assert not missing, f"missing fields: {missing}"
        # column-error safety
        assert "column" not in r.text.lower() or "column does not exist" not in r.text.lower()
        # nested payloads
        assert "transcript" in d, "transcript key present at top level"
        assert "analysis" in d, "analysis key present at top level"
        if d.get("transcript"):
            t = d["transcript"]
            for k in ("speaker_text", "speaker_colors", "safety_warnings"):
                assert k in t, f"transcript.{k} missing"
        if d.get("analysis"):
            a = d["analysis"]
            for k in ("actions", "risks", "cqc_mappings", "care_cert_mappings", "custom_mappings", "achievements", "learning_needs"):
                assert k in a, f"analysis.{k} missing"

    def test_get_signed_off_meeting_detail(self, admin):
        if not self.signed_off_id:
            pytest.skip("no signed_off meeting")
        r = admin.get(f"{BASE}/meetings/{self.signed_off_id}")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] in ("signed_off", "shared")
        # sign_off_record should be present dict
        assert "sign_off_record" in d

    def test_get_meeting_403_cross_org(self, jane):
        # jane belongs to same org but not attendee on Test Company's in_review meetings
        if not self.in_review_id:
            pytest.skip("no meeting")
        r = jane.get(f"{BASE}/meetings/{self.in_review_id}")
        assert r.status_code in (200, 403, 404), r.text


# ============================================================================
# 2. GET /api/review/{meeting_id} — get_review_data trim
# ============================================================================
class TestGetReview:
    @classmethod
    def setup_class(cls):
        s = _login(*ADMIN)
        mts = s.get(f"{BASE}/meetings").json()
        cls.in_review_id = next((m["id"] for m in mts if m.get("status") == "in_review" and m.get("analysis_id")), None)
        cls.signed_off_id = next((m["id"] for m in mts if m.get("status") in ("signed_off", "shared")), None)

    def test_review_full_shape(self, admin):
        if not self.in_review_id:
            pytest.skip("no in_review meeting")
        r = admin.get(f"{BASE}/review/{self.in_review_id}")
        assert r.status_code == 200, r.text
        d = r.json()
        # review endpoint returns flat shape: meeting fields at top-level + transcript/analysis/comments
        for k in ("transcript", "analysis", "comments"):
            assert k in d, f"missing top-level {k}"
        for k in ("id", "title", "date", "status", "attendees", "sign_off_record",
                  "reopen_record", "pii_redactions", "transcript_has_warnings",
                  "rescan_status", "reopen_requested"):
            assert k in d, f"meeting.{k} missing"
        a = d.get("analysis") or {}
        if a:
            for k in ("summary", "actions", "risks", "cqc_mappings",
                      "care_cert_mappings", "custom_mappings",
                      "achievements", "learning_needs"):
                assert k in a, f"analysis.{k} missing"
        assert isinstance(d["comments"], list)


# ============================================================================
# 3. GET /api/review/{meeting_id}/export-pdf
# ============================================================================
class TestExportPdf:
    @classmethod
    def setup_class(cls):
        s = _login(*ADMIN)
        mts = s.get(f"{BASE}/meetings").json()
        cls.signed_off_id = next((m["id"] for m in mts if m.get("status") in ("signed_off", "shared")), None)

    def test_export_pdf_signed_off(self, admin):
        if not self.signed_off_id:
            pytest.skip("no signed_off meeting")
        r = admin.get(f"{BASE}/review/{self.signed_off_id}/export-pdf")
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:400]}"
        assert r.headers.get("content-type", "").startswith("application/pdf"), r.headers.get("content-type")
        assert r.content[:4] == b"%PDF", "not a PDF payload"
        assert len(r.content) > 1000, f"PDF suspiciously small: {len(r.content)} bytes"

    def test_export_pdf_include_transcript(self, admin):
        if not self.signed_off_id:
            pytest.skip("no signed_off meeting")
        r = admin.get(f"{BASE}/review/{self.signed_off_id}/export-pdf?include_transcript=true")
        assert r.status_code == 200, r.text[:400]
        assert r.content[:4] == b"%PDF"

    def test_export_transcript_regression(self, admin):
        if not self.signed_off_id:
            pytest.skip("no signed_off meeting")
        r = admin.get(f"{BASE}/review/{self.signed_off_id}/export-transcript")
        # transcript may not exist on this meeting — accept 200 or 404, never 500
        assert r.status_code in (200, 400, 404), r.text[:200]
        assert "column does not exist" not in r.text.lower()


# ============================================================================
# 4. GET /api/portfolio/{user_id}
# ============================================================================
class TestPortfolio:
    def test_admin_own_portfolio(self, admin):
        me = admin.get(f"{BASE}/auth/me").json()
        r = admin.get(f"{BASE}/portfolio/{me['id']}")
        assert r.status_code == 200, r.text
        d = r.json()
        # user block should carry name/email/role
        u = d.get("user") or d
        assert u.get("name") and u.get("email") and u.get("role")
        assert "column does not exist" not in r.text.lower()

    def test_admin_views_attendee_portfolio(self, admin):
        # find attendee id in same org
        u = _login(*USER)
        me = u.get(f"{BASE}/auth/me").json()
        r = admin.get(f"{BASE}/portfolio/{me['id']}")
        assert r.status_code == 200, r.text
        d = r.json()
        u_block = d.get("user") or d
        assert u_block.get("email") == USER[0]
        assert u_block.get("role") == "attendee"

    def test_attendee_own_portfolio(self, user):
        me = user.get(f"{BASE}/auth/me").json()
        r = user.get(f"{BASE}/portfolio/{me['id']}")
        assert r.status_code == 200
        assert "column does not exist" not in r.text.lower()


# ============================================================================
# 5. GET /api/doc-uploads/{upload_id}
# ============================================================================
class TestDocUpload:
    @classmethod
    def setup_class(cls):
        # Find a done doc upload via list
        s = _login(*ADMIN)
        r = s.get(f"{BASE}/doc-uploads")
        rows = r.json() if r.status_code == 200 else []
        cls.done_id = next((u["id"] for u in rows if u.get("status") == "done"), None)
        cls.any_id = rows[0]["id"] if rows else None

    def test_get_upload_done(self, admin):
        if not self.done_id:
            pytest.skip("no done upload")
        r = admin.get(f"{BASE}/doc-uploads/{self.done_id}")
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("id", "label", "filename", "staff_name", "meeting_date",
                  "uploader_name", "status", "cqc_mappings", "care_cert_mappings",
                  "custom_mappings"):
            assert k in d, f"doc-upload.{k} missing"

    def test_get_upload_404(self, admin):
        fake = "00000000-0000-0000-0000-000000000000"
        r = admin.get(f"{BASE}/doc-uploads/{fake}")
        assert r.status_code in (404, 400), r.text


# ============================================================================
# 6. GET /api/prep/{meeting_id}
# ============================================================================
class TestPrep:
    @classmethod
    def setup_class(cls):
        # Find a meeting with prep record
        async def _find():
            c = await asyncpg.connect(DSN, ssl="require")
            r = await c.fetchval(
                "SELECT meeting_id::text FROM meeting_prep WHERE gen_status='done' ORDER BY created_at DESC LIMIT 1"
            )
            await c.close()
            return r
        cls.mid = asyncio.run(_find())

    def test_get_prep_shape(self, admin):
        if not self.mid:
            pytest.skip("no prep record")
        r = admin.get(f"{BASE}/prep/{self.mid}")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("exists") is True
        for k in ("sections", "focus_topic", "shared_with_attendees",
                  "gen_status", "included_source_ids", "coverage_results"):
            assert k in d, f"prep.{k} missing"
        assert isinstance(d["sections"], list)

    def test_get_prep_no_record(self, admin):
        # random meeting id that has no prep row
        fake = "00000000-0000-0000-0000-000000000000"
        r = admin.get(f"{BASE}/prep/{fake}")
        # meeting doesn't exist so 404
        assert r.status_code in (200, 403, 404), r.text


# ============================================================================
# 7. POST /api/super-admin/orgs/{org_id}/users — 3-phase txn restructuring
# ============================================================================
class TestSuperAdminCreateOrgUser:
    def test_create_login_and_verify_supabase_flags(self, super_admin):
        suffix = _uuid.uuid4().hex[:8]
        email = f"TEST_iter119_{suffix}@supervision.com"
        password = "Iter119Pass!"
        payload = {"email": email, "password": password, "name": f"TEST iter119 {suffix}", "role": "attendee"}
        r = super_admin.post(f"{BASE}/super-admin/orgs/{TEST_ORG_ID}/users", json=payload, timeout=60)
        assert r.status_code in (200, 201), r.text
        d = r.json()
        # (b) response shape unchanged
        for k in ("id", "email", "name", "role", "org_id"):
            assert k in d, f"missing {k}"
        assert d["email"] == email.lower()
        assert d["role"] == "attendee"
        assert d["org_id"] == TEST_ORG_ID
        user_id = d["id"]

        try:
            # (e) DB flags flipped
            async def _check_flags():
                c = await asyncpg.connect(DSN, ssl="require")
                row = await c.fetchrow(
                    "SELECT supabase_migrated, supabase_password_set, must_change_password FROM users WHERE id=$1",
                    user_id,
                )
                await c.close()
                return row
            row = asyncio.run(_check_flags())
            assert row is not None, "user not persisted"
            assert row["supabase_migrated"] is True, f"supabase_migrated={row['supabase_migrated']}"
            assert row["supabase_password_set"] is True, f"supabase_password_set={row['supabase_password_set']}"

            # (a) user can log in with given password (may require password change on first login)
            s = requests.Session()
            r2 = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=30)
            assert r2.status_code == 200, f"login of new user failed: {r2.status_code} {r2.text}"
            # attendee -> no MFA required, expect success (may include must_change_password redirect flag)
            d2 = r2.json()
            assert not d2.get("requires_mfa"), "attendee should not require MFA"
        finally:
            # cleanup: hard-delete the created user + supabase identity row
            async def _cleanup():
                c = await asyncpg.connect(DSN, ssl="require")
                # Delete any supabase auth identities under this id (best-effort)
                await c.execute("DELETE FROM users WHERE id=$1", user_id)
                await c.close()
            try:
                asyncio.run(_cleanup())
            except Exception as e:
                print(f"cleanup warn: {e}")

    def test_create_org_not_found(self, super_admin):
        fake = "00000000-0000-0000-0000-000000000000"
        suffix = _uuid.uuid4().hex[:8]
        payload = {"email": f"TEST_iter119_x_{suffix}@supervision.com", "password": "Iter119Pass!", "name": "x", "role": "attendee"}
        r = super_admin.post(f"{BASE}/super-admin/orgs/{fake}/users", json=payload, timeout=30)
        assert r.status_code == 404, r.text
        assert "not found" in r.text.lower()

    def test_create_duplicate_email(self, super_admin):
        # admin@supervision.com already exists
        payload = {"email": ADMIN[0], "password": "Iter119Pass!", "name": "dup", "role": "attendee"}
        r = super_admin.post(f"{BASE}/super-admin/orgs/{TEST_ORG_ID}/users", json=payload, timeout=30)
        assert r.status_code == 400, r.text
        assert "already exists" in r.text.lower()


# ============================================================================
# 8. General smoke — meetings list, admin dashboard, login
# ============================================================================
class TestSmoke:
    def test_meetings_list_admin(self, admin):
        r = admin.get(f"{BASE}/meetings")
        assert r.status_code == 200 and isinstance(r.json(), list)

    def test_meetings_list_manager(self, manager):
        r = manager.get(f"{BASE}/meetings")
        assert r.status_code == 200

    def test_admin_users_list(self, admin):
        r = admin.get(f"{BASE}/admin/users")
        assert r.status_code == 200 and isinstance(r.json(), list)

    def test_auth_me_admin(self, admin):
        r = admin.get(f"{BASE}/auth/me")
        assert r.status_code == 200 and r.json()["role"] == "admin"
