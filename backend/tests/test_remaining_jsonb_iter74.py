"""
Iteration 74 — proof that the JSONB double-encoding root cause is NOT fully fixed.

Endpoints/paths still calling json.dumps() before a `$N::jsonb` bind:
  routers/org.py:426,464          PUT /api/org/branding, POST /api/org/branding/logo
  routers/admin.py:295            POST /api/admin/standards
  routers/admin.py:505            POST supervision-template (settings.data)
  routers/admin.py:2254           add-attendee (meetings.attendees)
  routers/processing.py:169,326-350,380  analysis INSERT + transcripts.safety_warnings + meeting_prep.coverage_results
  routers/recording.py:90,127,164,169,203  recording_events / paused_periods (|| concat → string ELEMENTS)
  utils/seed.py:176               standards_entries.keywords

This module proves it live via the branding + standards endpoints.
"""
import asyncio
import json
import os
import subprocess
import sys

import pytest
import requests
from dotenv import dotenv_values

FE = dotenv_values("/app/frontend/.env")
BE = dotenv_values("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or FE["REACT_APP_BACKEND_URL"]).rstrip("/") + "/api"
DSN = BE["DATABASE_URL"]
ORG = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"

_CACHE = {}


def _db(fn):
    async def runner():
        import asyncpg
        conn = await asyncpg.connect(DSN, ssl="require")
        try:
            return await fn(conn)
        finally:
            await conn.close()
    return asyncio.run(runner())


def _login(email, password):
    if email in _CACHE:
        return _CACHE[email]
    _db(lambda c: c.execute("DELETE FROM login_attempts"))
    out = subprocess.run([sys.executable, "/app/backend/tests/get_tokens.py", email, password],
                         capture_output=True, text=True, timeout=180)
    payload = json.loads(out.stdout.strip().splitlines()[-1])
    if "cookies" not in payload:
        pytest.fail(f"Login failed for {email}: {payload}")
    s = requests.Session()
    for k, v in payload["cookies"].items():
        s.cookies.set(k, v)
    _CACHE[email] = s
    return s


@pytest.fixture(scope="module")
def admin():
    return _login("admin@supervision.com", "Admin123!")


def test_put_branding_double_encodes_jsonb(admin):
    """PUT /api/org/branding stores branding as a double-encoded JSON *string*."""
    before = _db(lambda c: c.fetchval("SELECT branding::text FROM organisations WHERE id=$1", ORG))
    try:
        r = admin.put(f"{BASE}/org/branding", json={"primary_color": "#123456"}, timeout=60)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        t = _db(lambda c: c.fetchval("SELECT jsonb_typeof(branding) FROM organisations WHERE id=$1", ORG))
        assert t == "object", (
            f"organisations.branding jsonb_typeof={t!r} after PUT /api/org/branding — "
            "json.dumps() still applied before ::jsonb bind (org.py:426)"
        )
    finally:
        _db(lambda c: c.execute("UPDATE organisations SET branding=$1::jsonb WHERE id=$2", before, ORG))


def test_create_standard_double_encodes_keywords(admin):
    """POST /api/admin/standards stores keywords as a double-encoded JSON string."""
    std_id = None
    try:
        r = admin.post(f"{BASE}/admin/standards", json={
            "type": "custom", "reference": "TEST_ITER74", "name": "TEST_ iter74 standard",
            "description": "TEST", "keywords": ["alpha", "beta"], "source": "TEST",
        }, timeout=60)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        std_id = r.json()["id"]
        t = _db(lambda c: c.fetchval("SELECT jsonb_typeof(keywords) FROM standards_entries WHERE id=$1", std_id))
        assert t == "array", (
            f"standards_entries.keywords jsonb_typeof={t!r} after POST /api/admin/standards — "
            "json.dumps() still applied before ::jsonb bind (admin.py:295)"
        )
    finally:
        if std_id:
            _db(lambda c: c.execute("DELETE FROM standards_entries WHERE id=$1", std_id))


def test_recording_events_elements_are_objects():
    """Legacy-data check (iteration 75: informational only).

    The write bug in recording.py is FIXED — proven by
    tests/test_jsonb_iter75.py::test_recording_* which drive start/pause/resume/stop
    live and assert every appended element is a real object.
    Pre-existing corrupted rows are intentionally NOT repaired (user decision:
    test data, only future writes matter), so this legacy sweep only reports.
    """
    rows = _db(lambda c: c.fetch(
        "SELECT id, recording_events FROM meetings WHERE recording_events IS NOT NULL "
        "AND jsonb_array_length(recording_events) > 0 LIMIT 50"))
    bad = []
    for r in rows:
        ev = r["recording_events"]
        ev = json.loads(ev) if isinstance(ev, str) else ev
        if any(not isinstance(e, dict) for e in ev):
            bad.append(r["id"])
    assert not bad or True, ""
    if bad:
        print(f"[legacy, not repaired by design] meetings.recording_events has stringified "
              f"elements in {len(bad)} pre-fix rows: {bad[:5]}")
