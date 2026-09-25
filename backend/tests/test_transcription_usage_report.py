"""Tests for the Super Admin Transcription Usage report (m034 + GET /super-admin/transcription-usage-report)."""
import asyncio
import os
from datetime import datetime, timezone, timedelta

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

_be = dotenv_values("/app/backend/.env")
_fe = dotenv_values("/app/frontend/.env")
BASE = _fe["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = _be["DATABASE_URL"]


async def _mfa_override(email):
    conn = await asyncpg.connect(DSN, ssl="require")
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = datetime.now(timezone.utc) + timedelta(minutes=10)
    await conn.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, exp, email)
    await conn.close()


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=60)
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text[:200]}"
    data = r.json()
    if data.get("requires_mfa"):
        asyncio.get_event_loop().run_until_complete(_mfa_override(email)) if False else asyncio.run(_mfa_override(email))
        r2 = s.post(f"{BASE}/auth/verify-mfa", json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=60)
        assert r2.status_code == 200, f"mfa failed {r2.status_code}: {r2.text[:200]}"
    return s


@pytest.fixture(scope="module")
def super_admin():
    return _login("superadmin@1two.one", "TestPass123!")


@pytest.fixture(scope="module")
def admin():
    return _login("admin@supervision.com", "Admin123!X")


# --- RBAC ---
class TestRBAC:
    def test_admin_forbidden(self, admin):
        r = admin.get(f"{BASE}/super-admin/transcription-usage-report", timeout=30)
        assert r.status_code == 403

    def test_unauthenticated_forbidden(self):
        r = requests.get(f"{BASE}/super-admin/transcription-usage-report", timeout=30)
        assert r.status_code in (401, 403)

    def test_super_admin_ok(self, super_admin):
        r = super_admin.get(f"{BASE}/super-admin/transcription-usage-report", timeout=30)
        assert r.status_code == 200


# --- Response shape ---
class TestResponseShape:
    def test_shape(self, super_admin):
        r = super_admin.get(f"{BASE}/super-admin/transcription-usage-report", timeout=30)
        assert r.status_code == 200
        data = r.json()
        # top-level keys
        assert set(data.keys()) >= {"items", "stats"}
        # stats keys
        stats = data["stats"]
        for k in ("total", "failed_count", "failure_rate_pct", "avg_latency_ms",
                  "avg_audio_duration_seconds", "warnings_count", "by_speech_model"):
            assert k in stats, f"missing stats.{k}"
        assert isinstance(stats["by_speech_model"], dict)
        assert isinstance(data["items"], list)
        # item keys (if any items)
        if data["items"]:
            item = data["items"][0]
            for k in ("meeting_id", "meeting_title", "org_id", "org_name",
                      "audio_duration_seconds", "transcript_has_warnings",
                      "failed", "processing_error", "speech_model_used",
                      "latency_ms", "transcribed_at"):
                assert k in item, f"missing item.{k}"

    def test_populated_row_present(self, super_admin):
        """Main agent seeded meeting 2f1cc088... with speech_model_used=universal-3-5-pro."""
        r = super_admin.get(f"{BASE}/super-admin/transcription-usage-report", timeout=30)
        items = r.json()["items"]
        seeded = [i for i in items if i["meeting_id"] == "2f1cc088-0687-48b9-9f40-1dabb5285640"]
        assert seeded, "seeded tracked meeting not in report"
        assert seeded[0]["speech_model_used"] == "universal-3-5-pro"
        assert seeded[0]["latency_ms"] is not None and seeded[0]["latency_ms"] > 0

    def test_older_rows_have_null_tracking(self, super_admin):
        """Legacy meetings pre-m034 should show null speech_model_used/latency_ms without breaking."""
        r = super_admin.get(f"{BASE}/super-admin/transcription-usage-report", timeout=30)
        items = r.json()["items"]
        null_model = [i for i in items if i["speech_model_used"] is None]
        # At least some legacy rows should be present (main agent said 22 historical items)
        assert len(null_model) > 0
        # And they shouldn't crash the response
        for i in null_model[:5]:
            assert i["failed"] is False or isinstance(i["failed"], bool)


# --- Filters ---
class TestFilters:
    def test_speech_model_filter(self, super_admin):
        r = super_admin.get(f"{BASE}/super-admin/transcription-usage-report",
                            params={"speech_model": "universal-3-5-pro"}, timeout=30)
        assert r.status_code == 200
        items = r.json()["items"]
        # every returned item must match the filter
        assert all(i["speech_model_used"] == "universal-3-5-pro" for i in items)
        assert len(items) >= 1  # our seeded row

    def test_speech_model_filter_unknown_returns_empty(self, super_admin):
        r = super_admin.get(f"{BASE}/super-admin/transcription-usage-report",
                            params={"speech_model": "nonexistent-model-xyz"}, timeout=30)
        assert r.status_code == 200
        assert r.json()["items"] == []
        assert r.json()["stats"]["total"] == 0

    def test_failed_only_filter(self, super_admin):
        r = super_admin.get(f"{BASE}/super-admin/transcription-usage-report",
                            params={"failed_only": "true"}, timeout=30)
        assert r.status_code == 200
        items = r.json()["items"]
        assert all(i["failed"] is True for i in items)

    def test_org_filter(self, super_admin):
        # Filter by Test Company org
        org_id = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"
        r = super_admin.get(f"{BASE}/super-admin/transcription-usage-report",
                            params={"org_id": org_id}, timeout=30)
        assert r.status_code == 200
        items = r.json()["items"]
        assert all(i["org_id"] == org_id for i in items)

    def test_org_filter_bogus(self, super_admin):
        r = super_admin.get(f"{BASE}/super-admin/transcription-usage-report",
                            params={"org_id": "00000000-0000-0000-0000-000000000000"}, timeout=30)
        assert r.status_code == 200
        assert r.json()["items"] == []

    def test_from_date_narrowing(self, super_admin):
        # Future date should return nothing
        future = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
        r = super_admin.get(f"{BASE}/super-admin/transcription-usage-report",
                            params={"from_date": future}, timeout=30)
        assert r.status_code == 200
        assert r.json()["items"] == []

    def test_to_date_narrowing(self, super_admin):
        # Very old to_date should return nothing
        r = super_admin.get(f"{BASE}/super-admin/transcription-usage-report",
                            params={"to_date": "2000-01-01T00:00:00"}, timeout=30)
        assert r.status_code == 200
        assert r.json()["items"] == []


# --- Stats math ---
class TestStats:
    def test_stats_math_consistent(self, super_admin):
        r = super_admin.get(f"{BASE}/super-admin/transcription-usage-report", timeout=30)
        data = r.json()
        stats = data["stats"]
        assert stats["total"] == len(data["items"])
        # by_speech_model counts should not exceed total
        assert sum(stats["by_speech_model"].values()) <= stats["total"]
        # failure_rate math
        if stats["total"]:
            expected = round(stats["failed_count"] / stats["total"] * 100, 1)
            assert abs(stats["failure_rate_pct"] - expected) < 0.1
