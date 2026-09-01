"""Iteration 107c — empty-string / malformed date input probes against endpoints that
write or filter on now-TIMESTAMPTZ columns. Goal: any 500 (should be 4xx)."""
import asyncio
import sys
from datetime import datetime, timedelta, timezone

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values, load_dotenv

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")
BE = dotenv_values("/app/backend/.env")
FE = dotenv_values("/app/frontend/.env")
BASE = FE["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = BE["DATABASE_URL"]
P = "TEST_iter107c_"


def db(fn):
    async def run():
        c = await asyncpg.connect(DSN)
        try:
            return await fn(c)
        finally:
            await c.close()
    return asyncio.new_event_loop().run_until_complete(run())


@pytest.fixture(scope="session")
def admin_s():
    db(lambda c: c.execute("DELETE FROM login_attempts"))
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": "admin@supervision.com", "password": "Admin123!"}, timeout=90)
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    if d.get("requires_mfa"):
        h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
        exp = datetime.now(timezone.utc) + timedelta(minutes=10)
        db(lambda c: c.execute(
            "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
            h, exp, "admin@supervision.com"))
        r2 = s.post(f"{BASE}/auth/verify-mfa", json={"mfa_session": d["mfa_session"], "code": "123456"}, timeout=90)
        assert r2.status_code == 200, r2.text[:300]
    return s


@pytest.mark.parametrize("q", [
    "?date_from=&date_to=",
    "?date_from=not-a-date",
    "?date_from=2026-13-45",
    "?date_to=''",
])
def test_meetings_date_filter_bad_input_no_500(admin_s, q):
    r = admin_s.get(f"{BASE}/meetings/{q}", timeout=90)
    assert r.status_code != 500, f"{q} -> 500: {r.text[:300]}"
    print(q, "->", r.status_code)


@pytest.mark.parametrize("date_val", ["", "not-a-date", "2026-13-45"])
def test_create_meeting_bad_date_no_500(admin_s, date_val):
    r = admin_s.post(f"{BASE}/meetings/", json={"title": P + "bad", "date": date_val,
                                                "meeting_type": "supervision"}, timeout=90)
    print(repr(date_val), "->", r.status_code, r.text[:150])
    if r.status_code in (200, 201):
        mid = r.json().get("id")
        if mid:
            admin_s.delete(f"{BASE}/meetings/{mid}", timeout=90)
    assert r.status_code != 500, f"date={date_val!r} -> 500: {r.text[:300]}"


@pytest.mark.parametrize("payload", [
    {"frequency": "monthly", "start_date": ""},
    {"frequency": "monthly", "start_date": "not-a-date"},
])
def test_schedule_bad_start_date_no_500(admin_s, payload):
    mt = admin_s.get(f"{BASE}/schedules/meeting-types", timeout=90)
    if mt.status_code != 200:
        pytest.skip(f"meeting-types unavailable: {mt.status_code}")
    body = mt.json()
    types = body if isinstance(body, list) else body.get("meeting_types", [])
    if not types:
        pytest.skip("no meeting types")
    uid = db(lambda c: c.fetchval("SELECT id FROM users WHERE email='user@supervision.com'"))
    full = {"staff_user_id": uid, "meeting_type_id": types[0]["id"], **payload}
    r = admin_s.post(f"{BASE}/schedules/", json=full, timeout=90)
    print(payload, "->", r.status_code, r.text[:150])
    if r.status_code in (200, 201):
        sid = r.json().get("id")
        if sid:
            admin_s.delete(f"{BASE}/schedules/{sid}", timeout=90)
    assert r.status_code != 500, f"{payload} -> 500: {r.text[:300]}"


def test_team_insights_bad_date_range_no_500(admin_s):
    for q in ("?date_from=&date_to=", "?date_from=bogus"):
        r = admin_s.get(f"{BASE}/admin/team-insights{q}", timeout=180)
        print("team-insights", q, "->", r.status_code)
        assert r.status_code != 500, f"{q} -> 500: {r.text[:300]}"
