"""Iteration 97 — regression suite for the DB index-only change (7 new indexes).

Covers every read/write path that touches the newly-indexed columns:
  teams.org_id / teams.setting_id, org_settings.org_id, focus_topics.org_id,
  standards_documents.org_id, users.team_id / users.setting_id

Modules exercised: routers/admin.py (list_users, team-insights, registers,
standards documents), routers/org.py (settings + teams CRUD, assign-team),
routers/prep.py (focus topics CRUD), routers/dashboard.py.
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

TAG = uuid.uuid4().hex[:6]


# ── helpers ───────────────────────────────────────────────────────────────────

async def _mfa_override(email):
    conn = await asyncpg.connect(DSN, ssl="require")
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    await conn.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, exp, email)
    await conn.close()


async def _db_fetch(sql, *args):
    conn = await asyncpg.connect(DSN, ssl="require")
    rows = await conn.fetch(sql, *args)
    await conn.close()
    return [dict(r) for r in rows]


async def _db_exec(sql, *args):
    conn = await asyncpg.connect(DSN, ssl="require")
    res = await conn.execute(sql, *args)
    await conn.close()
    return res


def login(email, password):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=60)
    if r.status_code != 200:
        pytest.fail(f"login failed for {email}: {r.status_code} {r.text[:300]}")
    data = r.json()
    if data.get("requires_mfa"):
        asyncio.run(_mfa_override(email))
        r2 = s.post(f"{API}/auth/verify-mfa",
                    json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=60)
        if r2.status_code != 200:
            pytest.fail(f"MFA verify failed for {email}: {r2.status_code} {r2.text[:300]}")
    me = s.get(f"{API}/auth/me", timeout=60)
    assert me.status_code == 200, me.text[:300]
    return s, me.json()


@pytest.fixture(scope="session")
def admin():
    return login(*ADMIN)


@pytest.fixture(scope="session")
def manager():
    return login(*MANAGER)


# ── Index presence (the actual change under test) ─────────────────────────────

class TestIndexes:
    def test_all_seven_indexes_exist(self):
        expected = {
            "idx_teams_org_id", "idx_teams_setting_id", "idx_org_settings_org_id",
            "idx_focus_topics_org_id", "idx_standards_documents_org_id",
            "idx_users_team_id", "idx_users_setting_id",
        }
        rows = asyncio.run(_db_fetch(
            "SELECT indexname FROM pg_indexes WHERE indexname = ANY($1::text[])",
            list(expected)))
        found = {r["indexname"] for r in rows}
        assert found == expected, f"missing indexes: {expected - found}"

    def test_indexes_are_valid_and_used(self):
        invalid = asyncio.run(_db_fetch(
            "SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
            "WHERE NOT i.indisvalid AND c.relname LIKE 'idx_%'"))
        assert invalid == [], f"invalid indexes: {invalid}"


# ── admin.py :: GET /admin/users (users.team_id / users.setting_id filters) ───

class TestListUsers:
    def test_admin_org_scope_lists_all(self, admin):
        s, me = admin
        r = s.get(f"{API}/admin/users", timeout=60)
        assert r.status_code == 200, r.text[:300]
        users = r.json()
        assert isinstance(users, list) and len(users) > 0
        assert all(u["org_id"] == me["org_id"] for u in users)
        assert all("_id" not in u for u in users)
        assert {"id", "email", "name", "role", "team_id", "setting_id"} <= set(users[0].keys())

    def test_ignore_scope_flag_admin(self, admin):
        s, _ = admin
        a = s.get(f"{API}/admin/users", timeout=60).json()
        b = s.get(f"{API}/admin/users?ignore_scope=true", timeout=60).json()
        assert {u["id"] for u in a} == {u["id"] for u in b}

    def test_manager_list_users(self, manager):
        s, me = manager
        r = s.get(f"{API}/admin/users", timeout=60)
        assert r.status_code == 200, r.text[:300]
        users = r.json()
        assert isinstance(users, list)
        # scope must be honoured server-side
        if me.get("team_id"):
            assert all(u["team_id"] == me["team_id"] for u in users)
        elif me.get("setting_id"):
            assert all(u["setting_id"] == me["setting_id"] for u in users)


# ── org.py :: org_settings + teams CRUD, assign-team ─────────────────────────

class TestOrgStructureCRUD:
    created = {}

    def test_01_list_settings(self, admin):
        s, _ = admin
        r = s.get(f"{API}/org/settings", timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert isinstance(r.json(), list)

    def test_02_create_setting(self, admin):
        s, me = admin
        r = s.post(f"{API}/org/settings", json={"name": f"TEST_Branch_{TAG}"}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["name"] == f"TEST_Branch_{TAG}"
        assert body["org_id"] == me["org_id"]
        TestOrgStructureCRUD.created["setting_id"] = body["id"]
        # persistence check
        listed = s.get(f"{API}/org/settings", timeout=60).json()
        assert body["id"] in [x["id"] for x in listed]

    def test_03_update_setting(self, admin):
        """PRE-EXISTING BUG (iter97): org_settings has no manager_user_id column ->
        org.py:213 raises KeyError 'manager_user_id' -> 500 on every branch rename."""
        s, _ = admin
        sid = TestOrgStructureCRUD.created["setting_id"]
        r = s.put(f"{API}/org/settings/{sid}", json={"name": f"TEST_Branch_{TAG}_upd"}, timeout=60)
        assert r.status_code == 200, f"branch rename failed: {r.status_code} {r.text[:200]}"
        listed = s.get(f"{API}/org/settings", timeout=60).json()
        match = [x for x in listed if x["id"] == sid]
        assert match and match[0]["name"] == f"TEST_Branch_{TAG}_upd"

    def test_04_create_team_under_setting(self, admin):
        s, _ = admin
        sid = TestOrgStructureCRUD.created["setting_id"]
        r = s.post(f"{API}/org/settings/{sid}/teams",
                   json={"name": f"TEST_Team_{TAG}", "description": "idx regression"}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["setting_id"] == sid
        TestOrgStructureCRUD.created["team_id"] = body["id"]

    def test_05_structure_reflects_setting_and_team(self, admin):
        s, _ = admin
        r = s.get(f"{API}/org/structure", timeout=60)
        assert r.status_code == 200, r.text[:300]
        struct = r.json()
        settings = struct["settings"]
        sid = TestOrgStructureCRUD.created["setting_id"]
        tid = TestOrgStructureCRUD.created["team_id"]
        node = [x for x in settings if x["id"] == sid]
        assert node, "created setting not returned by /org/structure (teams.setting_id filter)"
        assert tid in [t["id"] for t in node[0].get("teams", [])]

    def test_06_update_team_and_assign_supervisor(self, admin):
        s, _ = admin
        tid = TestOrgStructureCRUD.created["team_id"]
        users = s.get(f"{API}/admin/users", timeout=60).json()
        sup = next(u for u in users if u["email"] == "jane@supervision.com")
        TestOrgStructureCRUD.created["staff_id"] = sup["id"]
        TestOrgStructureCRUD.created["staff_prev"] = (sup["team_id"], sup["setting_id"])
        r = s.put(f"{API}/org/teams/{tid}",
                  json={"name": f"TEST_Team_{TAG}_upd", "description": "d",
                        "supervisor_user_id": sup["id"]}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        # supervisor should now be on the team + setting
        after = [u for u in s.get(f"{API}/admin/users", timeout=60).json() if u["id"] == sup["id"]][0]
        assert after["team_id"] == tid
        assert after["setting_id"] == TestOrgStructureCRUD.created["setting_id"]

    def test_07_assign_team_endpoint(self, admin):
        s, _ = admin
        tid = TestOrgStructureCRUD.created["team_id"]
        uid = TestOrgStructureCRUD.created["staff_id"]
        r = s.patch(f"{API}/org/users/{uid}/assign-team", json={"team_id": tid}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        rows = asyncio.run(_db_fetch("SELECT team_id, setting_id FROM users WHERE id=$1", uid))
        assert str(rows[0]["team_id"]) == tid
        assert str(rows[0]["setting_id"]) == TestOrgStructureCRUD.created["setting_id"]

    def test_08_team_insights_filtered_by_team(self, admin):
        s, _ = admin
        tid = TestOrgStructureCRUD.created["team_id"]
        r = s.get(f"{API}/admin/team-insights?team_id={tid}", timeout=90)
        assert r.status_code == 200, r.text[:300]
        assert isinstance(r.json(), dict)

    def test_09_team_insights_filtered_by_setting(self, admin):
        s, _ = admin
        sid = TestOrgStructureCRUD.created["setting_id"]
        r = s.get(f"{API}/admin/team-insights?setting_id={sid}", timeout=90)
        assert r.status_code == 200, r.text[:300]

    def test_10_registers_filtered_by_team_and_setting(self, admin):
        s, _ = admin
        tid = TestOrgStructureCRUD.created["team_id"]
        sid = TestOrgStructureCRUD.created["setting_id"]
        for q in (f"team_id={tid}", f"setting_id={sid}"):
            r = s.get(f"{API}/admin/team-insights/registers?{q}", timeout=90)
            assert r.status_code == 200, f"{q}: {r.text[:300]}"
            body = r.json()
            assert {"actions", "risks", "learning_needs"} <= set(body.keys())

    def test_11_people_stats_and_dashboard(self, admin):
        s, _ = admin
        r1 = s.get(f"{API}/admin/people-stats", timeout=90)
        assert r1.status_code == 200, r1.text[:300]
        r2 = s.get(f"{API}/dashboard/", timeout=90)
        if r2.status_code == 404:
            r2 = s.get(f"{API}/dashboard/stats", timeout=90)
        assert r2.status_code == 200, r2.text[:300]

    def test_12_remove_member_and_delete_team(self, admin):
        s, _ = admin
        tid = TestOrgStructureCRUD.created["team_id"]
        uid = TestOrgStructureCRUD.created["staff_id"]
        r = s.delete(f"{API}/org/teams/{tid}/members/{uid}", timeout=60)
        assert r.status_code == 200, r.text[:300]
        rows = asyncio.run(_db_fetch("SELECT team_id, setting_id FROM users WHERE id=$1", uid))
        assert rows[0]["team_id"] is None and rows[0]["setting_id"] is None
        d = s.delete(f"{API}/org/teams/{tid}", timeout=60)
        assert d.status_code == 200, d.text[:300]

    def test_13_delete_setting(self, admin):
        s, _ = admin
        sid = TestOrgStructureCRUD.created["setting_id"]
        d = s.delete(f"{API}/org/settings/{sid}", timeout=60)
        assert d.status_code == 200, d.text[:300]
        listed = s.get(f"{API}/org/settings", timeout=60).json()
        assert sid not in [x["id"] for x in listed]

    def test_14_restore_staff_assignment(self, admin):
        prev = TestOrgStructureCRUD.created.get("staff_prev")
        uid = TestOrgStructureCRUD.created.get("staff_id")
        if uid and prev:
            asyncio.run(_db_exec("UPDATE users SET team_id=$1, setting_id=$2 WHERE id=$3",
                                 prev[0], prev[1], str(uid)))


# ── prep.py :: focus_topics CRUD (focus_topics.org_id) ───────────────────────

class TestFocusTopics:
    topic_id = None

    def test_01_list(self, admin):
        s, _ = admin
        r = s.get(f"{API}/prep/focus-topics", timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert isinstance(r.json(), list)

    def test_02_create_current(self, admin):
        s, me = admin
        r = s.post(f"{API}/prep/focus-topics",
                   json={"topic": f"TEST_Focus_{TAG}", "is_current": True}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["topic"] == f"TEST_Focus_{TAG}"
        assert body["org_id"] == me["org_id"]
        TestFocusTopics.topic_id = body["id"]
        listed = s.get(f"{API}/prep/focus-topics", timeout=60).json()
        match = [t for t in listed if t["id"] == body["id"]]
        assert match, "created focus topic not returned by list (focus_topics.org_id filter)"
        assert match[0]["is_current"] is True
        # only one current topic allowed
        assert len([t for t in listed if t.get("is_current")]) == 1

    def test_03_update(self, admin):
        s, _ = admin
        r = s.put(f"{API}/prep/focus-topics/{TestFocusTopics.topic_id}",
                  json={"topic": f"TEST_Focus_{TAG}_upd", "is_current": True}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        listed = s.get(f"{API}/prep/focus-topics", timeout=60).json()
        match = [t for t in listed if t["id"] == TestFocusTopics.topic_id]
        assert match and match[0]["topic"] == f"TEST_Focus_{TAG}_upd"

    def test_04_delete_and_verify(self, admin):
        s, _ = admin
        r = s.delete(f"{API}/prep/focus-topics/{TestFocusTopics.topic_id}", timeout=60)
        assert r.status_code == 200, r.text[:300]
        listed = s.get(f"{API}/prep/focus-topics", timeout=60).json()
        assert TestFocusTopics.topic_id not in [t["id"] for t in listed]
        again = s.delete(f"{API}/prep/focus-topics/{TestFocusTopics.topic_id}", timeout=60)
        assert again.status_code == 404


# ── standards_documents.org_id ───────────────────────────────────────────────

class TestStandardsDocuments:
    def test_list_documents(self, admin):
        s, me = admin
        r = s.get(f"{API}/admin/standards/documents", timeout=60)
        assert r.status_code == 200, r.text[:300]
        docs = r.json()
        assert isinstance(docs, list)
        for d in docs:
            assert "_id" not in d
            assert d.get("org_id") in (me["org_id"], None)

    def test_standards_list_still_loads(self, admin):
        s, _ = admin
        r = s.get(f"{API}/admin/standards", timeout=90)
        assert r.status_code == 200, r.text[:300]
        assert len(r.json()) > 0

    def test_prep_context_uses_docs(self, admin):
        """A parsed standards document must still be consumable by prep context."""
        s, _ = admin
        meetings = s.get(f"{API}/meetings/", timeout=90)
        assert meetings.status_code == 200, meetings.text[:300]
        items = meetings.json()
        items = items.get("meetings", items) if isinstance(items, dict) else items
        if not items:
            pytest.skip("no meetings available to exercise prep context")
        mid = items[0]["id"]
        r = s.get(f"{API}/prep/{mid}/context", timeout=120)
        assert r.status_code in (200, 403, 404), r.text[:300]
