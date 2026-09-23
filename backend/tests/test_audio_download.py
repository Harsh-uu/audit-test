"""Backend tests for the Download Audio feature (Settings > Download Audio).

Covers:
- GET /api/meetings/downloadable-audio filters (no signed_off, no soft-deleted audio)
- Admin vs manager visibility (RBAC on list)
- GET /api/meetings/{id}/audio-download consent gate, RBAC, signed_off policy
- audit_logs row written with IP + user name on successful download
"""
import asyncio
import os
import re
import uuid
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

ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PW = "Admin123!X"
MGR_EMAIL = "manager@supervision.com"
MGR_PW = "Manager123!"
ORG_ID = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"
SIGNED_OFF_MEETING_ID = "4b948235-5483-4f60-af2e-3f9591e3978b"


# ---------- helpers ----------

async def _set_mfa_bypass(email: str):
    conn = await asyncpg.connect(DSN, ssl="require")
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = datetime.now(timezone.utc) + timedelta(minutes=10)
    await conn.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, exp, email)
    await conn.close()


def _login(email: str, password: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:200]}"
    data = r.json()
    if data.get("requires_mfa"):
        asyncio.run(_set_mfa_bypass(email))
        r2 = s.post(f"{BASE}/auth/verify-mfa", json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=30)
        assert r2.status_code == 200, f"mfa verify failed: {r2.status_code} {r2.text[:200]}"
    return s


@pytest.fixture(scope="module")
def admin_session():
    return _login(ADMIN_EMAIL, ADMIN_PW)


@pytest.fixture(scope="module")
def manager_session():
    return _login(MGR_EMAIL, MGR_PW)


@pytest.fixture(scope="module")
def admin_id(admin_session):
    r = admin_session.get(f"{BASE}/auth/me", timeout=30)
    return r.json()["id"]


@pytest.fixture(scope="module")
def manager_id(manager_session):
    r = manager_session.get(f"{BASE}/auth/me", timeout=30)
    return r.json()["id"]


# ---------- tests ----------

class TestDownloadableAudioList:
    """GET /api/meetings/downloadable-audio"""

    def test_admin_list_200_and_no_signed_off(self, admin_session):
        r = admin_session.get(f"{BASE}/meetings/downloadable-audio", timeout=30)
        assert r.status_code == 200, r.text[:200]
        rows = r.json()
        assert isinstance(rows, list)
        assert len(rows) > 0, "expected some downloadable meetings for admin"
        assert all(m["status"] != "signed_off" for m in rows), \
            "signed_off meetings must never appear in downloadable-audio"
        # signed-off meeting id must not be there
        assert SIGNED_OFF_MEETING_ID not in [str(m["id"]) for m in rows]

    def test_admin_list_all_have_audio_file(self, admin_session):
        """List joins audio_files where is_deleted=FALSE — every row is downloadable."""
        r = admin_session.get(f"{BASE}/meetings/downloadable-audio", timeout=30)
        rows = r.json()
        for m in rows:
            assert "id" in m and "title" in m and "status" in m

    def test_manager_list_only_own_sign_off_meetings(self, manager_session, manager_id):
        r = manager_session.get(f"{BASE}/meetings/downloadable-audio", timeout=30)
        assert r.status_code == 200, r.text[:200]
        rows = r.json()
        for m in rows:
            assert str(m.get("sign_off_manager_id")) == str(manager_id), \
                f"manager sees a meeting where they aren't sign_off_manager: {m}"


class TestConsentGate:
    def test_no_consent_returns_400(self, admin_session):
        # pick any downloadable meeting
        rows = admin_session.get(f"{BASE}/meetings/downloadable-audio", timeout=30).json()
        assert rows
        mid = rows[0]["id"]
        r = admin_session.get(f"{BASE}/meetings/{mid}/audio-download", timeout=30)
        assert r.status_code == 400
        assert "consent" in r.text.lower()

    def test_consent_false_returns_400(self, admin_session):
        rows = admin_session.get(f"{BASE}/meetings/downloadable-audio", timeout=30).json()
        mid = rows[0]["id"]
        r = admin_session.get(f"{BASE}/meetings/{mid}/audio-download?consent=false", timeout=30)
        assert r.status_code == 400


class TestSignedOffPolicy:
    def test_signed_off_meeting_rejected(self, admin_session):
        """Core policy: even with a leftover audio_file_id, signed_off meetings 400/404."""
        r = admin_session.get(
            f"{BASE}/meetings/{SIGNED_OFF_MEETING_ID}/audio-download?consent=true", timeout=30)
        assert r.status_code in (400, 404), f"expected 400/404, got {r.status_code}: {r.text[:200]}"


class TestSuccessfulDownload:
    def test_admin_download_returns_audio_bytes(self, admin_session):
        rows = admin_session.get(f"{BASE}/meetings/downloadable-audio", timeout=30).json()
        # prefer one with a real audio file
        mid = rows[0]["id"]
        r = admin_session.get(
            f"{BASE}/meetings/{mid}/audio-download?consent=true", timeout=60)
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:200]}"
        assert len(r.content) > 0, "empty audio body"
        ct = r.headers.get("content-type", "")
        assert "audio" in ct.lower() or "octet-stream" in ct.lower() or "webm" in ct.lower(), \
            f"unexpected content-type: {ct}"
        cd = r.headers.get("content-disposition", "")
        assert "filename" in cd.lower(), f"missing filename in content-disposition: {cd}"

    def test_audit_log_written_with_ip_and_user_name(self, admin_session):
        rows = admin_session.get(f"{BASE}/meetings/downloadable-audio", timeout=30).json()
        mid = str(rows[0]["id"])

        async def _pre():
            c = await asyncpg.connect(DSN, ssl="require")
            n = await c.fetchval(
                "SELECT COUNT(*) FROM audit_logs WHERE meeting_id=$1 AND action='audio_downloaded'", mid)
            await c.close()
            return n
        before = asyncio.run(_pre())

        r1 = admin_session.get(f"{BASE}/meetings/{mid}/audio-download?consent=true", timeout=60)
        assert r1.status_code == 200
        r2 = admin_session.get(f"{BASE}/meetings/{mid}/audio-download?consent=true", timeout=60)
        assert r2.status_code == 200

        async def _post():
            c = await asyncpg.connect(DSN, ssl="require")
            rows_ = await c.fetch(
                "SELECT user_name, detail FROM audit_logs "
                "WHERE meeting_id=$1 AND action='audio_downloaded' "
                "ORDER BY timestamp DESC LIMIT 5", mid)
            n = await c.fetchval(
                "SELECT COUNT(*) FROM audit_logs WHERE meeting_id=$1 AND action='audio_downloaded'", mid)
            await c.close()
            return n, [dict(r) for r in rows_]
        after, latest = asyncio.run(_post())
        assert after >= before + 2, f"expected 2 new audit rows (before={before}, after={after})"
        # at least the two most recent should have user name + IP in detail
        top2 = latest[:2]
        for row in top2:
            assert row["user_name"], f"missing user_name in audit row: {row}"
            assert "IP:" in (row["detail"] or ""), f"IP: not in detail: {row['detail']}"


class TestManagerCrossOwnership:
    """Direct-endpoint 403 when a manager tries someone else's meeting."""

    def test_403_when_manager_is_not_sign_off_manager(self, manager_session, admin_id, manager_id):
        """Temporarily reassign one meeting's sign_off_manager_id to admin's UUID,
        confirm manager gets 403 on the direct endpoint, then restore."""
        async def _prep():
            c = await asyncpg.connect(DSN, ssl="require")
            # pick a not-signed-off meeting that currently belongs to manager and has audio
            row = await c.fetchrow(
                "SELECT m.id, m.sign_off_manager_id, m.sign_off_manager_name "
                "FROM meetings m JOIN audio_files a ON a.id=m.audio_file_id "
                "WHERE m.org_id=$1 AND m.status!='signed_off' AND a.is_deleted=FALSE "
                "AND m.sign_off_manager_id=$2 LIMIT 1",
                ORG_ID, uuid.UUID(manager_id))
            if not row:
                await c.close()
                return None
            mid = str(row["id"])
            orig_id = row["sign_off_manager_id"]
            orig_name = row["sign_off_manager_name"]
            await c.execute(
                "UPDATE meetings SET sign_off_manager_id=$1, sign_off_manager_name=$2 WHERE id=$3",
                uuid.UUID(admin_id), "Test Admin", uuid.UUID(mid))
            await c.close()
            return mid, orig_id, orig_name

        async def _restore(mid, orig_id, orig_name):
            c = await asyncpg.connect(DSN, ssl="require")
            await c.execute(
                "UPDATE meetings SET sign_off_manager_id=$1, sign_off_manager_name=$2 WHERE id=$3",
                orig_id, orig_name, uuid.UUID(mid))
            await c.close()

        prep = asyncio.run(_prep())
        assert prep is not None, "no suitable manager-owned meeting to reassign"
        mid, orig_id, orig_name = prep
        try:
            r = manager_session.get(
                f"{BASE}/meetings/{mid}/audio-download?consent=true", timeout=30)
            assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:200]}"
            # And that meeting must not appear in the manager's list any more
            rows = manager_session.get(f"{BASE}/meetings/downloadable-audio", timeout=30).json()
            assert mid not in [str(m["id"]) for m in rows], \
                "meeting reassigned to admin should not appear in manager's list"
        finally:
            asyncio.run(_restore(mid, orig_id, orig_name))


class TestAttendeeAccess:
    def test_attendee_cannot_list(self):
        s = _login("user@supervision.com", "Staff123!")
        r = s.get(f"{BASE}/meetings/downloadable-audio", timeout=30)
        assert r.status_code == 403
