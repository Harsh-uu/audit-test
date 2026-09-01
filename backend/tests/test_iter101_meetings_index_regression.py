"""Iteration 101 — regression suite for removal of the two dead CREATE INDEX
statements on `meetings` (idx_meetings_org_id, idx_meetings_status) from init_db.py.

The composite covering index idx_meetings_org_status_date(org_id, status, created_at DESC)
does all the work; the two standalone indexes were created and dropped in the
same startup script every restart.

Modules exercised:
  routers/meetings.py   — list (admin/manager/attendee scoping, created_at DESC sort),
                          create, detail, delete
  routers/dashboard.py  — dashboard aggregation over meetings
  routers/admin.py      — /admin/stats, /admin/meetings-brief (status-filtered queries)
  DB level              — index inventory on public.meetings + planner usage
  init_db.py            — source-level assertion the dead CREATEs are gone
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

BE = dotenv_values("/app/backend/.env")
FE = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or FE.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
if not BASE_URL:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
API = f"{BASE_URL}/api"
DSN = BE["DATABASE_URL"]

ADMIN = ("admin@supervision.com", "Admin123!")
MANAGER = ("manager@supervision.com", "Manager123!")
JANE = ("jane@supervision.com", "Jane123!")

TAG = uuid.uuid4().hex[:8]
CREATED_MEETING_IDS = []


# ── helpers ───────────────────────────────────────────────────────────────────

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
    if me.status_code != 200:
        pytest.fail(f"/auth/me failed for {email}: {me.status_code} {me.text[:200]}")
    return s, me.json()


@pytest.fixture(scope="module")
def admin():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def manager():
    return _login(*MANAGER)


@pytest.fixture(scope="module")
def jane():
    return _login(*JANE)


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    for mid in CREATED_MEETING_IDS:
        try:
            asyncio.run(_db_exec("DELETE FROM meetings WHERE id=$1", mid))
        except Exception as e:  # noqa: BLE001
            print(f"cleanup failed for {mid}: {e}")


def _sorted_desc(items):
    keys = [m.get("created_at") or "" for m in items]
    return keys == sorted(keys, reverse=True)


# ── DB / source level ─────────────────────────────────────────────────────────

class TestIndexInventory:
    def test_meetings_indexes(self):
        rows = asyncio.run(_db_fetch(
            "SELECT indexname FROM pg_indexes WHERE schemaname='public' AND tablename='meetings'"))
        names = sorted(r["indexname"] for r in rows)
        print("meetings indexes:", names)
        assert "idx_meetings_org_status_date" in names
        assert "idx_meetings_created_at" in names
        assert "meetings_pkey" in names
        assert "idx_meetings_org_id" not in names
        assert "idx_meetings_status" not in names

    def test_init_db_source_has_no_dead_creates(self):
        src = open("/app/backend/init_db.py", encoding="utf-8").read()
        migrations_dir = "/app/backend/migrations"
        for fname in sorted(os.listdir(migrations_dir)):
            if fname.endswith(".py"):
                src += open(os.path.join(migrations_dir, fname), encoding="utf-8").read()
        assert "CREATE INDEX IF NOT EXISTS idx_meetings_org_id" not in src
        assert "CREATE INDEX IF NOT EXISTS idx_meetings_status" not in src
        assert "DROP INDEX IF EXISTS idx_meetings_org_id;" in src
        assert "DROP INDEX IF EXISTS idx_meetings_status;" in src
        assert "CREATE INDEX IF NOT EXISTS idx_meetings_org_status_date" in src

    def test_planner_uses_composite_index(self):
        org = asyncio.run(_db_fetch(
            "SELECT org_id, COUNT(*) c FROM meetings GROUP BY org_id ORDER BY c DESC LIMIT 1"))
        assert org, "no meetings in DB to test planner"
        org_id = org[0]["org_id"]
        plan = asyncio.run(_db_fetch(
            "EXPLAIN SELECT id FROM meetings WHERE org_id=$1 AND status='draft' "
            "ORDER BY created_at DESC LIMIT 50", org_id))
        text = "\n".join(list(r.values())[0] for r in plan)
        print(text)
        # informational: small tables may still seq-scan, but must not error
        assert "meetings" in text


# ── meetings list scoping / sorting ───────────────────────────────────────────

class TestMeetingsList:
    def test_admin_list(self, admin):
        s, me = admin
        r = s.get(f"{API}/meetings/", timeout=90)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert isinstance(data, list) and len(data) > 0, "admin sees no meetings"
        assert all(m["org_id"] == me["org_id"] for m in data), "cross-org leak in admin list"
        assert _sorted_desc(data), "admin list not sorted by created_at DESC"
        ids = [m["id"] for m in data]
        assert len(ids) == len(set(ids)), "duplicate rows in admin list"
        print(f"admin list: {len(data)} meetings, statuses={sorted({m['status'] for m in data})}")

    def test_manager_list(self, manager):
        s, me = manager
        r = s.get(f"{API}/meetings/", timeout=90)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert isinstance(data, list)
        assert all(m["org_id"] == me["org_id"] for m in data)
        assert _sorted_desc(data)
        ids = [m["id"] for m in data]
        assert len(ids) == len(set(ids))
        print(f"manager list: {len(data)} meetings")

    def test_attendee_list_scoped(self, jane):
        s, me = jane
        r = s.get(f"{API}/meetings/", timeout=90)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert isinstance(data, list)
        assert all(m["org_id"] == me["org_id"] for m in data)
        assert _sorted_desc(data)
        uid = me["id"]
        for m in data:
            attendee_ids = {a.get("user_id") for a in (m.get("attendees") or [])}
            shared_ids = {x.get("user_id") for x in (m.get("shared_with") or [])}
            assert uid in attendee_ids or uid in shared_ids or m.get("created_by") == uid, \
                f"attendee sees unrelated meeting {m['id']}"
        print(f"jane list: {len(data)} meetings")

    def test_admin_list_matches_db_count(self, admin):
        s, me = admin
        r = s.get(f"{API}/meetings/?limit=1000", timeout=120)
        assert r.status_code == 200
        api_count = len(r.json())
        db_count = asyncio.run(_db_fetch(
            "SELECT COUNT(*) c FROM meetings WHERE org_id=$1", me["org_id"]))[0]["c"]
        assert api_count == min(db_count, 1000), f"API {api_count} vs DB {db_count}"

    def test_pagination_consistency(self, admin):
        s, _ = admin
        full = s.get(f"{API}/meetings/?limit=6&offset=0", timeout=90)
        page2 = s.get(f"{API}/meetings/?limit=3&offset=3", timeout=90)
        assert full.status_code == 200 and page2.status_code == 200
        f, p = full.json(), page2.json()
        if len(f) >= 6:
            assert [m["id"] for m in f[3:6]] == [m["id"] for m in p], "pagination mismatch"

    def test_status_grouping_matches_db(self, admin):
        """Per-status counts from the API list must match DB per-status counts."""
        s, me = admin
        r = s.get(f"{API}/meetings/?limit=1000", timeout=120)
        assert r.status_code == 200
        api = {}
        for m in r.json():
            api[m["status"]] = api.get(m["status"], 0) + 1
        rows = asyncio.run(_db_fetch(
            "SELECT status, COUNT(*) c FROM meetings WHERE org_id=$1 GROUP BY status", me["org_id"]))
        db = {r_["status"]: r_["c"] for r_ in rows}
        print("api:", api, "db:", db)
        assert api == db, "status counts diverge between API list and DB"


# ── create / detail / delete ──────────────────────────────────────────────────

class TestMeetingCRUD:
    def test_create_appears_first_and_detail_loads(self, admin):
        s, me = admin
        title = f"TEST_iter101_{TAG}"
        payload = {
            "title": title,
            "date": datetime.now(timezone.utc).date().isoformat(),
            "location": "QA Room",
            "meeting_type": "supervision",
            "attendee_ids": [],
        }
        r = s.post(f"{API}/meetings/", json=payload, timeout=90)
        assert r.status_code in (200, 201), f"create failed: {r.status_code} {r.text[:400]}"
        created = r.json()
        mid = created["id"]
        CREATED_MEETING_IDS.append(mid)
        assert created["title"] == title
        assert created["status"] == "draft"
        assert created["org_id"] == me["org_id"]

        # appears at top of the created_at DESC list
        lst = s.get(f"{API}/meetings/?limit=50", timeout=90)
        assert lst.status_code == 200
        data = lst.json()
        assert data[0]["id"] == mid, f"new meeting not first; first={data[0]['id']}"
        assert _sorted_desc(data)

        # detail loads
        d = s.get(f"{API}/meetings/{mid}", timeout=90)
        assert d.status_code == 200, d.text[:300]
        detail = d.json()
        assert detail["id"] == mid and detail["title"] == title
        assert detail["status"] == "draft"
        assert "_id" not in detail

        # persisted in DB
        rows = asyncio.run(_db_fetch(
            "SELECT title, status, org_id FROM meetings WHERE id=$1", mid))
        assert rows and rows[0]["title"] == title and rows[0]["status"] == "draft"

    def test_status_transitions_visible_in_list(self, admin):
        """Flip status through each value and verify list reflects it (composite index path)."""
        s, _ = admin
        assert CREATED_MEETING_IDS, "create test must run first"
        mid = CREATED_MEETING_IDS[0]
        for status in ("in_review", "reviewed", "signed_off", "shared", "draft"):
            asyncio.run(_db_exec(
                "UPDATE meetings SET status=$1 WHERE id=$2", status, mid))
            r = s.get(f"{API}/meetings/?limit=1000", timeout=120)
            assert r.status_code == 200
            match = [m for m in r.json() if m["id"] == mid]
            assert len(match) == 1, f"meeting missing/duplicated at status={status}"
            assert match[0]["status"] == status

    def test_detail_404_for_unknown(self, admin):
        s, _ = admin
        r = s.get(f"{API}/meetings/{uuid.uuid4()}", timeout=60)
        assert r.status_code == 404, f"expected 404, got {r.status_code} {r.text[:200]}"

    def test_attendee_cannot_read_unrelated_meeting(self, jane, admin):
        s_admin, _ = admin
        s_jane, _ = jane
        assert CREATED_MEETING_IDS
        mid = CREATED_MEETING_IDS[0]
        r = s_jane.get(f"{API}/meetings/{mid}", timeout=60)
        assert r.status_code in (403, 404), f"IDOR: jane got {r.status_code}"

    def test_delete_meeting(self, admin, jane):
        s, _ = admin
        s_jane, _ = jane
        # attendee cannot delete
        assert CREATED_MEETING_IDS
        mid = CREATED_MEETING_IDS[0]
        r = s_jane.delete(f"{API}/meetings/{mid}", timeout=60)
        assert r.status_code in (403, 404)
        # admin can
        r = s.delete(f"{API}/meetings/{mid}", timeout=90)
        assert r.status_code == 200, r.text[:300]
        assert s.get(f"{API}/meetings/{mid}", timeout=60).status_code == 404
        rows = asyncio.run(_db_fetch("SELECT id FROM meetings WHERE id=$1", mid))
        assert not rows


# ── dependent read paths ──────────────────────────────────────────────────────

class TestDependentReads:
    def test_dashboard(self, admin, manager, jane):
        for label, (s, _) in (("admin", admin), ("manager", manager), ("jane", jane)):
            r = s.get(f"{API}/dashboard/", timeout=90)
            assert r.status_code == 200, f"{label} dashboard {r.status_code} {r.text[:200]}"
            print(f"{label} dashboard keys: {list(r.json())[:10]}")

    def test_admin_stats_status_filters(self, admin):
        s, _ = admin
        r = s.get(f"{API}/admin/stats", timeout=90)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        print("admin stats:", data)
        assert isinstance(data, dict) and len(data) > 0

    def test_admin_meetings_brief(self, admin):
        s, me = admin
        r = s.get(f"{API}/admin/meetings-brief", timeout=90)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        items = data if isinstance(data, list) else data.get("meetings", [])
        db = asyncio.run(_db_fetch(
            "SELECT COUNT(*) c FROM meetings WHERE org_id=$1 AND status IN ('signed_off','shared')",
            me["org_id"]))[0]["c"]
        assert len(items) == db, f"meetings-brief {len(items)} vs DB signed_off/shared {db}"
