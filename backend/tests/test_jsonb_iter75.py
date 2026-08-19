"""
Iteration 75 — verify ALL remaining JSONB write paths (fixed after iteration 74) now
store sound JSONB: real arrays/objects, and array ELEMENTS that are real objects
(not stringified JSON) for the `||` concat paths.

Covers:
  routers/recording.py  start / pause / resume(pause_start) / stop
  routers/org.py        PUT /api/org/branding, POST /api/org/branding/logo
  routers/admin.py      POST /admin/standards, PUT /admin/template,
                        POST /admin/meetings/{id}/add-attendee,
                        POST /admin/standards/upload -> parse_document_background
All state created here is cleaned up in teardown.
"""
import json
import struct
import time
import uuid
import zlib
from datetime import datetime, timezone

import pytest

from _iter75_helpers import BASE, ORG, all_elements_are_dicts, db, login

ADMIN_ID = "f72ac550-e6b8-4ffc-b2da-46a54a4c06d5"


@pytest.fixture(scope="module")
def admin():
    return login("admin@supervision.com", "Admin123!")


@pytest.fixture(scope="module")
def meeting():
    """Throw-away meeting used by the recording + add-attendee tests."""
    mid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    db(lambda c: c.execute(
        """INSERT INTO meetings (id, org_id, title, date, meeting_type, created_by, created_by_name,
                                 attendees, status, recording_events, paused_periods, created_at, updated_at)
           VALUES ($1,$2,$3,$4,'supervision',$5,'Test Admin',$6::jsonb,'draft','[]'::jsonb,'[]'::jsonb,$7,$7)""",
        mid, ORG, "TEST_ITER75 recording meeting", now[:10], ADMIN_ID,
        json.dumps([{"user_id": ADMIN_ID, "name": "Test Admin", "email": "admin@supervision.com",
                     "role": "admin", "present": True, "reviewed": False, "reviewed_at": None}]), now))
    yield mid
    db(lambda c: c.execute("DELETE FROM audit_logs WHERE meeting_id=$1", mid))
    db(lambda c: c.execute("DELETE FROM meetings WHERE id=$1", mid))


def _mtg(mid, col):
    return db(lambda c: c.fetchrow(
        f"SELECT jsonb_typeof({col}) AS t, {col} AS v FROM meetings WHERE id=$1", mid))


# ─────────────────────────── recording.py ───────────────────────────

def test_recording_start_writes_object_element(admin, meeting):
    r = admin.post(f"{BASE}/recording/{meeting}/start", json={}, timeout=60)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    row = _mtg(meeting, "recording_events")
    assert row["t"] == "array", f"recording_events jsonb_typeof={row['t']!r}"
    ok, why = all_elements_are_dicts(row["v"])
    assert ok, f"recording_events after start: {why}"
    ev = json.loads(row["v"]) if isinstance(row["v"], str) else row["v"]
    assert len(ev) == 1 and ev[0]["type"] == "started", ev


def test_recording_pause_appends_object_element(admin, meeting):
    r = admin.post(f"{BASE}/recording/{meeting}/pause", json={}, timeout=60)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    row = _mtg(meeting, "recording_events")
    assert row["t"] == "array"
    ok, why = all_elements_are_dicts(row["v"])
    assert ok, f"recording_events after pause: {why}"
    ev = json.loads(row["v"]) if isinstance(row["v"], str) else row["v"]
    assert [e["type"] for e in ev] == ["started", "paused"], ev


def test_recording_resume_writes_paused_periods_objects(admin, meeting):
    pause_start = "2026-07-01T10:00:00+00:00"
    r = admin.post(f"{BASE}/recording/{meeting}/resume",
                   json={"pause_start": pause_start,
                         "timestamp": "2026-07-01T10:00:30+00:00"}, timeout=60)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    ev_row = _mtg(meeting, "recording_events")
    ok, why = all_elements_are_dicts(ev_row["v"])
    assert ok, f"recording_events after resume: {why}"

    pp_row = _mtg(meeting, "paused_periods")
    assert pp_row["t"] == "array", f"paused_periods jsonb_typeof={pp_row['t']!r}"
    ok, why = all_elements_are_dicts(pp_row["v"])
    assert ok, f"paused_periods after resume: {why}"
    pp = json.loads(pp_row["v"]) if isinstance(pp_row["v"], str) else pp_row["v"]
    assert pp[0]["duration_seconds"] == 30, pp
    dur = db(lambda c: c.fetchval(
        "SELECT total_paused_duration_seconds FROM meetings WHERE id=$1", meeting))
    assert dur == 30, dur


def test_recording_stop_appends_object_element(admin, meeting):
    r = admin.post(f"{BASE}/recording/{meeting}/stop", json={}, timeout=60)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    row = _mtg(meeting, "recording_events")
    ok, why = all_elements_are_dicts(row["v"])
    assert ok, f"recording_events after stop: {why}"
    ev = json.loads(row["v"]) if isinstance(row["v"], str) else row["v"]
    assert [e["type"] for e in ev] == ["started", "paused", "resumed", "stopped"], ev


def test_recording_events_readback_via_api(admin, meeting):
    """GET /api/recording/{id}/events must return real event objects."""
    r = admin.get(f"{BASE}/recording/{meeting}/events", timeout=60)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    body = r.json()
    assert all(isinstance(e, dict) for e in body["recording_events"]), body["recording_events"]
    assert all(isinstance(p, dict) for p in body["paused_periods"]), body["paused_periods"]


# ─────────────────────────── org.py branding ───────────────────────────

def test_put_branding_stores_object(admin):
    before = db(lambda c: c.fetchval("SELECT branding::text FROM organisations WHERE id=$1", ORG))
    try:
        r = admin.put(f"{BASE}/org/branding", json={"primary_color": "#123456"}, timeout=60)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        t = db(lambda c: c.fetchval("SELECT jsonb_typeof(branding) FROM organisations WHERE id=$1", ORG))
        assert t == "object", f"organisations.branding jsonb_typeof={t!r} after PUT /api/org/branding"
        got = db(lambda c: c.fetchval("SELECT branding->>'primary_color' FROM organisations WHERE id=$1", ORG))
        assert got == "#123456", got
    finally:
        db(lambda c: c.execute("UPDATE organisations SET branding=$1::jsonb WHERE id=$2", before, ORG))


def test_put_branding_survives_legacy_double_encoded_value(admin):
    """Legacy rows still hold branding as a double-encoded JSON *string* (iter74 found 1).
    org.py's _jdict only decodes one level, so update_branding does
    `branding["primary_color"] = ...` on a str → TypeError → HTTP 500.
    """
    before = db(lambda c: c.fetchval("SELECT branding::text FROM organisations WHERE id=$1", ORG))
    try:
        # simulate a legacy double-encoded row (what iter74 found in prod data)
        db(lambda c: c.execute("UPDATE organisations SET branding=to_jsonb($1::text) WHERE id=$2",
                               json.dumps({"primary_color": "#abcdef"}), ORG))
        assert db(lambda c: c.fetchval(
            "SELECT jsonb_typeof(branding) FROM organisations WHERE id=$1", ORG)) == "string"
        r = admin.put(f"{BASE}/org/branding", json={"primary_color": "#654321"}, timeout=60)
        assert r.status_code == 200, (
            f"PUT /api/org/branding returned {r.status_code} on a legacy double-encoded "
            f"branding value: {r.text[:200]}")
    finally:
        db(lambda c: c.execute("UPDATE organisations SET branding=$1::jsonb WHERE id=$2", before, ORG))


def _png_bytes():
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\xff\xff")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def test_upload_logo_stores_object(admin):
    before = db(lambda c: c.fetchval("SELECT branding::text FROM organisations WHERE id=$1", ORG))
    try:
        r = admin.post(f"{BASE}/org/branding/logo",
                       files={"file": ("TEST_ITER75.png", _png_bytes(), "image/png")}, timeout=90)
        if r.status_code == 500 and "Storage" in r.text:
            pytest.skip(f"object storage unavailable: {r.text[:200]}")
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        t = db(lambda c: c.fetchval("SELECT jsonb_typeof(branding) FROM organisations WHERE id=$1", ORG))
        assert t == "object", f"organisations.branding jsonb_typeof={t!r} after logo upload"
        assert db(lambda c: c.fetchval("SELECT branding->>'logo_path' FROM organisations WHERE id=$1", ORG))
    finally:
        db(lambda c: c.execute("UPDATE organisations SET branding=$1::jsonb WHERE id=$2", before, ORG))


# ─────────────────────────── admin.py ───────────────────────────

def test_create_standard_stores_keywords_array(admin):
    std_id = None
    try:
        r = admin.post(f"{BASE}/admin/standards", json={
            "type": "custom", "reference": "TEST_ITER75", "name": "TEST_ iter75 standard",
            "description": "TEST", "keywords": ["alpha", "beta"], "source": "TEST",
        }, timeout=60)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        std_id = r.json()["id"]
        row = db(lambda c: c.fetchrow(
            "SELECT jsonb_typeof(keywords) AS t, keywords AS v FROM standards_entries WHERE id=$1", std_id))
        assert row["t"] == "array", f"standards_entries.keywords jsonb_typeof={row['t']!r}"
        kw = json.loads(row["v"]) if isinstance(row["v"], str) else row["v"]
        assert kw == ["alpha", "beta"], kw
    finally:
        if std_id:
            db(lambda c: c.execute("DELETE FROM standards_entries WHERE id=$1", std_id))


def test_save_template_stores_object(admin):
    key = f"supervision_template:{ORG}"
    before = db(lambda c: c.fetchval("SELECT data::text FROM settings WHERE id=$1", key))
    try:
        r = admin.put(f"{BASE}/admin/template", json={
            "name": "TEST_ITER75 template", "description": "TEST",
            "steps": [{"id": "s1", "title": "TEST step", "prompts": ["a"]}],
        }, timeout=60)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        row = db(lambda c: c.fetchrow(
            "SELECT jsonb_typeof(data) AS t, jsonb_typeof(data->'steps') AS st FROM settings WHERE id=$1", key))
        assert row["t"] == "object", f"settings.data jsonb_typeof={row['t']!r}"
        assert row["st"] == "array", f"settings.data->steps jsonb_typeof={row['st']!r}"
        # readback through the API
        g = admin.get(f"{BASE}/admin/template", timeout=60)
        assert g.status_code == 200
        assert isinstance(g.json().get("steps"), list)
    finally:
        if before is None:
            db(lambda c: c.execute("DELETE FROM settings WHERE id=$1", key))
        else:
            db(lambda c: c.execute("UPDATE settings SET data=$1::jsonb WHERE id=$2", before, key))


def test_repair_add_attendee_keeps_attendees_array(admin, meeting):
    r = admin.post(f"{BASE}/admin/meetings/{meeting}/add-attendee",
                   json={"user_email": "jane@supervision.com"}, timeout=60)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    row = _mtg(meeting, "attendees")
    assert row["t"] == "array", f"meetings.attendees jsonb_typeof={row['t']!r}"
    ok, why = all_elements_are_dicts(row["v"])
    assert ok, f"attendees after add-attendee: {why}"
    att = json.loads(row["v"]) if isinstance(row["v"], str) else row["v"]
    assert any(a["email"] == "jane@supervision.com" for a in att), att


def test_document_upload_parse_stores_criteria_array(admin):
    doc_text = (
        "TEST_ITER75 Care Quality Handbook\n\n"
        "1.1 Staff must record all medication administration accurately.\n"
        "1.2 Staff must complete safeguarding training annually.\n"
        "1.3 Care plans must be reviewed every six months with the person.\n"
    ).encode()
    doc_id = None
    try:
        r = admin.post(f"{BASE}/admin/standards/upload",
                       files={"file": ("TEST_ITER75.txt", doc_text, "text/plain")},
                       data={"label": "TEST_ITER75 doc"}, timeout=90)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        doc_id = r.json()["id"]
        status, err = None, None
        for _ in range(40):  # up to ~120s for the AI parse
            row = db(lambda c: c.fetchrow(
                "SELECT parse_status, parse_error FROM standards_documents WHERE id=$1", doc_id))
            status, err = row["parse_status"], row["parse_error"]
            if status != "parsing":
                break
            time.sleep(3)
        assert status == "parsed", f"parse_status={status!r} parse_error={err!r}"
        row = db(lambda c: c.fetchrow(
            "SELECT jsonb_typeof(extracted_criteria) AS t, criteria_count "
            "FROM standards_documents WHERE id=$1", doc_id))
        assert row["t"] == "array", f"standards_documents.extracted_criteria jsonb_typeof={row['t']!r}"
        assert row["criteria_count"] > 0
    finally:
        if doc_id:
            db(lambda c: c.execute("DELETE FROM standards_documents WHERE id=$1", doc_id))
