"""Iteration 150: retry logic in _ai_chat + initial_ai_provider column split.

Covers:
1. _ai_chat retries Gemini once on transient failure, then falls back to OpenAI.
2. _ai_chat skips retry on 'not configured' errors (goes straight to fallback).
3. GET /api/super-admin/ai-usage-report returns initial_ai_* fields + provider_changed_on_rescan.
4. Rescan does NOT overwrite initial_ai_* columns; only overwrites ai_*.
"""
import os
import sys
import asyncio
import uuid
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import requests
from dotenv import load_dotenv

# Load env before importing backend modules
sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else None
if not BASE_URL:
    # Fallback: read frontend env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL"):
                BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")

DATABASE_URL = os.environ["DATABASE_URL"]


# ─────────────────── UNIT TESTS: retry logic in _ai_chat ───────────────────

@pytest.mark.asyncio
async def test_retry_then_succeed_lands_on_gemini():
    """Gemini fails once, succeeds on retry → provider=gemini, no fallback."""
    from utils import ai as ai_mod

    call_count = {"n": 0}

    async def fake_gemini(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("transient network blip")
        return '{"ok": true}'

    with patch.object(ai_mod, "_gemini_chat", side_effect=fake_gemini), \
         patch.object(ai_mod.asyncio, "sleep", new=AsyncMock()):  # skip 1.5s wait
        tracker = {}
        result = await ai_mod._ai_chat("gpt-4o", "sys", "user", tracker=tracker)

    assert result == '{"ok": true}'
    assert call_count["n"] == 2, "Should have retried once"
    assert tracker["provider"] == "gemini-2.5-flash"
    assert tracker["fallback_used"] is False
    assert tracker["fallback_reason"] is None


@pytest.mark.asyncio
async def test_retry_then_fail_falls_back_to_openai():
    """Gemini fails twice → falls back to OpenAI."""
    from utils import ai as ai_mod

    call_count = {"gemini": 0, "openai": 0}

    async def fake_gemini(*args, **kwargs):
        call_count["gemini"] += 1
        raise RuntimeError("transient network blip")

    async def fake_openai(model, *args, **kwargs):
        call_count["openai"] += 1
        return '{"served_by": "openai"}'

    with patch.object(ai_mod, "_gemini_chat", side_effect=fake_gemini), \
         patch.object(ai_mod, "_openai_chat", side_effect=fake_openai), \
         patch.object(ai_mod.asyncio, "sleep", new=AsyncMock()):
        tracker = {}
        result = await ai_mod._ai_chat("gpt-4o", "sys", "user", tracker=tracker)

    assert result == '{"served_by": "openai"}'
    assert call_count["gemini"] == 2, "Should have retried once before falling back"
    assert call_count["openai"] == 1
    assert tracker["provider"] == "gpt-4o"
    assert tracker["fallback_used"] is True
    assert "transient network blip" in tracker["fallback_reason"]


@pytest.mark.asyncio
async def test_not_configured_skips_retry():
    """When error contains 'not configured', do NOT retry — go straight to fallback."""
    from utils import ai as ai_mod

    call_count = {"gemini": 0, "openai": 0, "sleep": 0}

    async def fake_gemini(*args, **kwargs):
        call_count["gemini"] += 1
        raise ValueError("Vertex AI not configured (missing GCP_PROJECT_ID/GCP_LOCATION/GCP_SERVICE_ACCOUNT_JSON)")

    async def fake_openai(model, *args, **kwargs):
        call_count["openai"] += 1
        return "ok"

    async def fake_sleep(*_a, **_kw):
        call_count["sleep"] += 1

    with patch.object(ai_mod, "_gemini_chat", side_effect=fake_gemini), \
         patch.object(ai_mod, "_openai_chat", side_effect=fake_openai), \
         patch.object(ai_mod.asyncio, "sleep", side_effect=fake_sleep):
        tracker = {}
        await ai_mod._ai_chat("gpt-4o", "sys", "user", tracker=tracker)

    assert call_count["gemini"] == 1, "Config error must NOT retry"
    assert call_count["sleep"] == 0, "No 1.5s delay wasted on config error"
    assert call_count["openai"] == 1
    assert tracker["fallback_used"] is True
    assert "not configured" in tracker["fallback_reason"]


# ─────────────────── DB + API TESTS: initial_ai_provider column split ───────────────────

@pytest.fixture(scope="module")
def super_admin_cookies():
    """Login as super admin using the get_tokens helper flow."""
    # Use raw HTTP + direct MFA override
    import bcrypt
    import psycopg2
    from datetime import timedelta

    # Login
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": "superadmin@1two.one", "password": "TestPass123!"})
    if r.status_code != 200:
        # Clear rate limit and retry
        with psycopg2.connect(DATABASE_URL) as pg:
            with pg.cursor() as cur:
                cur.execute("DELETE FROM login_attempts WHERE identifier LIKE 'mfa_send:%'")
                pg.commit()
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": "superadmin@1two.one", "password": "TestPass123!"})
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text[:300]}"
    body = r.json()
    mfa_session = body.get("mfa_session")
    assert mfa_session, "No mfa_session in login response"

    # Override MFA code to bcrypt('123456')
    code_hash = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    with psycopg2.connect(DATABASE_URL) as pg:
        with pg.cursor() as cur:
            cur.execute("UPDATE users SET mfa_code=%s, mfa_code_expires_at=%s WHERE email='superadmin@1two.one'",
                        (code_hash, expires))
            pg.commit()

    r = requests.post(f"{BASE_URL}/api/auth/verify-mfa",
                      json={"mfa_session": mfa_session, "code": "123456"})
    assert r.status_code == 200, f"MFA verify failed: {r.status_code} {r.text[:300]}"
    return r.cookies


def test_ai_usage_report_returns_new_fields(super_admin_cookies):
    """Report must include initial_* fields per row + provider_changed_on_rescan_count stat."""
    r = requests.get(f"{BASE_URL}/api/super-admin/ai-usage-report",
                     cookies=super_admin_cookies)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    data = r.json()
    assert "items" in data and "stats" in data
    # Stat must exist
    assert "provider_changed_on_rescan_count" in data["stats"]
    assert isinstance(data["stats"]["provider_changed_on_rescan_count"], int)
    # If items exist, they must include the new fields
    for item in data["items"]:
        for f in ("initial_ai_provider", "initial_ai_fallback_used",
                  "initial_ai_fallback_reason", "initial_ai_latency_ms",
                  "provider_changed_on_rescan"):
            assert f in item, f"Missing field '{f}' in item"
        assert isinstance(item["provider_changed_on_rescan"], bool)


def test_provider_changed_on_rescan_flag_correctness(super_admin_cookies):
    """Seed a row: initial=gpt-4o (fallback), latest=gemini, rescanned_at=now → flag TRUE.
    Also seed a never-rescanned row → flag FALSE. Verify both, then clean up."""
    import psycopg2
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Find an existing analysis row we can safely mutate + restore
    cur.execute("SELECT id, meeting_id, org_id, ai_provider, ai_fallback_used, ai_fallback_reason, ai_latency_ms, rescanned_at, initial_ai_provider, initial_ai_fallback_used, initial_ai_fallback_reason, initial_ai_latency_ms FROM analyses LIMIT 2")
    rows = cur.fetchall()
    if len(rows) < 2:
        pytest.skip("Need at least 2 analyses rows to test flag logic")
    row_changed, row_unchanged = rows[0], rows[1]
    id_changed, id_unchanged = row_changed[0], row_unchanged[0]
    # Save originals for restore
    original_changed = row_changed
    original_unchanged = row_unchanged

    try:
        # Row 1: simulate rescan changing provider
        cur.execute("""UPDATE analyses SET
                       ai_provider='gemini-2.5-flash', ai_fallback_used=FALSE, ai_fallback_reason=NULL, ai_latency_ms=5000,
                       rescanned_at=NOW(),
                       initial_ai_provider='gpt-4o', initial_ai_fallback_used=TRUE,
                       initial_ai_fallback_reason='transient blip', initial_ai_latency_ms=6000
                       WHERE id=%s""", (id_changed,))
        # Row 2: never rescanned, initial matches latest
        cur.execute("""UPDATE analyses SET
                       ai_provider='gemini-2.5-flash', ai_fallback_used=FALSE, ai_fallback_reason=NULL, ai_latency_ms=4000,
                       rescanned_at=NULL,
                       initial_ai_provider='gemini-2.5-flash', initial_ai_fallback_used=FALSE,
                       initial_ai_fallback_reason=NULL, initial_ai_latency_ms=4000
                       WHERE id=%s""", (id_unchanged,))
        conn.commit()

        r = requests.get(f"{BASE_URL}/api/super-admin/ai-usage-report",
                         cookies=super_admin_cookies)
        assert r.status_code == 200
        data = r.json()
        items = {i["analysis_id"]: i for i in data["items"]}

        assert str(id_changed) in items, "seeded changed row missing"
        assert str(id_unchanged) in items, "seeded unchanged row missing"

        chg = items[str(id_changed)]
        assert chg["provider_changed_on_rescan"] is True
        assert chg["initial_ai_provider"] == "gpt-4o"
        assert chg["ai_provider"] == "gemini-2.5-flash"
        assert chg["rescanned_at"] is not None

        unc = items[str(id_unchanged)]
        assert unc["provider_changed_on_rescan"] is False
        assert unc["rescanned_at"] is None
        assert unc["initial_ai_provider"] == "gemini-2.5-flash"

        # Stat aggregate should include the seeded changed row
        assert data["stats"]["provider_changed_on_rescan_count"] >= 1
    finally:
        # Restore originals
        cur.execute("""UPDATE analyses SET
                       ai_provider=%s, ai_fallback_used=%s, ai_fallback_reason=%s, ai_latency_ms=%s,
                       rescanned_at=%s, initial_ai_provider=%s, initial_ai_fallback_used=%s,
                       initial_ai_fallback_reason=%s, initial_ai_latency_ms=%s
                       WHERE id=%s""",
                    (original_changed[3], original_changed[4], original_changed[5], original_changed[6],
                     original_changed[7], original_changed[8], original_changed[9],
                     original_changed[10], original_changed[11], id_changed))
        cur.execute("""UPDATE analyses SET
                       ai_provider=%s, ai_fallback_used=%s, ai_fallback_reason=%s, ai_latency_ms=%s,
                       rescanned_at=%s, initial_ai_provider=%s, initial_ai_fallback_used=%s,
                       initial_ai_fallback_reason=%s, initial_ai_latency_ms=%s
                       WHERE id=%s""",
                    (original_unchanged[3], original_unchanged[4], original_unchanged[5], original_unchanged[6],
                     original_unchanged[7], original_unchanged[8], original_unchanged[9],
                     original_unchanged[10], original_unchanged[11], id_unchanged))
        conn.commit()
        cur.close()
        conn.close()


def test_rescan_sql_only_touches_latest_columns():
    """Static check: the rescan UPDATE statement in routers/review.py MUST NOT touch
    the initial_* columns. This is the key regression guard."""
    with open("/app/backend/routers/review.py") as f:
        source = f.read()
    # Find the rescan UPDATE
    marker = "AI provider tracking (Super Admin AI Usage report) — a rescan"
    idx = source.find(marker)
    assert idx != -1, "Could not locate rescan ai_provider update block"
    block = source[idx:idx + 800]
    assert "initial_ai_provider" not in block, \
        "rescan UPDATE must NOT touch initial_ai_provider column"
    assert "initial_ai_fallback_used" not in block
    assert "initial_ai_latency_ms" not in block


def test_transcription_pipeline_sets_both_ai_and_initial_ai():
    """Static check: the pipeline INSERT/UPDATE must set BOTH ai_* and initial_ai_* columns."""
    with open("/app/backend/utils/transcription_pipeline.py") as f:
        source = f.read()
    assert "initial_ai_provider" in source, "pipeline must populate initial_ai_provider"
    assert "initial_ai_fallback_used" in source
    assert "initial_ai_latency_ms" in source
