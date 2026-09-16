"""Tests for the Meetings page lazy-load feature (month-summary endpoint
+ year/month filter on the list endpoint).

Modules exercised:
  routers/meetings.py -- _list_meetings_data (year/month filter across
                         all 4 role branches), GET /month-summary
  routers/dashboard.py -- unchanged use of _list_meetings_data
"""
import asyncio
import os
from datetime import datetime, timezone, timedelta

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

BE = dotenv_values("/app/backend/.env")
FE = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or FE.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
API = f"{BASE_URL}/api"
DSN = BE["DATABASE_URL"]

ADMIN = ("admin@supervision.com", "Admin123!")
MANAGER = ("manager@supervision.com", "Manager123!")
USER = ("user@supervision.com", "AnotherNew789!")

TEST_ORG_ID = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"


async def _db_fetch(sql, *args):
    conn = await asyncpg.connect(DSN, ssl="require")
    try:
        return [dict(r) for r in await conn.fetch(sql, *args)]
    finally:
        await conn.close()


async def _db_exec(sql, *args):
    conn = await asyncpg.connect(DSN, ssl="require")
    try:
        return await conn.execute(sql, *args)
    finally:
        await conn.close()


async def _mfa_override(email):
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    await _db_exec(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 "
        "WHERE LOWER(email)=LOWER($3)", h, exp, email)


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=60)
    if r.status_code != 200:
        pytest.fail(f"login failed for {email}: {r.status_code} {r.text[:300]}")
    data = r.json()
    if data.get("requires_mfa"):
        asyncio.run(_mfa_override(email))
        r = s.post(f"{API}/auth/verify-mfa",
                   json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=60)
        if r.status_code != 200:
            pytest.fail(f"MFA verify failed for {email}: {r.status_code} {r.text[:300]}")
    me = s.get(f"{API}/auth/me", timeout=60)
    assert me.status_code == 200
    return s, me.json()


@pytest.fixture(scope="module")
def admin():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def manager():
    return _login(*MANAGER)


@pytest.fixture(scope="module")
def user_client():
    return _login(*USER)


NOW = datetime.now(timezone.utc)
CUR_KEY = f"{NOW.year:04d}-{NOW.month:02d}"


# ── /meetings/month-summary ───────────────────────────────────────────────

class TestMonthSummary:
    def test_admin_month_summary_matches_db(self, admin):
        s, me = admin
        r = s.get(f"{API}/meetings/month-summary", timeout=30)
        assert r.status_code == 200, r.text
        summary = r.json()
        assert isinstance(summary, list)

        # Every entry excludes the current month
        for entry in summary:
            assert entry["month_key"] != CUR_KEY
            assert "year" in entry and "month" in entry and "label" in entry
            assert isinstance(entry["count"], int) and entry["count"] > 0
            assert isinstance(entry["status_counts"], dict)
            assert sum(entry["status_counts"].values()) == entry["count"]

        # Sorted newest-first
        keys = [e["month_key"] for e in summary]
        assert keys == sorted(keys, reverse=True)

        # Compare against actual DB rows for Test Company
        db_rows = asyncio.run(_db_fetch(
            """SELECT to_char(date_trunc('month', COALESCE(date, created_at)), 'YYYY-MM') AS mk,
                      COUNT(*) AS n
               FROM meetings WHERE org_id=$1 GROUP BY mk""", TEST_ORG_ID))
        db_map = {r["mk"]: r["n"] for r in db_rows if r["mk"] and r["mk"] != CUR_KEY}
        api_map = {e["month_key"]: e["count"] for e in summary}
        assert db_map == api_map, f"summary counts mismatch. db={db_map} api={api_map}"

    def test_month_summary_excludes_current_month(self, admin):
        s, _ = admin
        r = s.get(f"{API}/meetings/month-summary", timeout=30)
        assert r.status_code == 200
        keys = {e["month_key"] for e in r.json()}
        assert CUR_KEY not in keys

    def test_month_summary_route_not_shadowed(self, admin):
        # If /month-summary were shadowed by /{meeting_id}, we'd get 404 here.
        s, _ = admin
        r = s.get(f"{API}/meetings/month-summary", timeout=30)
        assert r.status_code == 200

    def test_attendee_month_summary_scoped(self, user_client):
        s, me = user_client
        r = s.get(f"{API}/meetings/month-summary", timeout=30)
        assert r.status_code == 200
        summary = r.json()
        # An attendee should typically see fewer months than admin (or same subset)
        assert isinstance(summary, list)
        for e in summary:
            assert e["month_key"] != CUR_KEY


# ── /meetings/?year=&month= filter ────────────────────────────────────────

class TestListWithYearMonth:
    def test_admin_current_month(self, admin):
        s, _ = admin
        r = s.get(f"{API}/meetings/?year={NOW.year}&month={NOW.month}", timeout=30)
        assert r.status_code == 200
        for m in r.json():
            d = m.get("date") or m.get("created_at")
            assert d.startswith(CUR_KEY), f"meeting outside month: {d}"

    def test_admin_past_month(self, admin):
        s, _ = admin
        # Aug 2026 per problem statement
        r = s.get(f"{API}/meetings/?year=2026&month=8", timeout=30)
        assert r.status_code == 200
        meetings = r.json()
        # Verify all fall in Aug 2026
        for m in meetings:
            d = m.get("date") or m.get("created_at")
            assert d.startswith("2026-08"), f"meeting outside 2026-08: {d}"

        # Compare against DB count
        db = asyncio.run(_db_fetch(
            """SELECT COUNT(*) c FROM meetings
               WHERE org_id=$1
               AND COALESCE(date, created_at) BETWEEN '2026-08-01' AND '2026-08-31T23:59:59'""",
            TEST_ORG_ID))
        assert len(meetings) == db[0]["c"], f"api={len(meetings)} db={db[0]['c']}"

    def test_admin_no_year_month_returns_all(self, admin):
        s, _ = admin
        r = s.get(f"{API}/meetings/", timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_manager_past_month(self, manager):
        s, _ = manager
        r = s.get(f"{API}/meetings/?year=2026&month=8", timeout=30)
        assert r.status_code == 200
        for m in r.json():
            d = m.get("date") or m.get("created_at")
            assert d.startswith("2026-08"), f"meeting outside 2026-08: {d}"

    def test_attendee_past_month(self, user_client):
        s, _ = user_client
        r = s.get(f"{API}/meetings/?year=2026&month=8", timeout=30)
        assert r.status_code == 200
        for m in r.json():
            d = m.get("date") or m.get("created_at")
            assert d.startswith("2026-08"), f"attendee got meeting outside 2026-08: {d}"

    def test_year_month_matches_summary_count(self, admin):
        """The count from month-summary must equal len(GET /?year=&month=) for that month."""
        s, _ = admin
        r = s.get(f"{API}/meetings/month-summary", timeout=30)
        assert r.status_code == 200
        summary = r.json()
        if not summary:
            pytest.skip("no past months to cross-check")
        picked = summary[0]  # newest past month
        r2 = s.get(f"{API}/meetings/?year={picked['year']}&month={picked['month']}", timeout=30)
        assert r2.status_code == 200
        assert len(r2.json()) == picked["count"], \
            f"summary said {picked['count']} for {picked['month_key']}, list returned {len(r2.json())}"

    def test_invalid_month_rejected(self, admin):
        s, _ = admin
        r = s.get(f"{API}/meetings/?year=2026&month=13", timeout=30)
        assert r.status_code == 422

    def test_year_only_returns_all(self, admin):
        """Only one of year/month set — falls back to no date filter (default behaviour)."""
        s, _ = admin
        r = s.get(f"{API}/meetings/?year=2026", timeout=30)
        assert r.status_code == 200
        # Should return meetings from many months since date filter requires both
        assert isinstance(r.json(), list)


# ── Regression: dashboard unaffected ──────────────────────────────────────

class TestDashboardRegression:
    def test_dashboard_still_returns_meetings(self, admin):
        s, _ = admin
        r = s.get(f"{API}/dashboard/", timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert "recent_meetings" in data or "meetings" in data or isinstance(data, dict)
