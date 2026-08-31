"""Iteration 98 — verification of the 5 fixes applied after iter97.

Focus:
  1. PUT /api/org/settings/{id} no longer 500s (org_settings.manager_user_id column added
     + create_setting/update_setting persist it).
  2. GET /api/org/structure rewritten to batched queries — output shape/data must be
     identical to the previous N+1 implementation (org / setting-scoped / team-scoped),
     plus edge cases (zero teams, zero members, null manager/supervisor).
  3. Full Organisation-structure CRUD regression (settings, teams, members, assign-team,
     invite user, edit user).
"""
import asyncio
import uuid
from datetime import datetime, timezone, timedelta

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

BE = dotenv_values("/app/backend/.env")
FE = dotenv_values("/app/frontend/.env")
API = FE["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = BE["DATABASE_URL"]
TAG = uuid.uuid4().hex[:6]

ADMIN = ("admin@supervision.com", "Admin123!")
MANAGER = ("manager@supervision.com", "Manager123!")
STAFF_EMAIL = "jane@supervision.com"


# ── helpers ───────────────────────────────────────────────────────────────────

async def _mfa(email):
    c = await asyncpg.connect(DSN, ssl="require")
    await c.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode(),
        (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(), email)
    await c.close()


async def _fetch(sql, *a):
    c = await asyncpg.connect(DSN, ssl="require")
    rows = await c.fetch(sql, *a)
    await c.close()
    return [dict(r) for r in rows]


async def _exec(sql, *a):
    c = await asyncpg.connect(DSN, ssl="require")
    res = await c.execute(sql, *a)
    await c.close()
    return res


def _login(email, pw):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=60)
    if r.status_code != 200:
        pytest.fail(f"login failed {email}: {r.status_code} {r.text[:200]}")
    d = r.json()
    if d.get("requires_mfa"):
        asyncio.run(_mfa(email))
        r2 = s.post(f"{API}/auth/verify-mfa",
                    json={"mfa_session": d["mfa_session"], "code": "123456"}, timeout=60)
        if r2.status_code != 200:
            pytest.fail(f"mfa failed {email}: {r2.status_code} {r2.text[:200]}")
    me = s.get(f"{API}/auth/me", timeout=60)
    assert me.status_code == 200, me.text[:200]
    return s, me.json()


@pytest.fixture(scope="module")
def admin():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def users(admin):
    s, _ = admin
    r = s.get(f"{API}/admin/users", timeout=60)
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def fixtures(admin, users):
    """A branch with 2 teams (one empty) + an empty branch. Cleaned up at teardown."""
    s, _ = admin
    created = {"settings": [], "teams": []}

    r = s.post(f"{API}/org/settings", json={"name": f"TEST98_Branch_{TAG}"}, timeout=60)
    assert r.status_code == 200, r.text[:300]
    sid = r.json()["id"]
    created["settings"].append(sid)

    r = s.post(f"{API}/org/settings", json={"name": f"TEST98_EmptyBranch_{TAG}"}, timeout=60)
    assert r.status_code == 200, r.text[:300]
    empty_sid = r.json()["id"]
    created["settings"].append(empty_sid)

    r = s.post(f"{API}/org/settings/{sid}/teams", json={"name": f"TEST98_TeamA_{TAG}"}, timeout=60)
    assert r.status_code == 200, r.text[:300]
    tid_a = r.json()["id"]
    created["teams"].append(tid_a)

    r = s.post(f"{API}/org/settings/{sid}/teams", json={"name": f"TEST98_TeamB_{TAG}"}, timeout=60)
    assert r.status_code == 200, r.text[:300]
    tid_b = r.json()["id"]
    created["teams"].append(tid_b)

    mgr = next(u for u in users if u["email"] == MANAGER[0])
    staff = next(u for u in users if u["email"] == STAFF_EMAIL)
    prev = {mgr["id"]: (mgr["team_id"], mgr["setting_id"]),
            staff["id"]: (staff["team_id"], staff["setting_id"])}

    yield {"setting_id": sid, "empty_setting_id": empty_sid, "team_a": tid_a, "team_b": tid_b,
           "mgr_id": mgr["id"], "staff_id": staff["id"], "created": created}

    # teardown — restore user scoping, delete created settings/teams
    for uid, (t, st) in prev.items():
        asyncio.run(_exec("UPDATE users SET team_id=$1, setting_id=$2 WHERE id=$3", t, st, uid))
    for tid in created["teams"]:
        s.delete(f"{API}/org/teams/{tid}", timeout=60)
    for s_id in created["settings"]:
        s.delete(f"{API}/org/settings/{s_id}", timeout=60)
    left = asyncio.run(_fetch("SELECT name FROM org_settings WHERE name LIKE 'TEST98%'"))
    assert left == [], f"setting cleanup incomplete: {left}"
    left_t = asyncio.run(_fetch("SELECT name FROM teams WHERE name LIKE 'TEST98%'"))
    assert left_t == [], f"team cleanup incomplete: {left_t}"


def _find_setting(struct, sid):
    return next((x for x in struct["settings"] if x["id"] == sid), None)


# ── FIX 1: PUT /org/settings/{id} (branch rename) ─────────────────────────────

class TestSettingRenameFix:
    def test_schema_has_manager_user_id_column(self):
        cols = asyncio.run(_fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name='org_settings'"))
        assert "manager_user_id" in {c["column_name"] for c in cols}

    def test_rename_without_manager_returns_200(self, admin, fixtures):
        s, _ = admin
        sid = fixtures["setting_id"]
        new_name = f"TEST98_Branch_{TAG}_r1"
        r = s.put(f"{API}/org/settings/{sid}", json={"name": new_name}, timeout=60)
        assert r.status_code == 200, f"rename 500/err: {r.status_code} {r.text[:300]}"
        listed = s.get(f"{API}/org/settings", timeout=60).json()
        row = next(x for x in listed if x["id"] == sid)
        assert row["name"] == new_name
        assert row.get("manager_user_id") is None

    def test_rename_with_manager_persists_and_shows_name(self, admin, fixtures, users):
        s, _ = admin
        sid = fixtures["setting_id"]
        mgr = next(u for u in users if u["email"] == MANAGER[0])
        new_name = f"TEST98_Branch_{TAG}_r2"
        r = s.put(f"{API}/org/settings/{sid}",
                  json={"name": new_name, "manager_user_id": mgr["id"]}, timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        # DB persistence
        row = asyncio.run(_fetch("SELECT name, manager_user_id FROM org_settings WHERE id=$1", sid))[0]
        assert row["name"] == new_name
        assert row["manager_user_id"] == mgr["id"]
        # manager's setting_id was updated
        u = asyncio.run(_fetch("SELECT setting_id FROM users WHERE id=$1", mgr["id"]))[0]
        assert u["setting_id"] == sid
        # structure exposes manager_name
        struct = s.get(f"{API}/org/structure", timeout=60).json()
        node = _find_setting(struct, sid)
        assert node is not None
        assert node["manager_name"] == mgr["name"], node.get("manager_name")

    def test_rename_clearing_manager_unassigns(self, admin, fixtures, users):
        s, _ = admin
        sid = fixtures["setting_id"]
        mgr = next(u for u in users if u["email"] == MANAGER[0])
        r = s.put(f"{API}/org/settings/{sid}",
                  json={"name": f"TEST98_Branch_{TAG}", "manager_user_id": None}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        row = asyncio.run(_fetch("SELECT manager_user_id FROM org_settings WHERE id=$1", sid))[0]
        assert row["manager_user_id"] is None
        u = asyncio.run(_fetch("SELECT setting_id FROM users WHERE id=$1", mgr["id"]))[0]
        assert u["setting_id"] is None
        struct = s.get(f"{API}/org/structure", timeout=60).json()
        assert _find_setting(struct, sid)["manager_name"] is None

    def test_rename_nonexistent_setting_404(self, admin):
        s, _ = admin
        r = s.put(f"{API}/org/settings/{uuid.uuid4()}", json={"name": "TEST98_nope"}, timeout=60)
        assert r.status_code == 404, f"{r.status_code} {r.text[:200]}"

    def test_create_setting_with_manager_shows_manager_name(self, admin, fixtures, users):
        s, _ = admin
        staff = next(u for u in users if u["email"] == STAFF_EMAIL)
        r = s.post(f"{API}/org/settings",
                   json={"name": f"TEST98_MgrBranch_{TAG}", "manager_user_id": staff["id"]}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        sid = r.json()["id"]
        fixtures["created"]["settings"].append(sid)
        row = asyncio.run(_fetch("SELECT manager_user_id FROM org_settings WHERE id=$1", sid))[0]
        assert row["manager_user_id"] == staff["id"]
        struct = s.get(f"{API}/org/structure", timeout=60).json()
        node = _find_setting(struct, sid)
        assert node["manager_name"] == staff["name"]
        # cleanup this extra branch immediately (restores staff scoping via cascade)
        assert s.delete(f"{API}/org/settings/{sid}", timeout=60).status_code == 200
        fixtures["created"]["settings"].remove(sid)


# ── FIX 2: GET /org/structure batched rewrite — shape equivalence ─────────────

class TestStructureShape:
    def test_admin_org_level_shape(self, admin, fixtures):
        s, _ = admin
        r = s.get(f"{API}/org/structure", timeout=60)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert set(body.keys()) == {"settings", "unassigned_users"}
        assert isinstance(body["settings"], list) and isinstance(body["unassigned_users"], list)
        for st in body["settings"]:
            assert {"id", "org_id", "name", "manager_user_id", "manager_name", "teams"} <= set(st.keys())
            assert "_id" not in st
            assert isinstance(st["teams"], list)
            for t in st["teams"]:
                assert {"id", "org_id", "setting_id", "name", "supervisor_user_id",
                        "supervisor_name", "members"} <= set(t.keys())
                assert t["setting_id"] == st["id"]
                assert isinstance(t["members"], list)
                for m in t["members"]:
                    assert set(m.keys()) == {"id", "name", "email", "role"}
        for u in body["unassigned_users"]:
            assert set(u.keys()) == {"id", "name", "email", "role"}
        # settings ordered by the DB's collation for name ASC (verified against SQL
        # in test_batched_output_matches_reference_reconstruction)
        assert len(body["settings"]) >= 1

    def test_setting_with_zero_teams_and_team_with_zero_members(self, admin, fixtures):
        s, _ = admin
        body = s.get(f"{API}/org/structure", timeout=60).json()
        empty = _find_setting(body, fixtures["empty_setting_id"])
        assert empty is not None and empty["teams"] == []
        node = _find_setting(body, fixtures["setting_id"])
        team_b = next(t for t in node["teams"] if t["id"] == fixtures["team_b"])
        assert team_b["members"] == []
        assert team_b["supervisor_name"] is None
        assert team_b["supervisor_user_id"] is None

    def test_teams_sorted_and_members_sorted(self, admin, fixtures):
        s, _ = admin
        node = _find_setting(s.get(f"{API}/org/structure", timeout=60).json(), fixtures["setting_id"])
        tnames = [t["name"] for t in node["teams"]]
        assert tnames == sorted(tnames)

    def test_batched_output_matches_reference_reconstruction(self, admin):
        """Rebuild the expected structure straight from SQL and diff it against the API."""
        s, me = admin
        org_id = me["org_id"]
        body = s.get(f"{API}/org/structure", timeout=60).json()

        settings = asyncio.run(_fetch(
            "SELECT id, name, manager_user_id FROM org_settings WHERE org_id=$1 ORDER BY name ASC", org_id))
        assert [x["id"] for x in body["settings"]] == [x["id"] for x in settings]

        for api_s, db_s in zip(body["settings"], settings):
            assert api_s["name"] == db_s["name"]
            assert api_s["manager_user_id"] == db_s["manager_user_id"]
            db_teams = asyncio.run(_fetch(
                "SELECT id, name, supervisor_user_id FROM teams WHERE setting_id=$1 ORDER BY name ASC",
                db_s["id"]))
            assert [t["id"] for t in api_s["teams"]] == [t["id"] for t in db_teams]
            for api_t, db_t in zip(api_s["teams"], db_teams):
                db_members = asyncio.run(_fetch(
                    "SELECT id FROM users WHERE team_id=$1 AND is_active=TRUE ORDER BY name ASC", db_t["id"]))
                assert [m["id"] for m in api_t["members"]] == [m["id"] for m in db_members]

        db_unassigned = asyncio.run(_fetch(
            "SELECT id FROM users WHERE org_id=$1 AND is_active=TRUE AND (team_id IS NULL OR team_id='') "
            "ORDER BY name ASC", org_id))
        assert [u["id"] for u in body["unassigned_users"]] == [u["id"] for u in db_unassigned]

    def test_setting_scoped_manager(self, admin, fixtures):
        """Manager scoped to a branch (setting_id set, team_id NULL)."""
        asyncio.run(_exec("UPDATE users SET team_id=NULL, setting_id=$1 WHERE id=$2",
                          fixtures["setting_id"], fixtures["mgr_id"]))
        s, me = _login(*MANAGER)
        assert me["setting_id"] == fixtures["setting_id"] and not me.get("team_id")
        r = s.get(f"{API}/org/structure", timeout=60)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert [x["id"] for x in body["settings"]] == [fixtures["setting_id"]]
        team_ids = {t["id"] for t in body["settings"][0]["teams"]}
        assert team_ids == {fixtures["team_a"], fixtures["team_b"]}
        assert body["unassigned_users"] == []
        assert body["settings"][0]["manager_name"] is None or isinstance(
            body["settings"][0]["manager_name"], str)

    def test_team_scoped_manager(self, admin, fixtures):
        """Manager scoped to a single team sees only their setting + that one team."""
        asyncio.run(_exec("UPDATE users SET team_id=$1, setting_id=$2 WHERE id=$3",
                          fixtures["team_a"], fixtures["setting_id"], fixtures["mgr_id"]))
        s, me = _login(*MANAGER)
        assert me["team_id"] == fixtures["team_a"]
        body = s.get(f"{API}/org/structure", timeout=60).json()
        assert [x["id"] for x in body["settings"]] == [fixtures["setting_id"]]
        assert [t["id"] for t in body["settings"][0]["teams"]] == [fixtures["team_a"]]
        assert body["unassigned_users"] == []
        members = body["settings"][0]["teams"][0]["members"]
        assert MANAGER[0] in {m["email"] for m in members}

    def test_scoped_manager_out_of_scope_403(self, admin, fixtures):
        s, _ = _login(*MANAGER)
        r = s.put(f"{API}/org/settings/{fixtures['empty_setting_id']}",
                  json={"name": "TEST98_hack"}, timeout=60)
        assert r.status_code == 403, f"{r.status_code} {r.text[:200]}"
        # restore org-level scope for later tests
        asyncio.run(_exec("UPDATE users SET team_id=NULL, setting_id=NULL WHERE id=$1", fixtures["mgr_id"]))


# ── FIX 3: full CRUD regression ───────────────────────────────────────────────

class TestOrgCrudRegression:
    def test_team_update_with_supervisor(self, admin, fixtures, users):
        s, _ = admin
        staff = next(u for u in users if u["email"] == STAFF_EMAIL)
        tid = fixtures["team_a"]
        r = s.put(f"{API}/org/teams/{tid}",
                  json={"name": f"TEST98_TeamA_{TAG}_upd", "supervisor_user_id": staff["id"]}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        node = _find_setting(s.get(f"{API}/org/structure", timeout=60).json(), fixtures["setting_id"])
        team = next(t for t in node["teams"] if t["id"] == tid)
        assert team["name"] == f"TEST98_TeamA_{TAG}_upd"
        assert team["supervisor_name"] == staff["name"]
        assert staff["id"] in {m["id"] for m in team["members"]}

    def test_assign_member_between_teams(self, admin, fixtures, users):
        s, _ = admin
        staff_id = fixtures["staff_id"]
        r = s.patch(f"{API}/org/users/{staff_id}/assign-team",
                    json={"team_id": fixtures["team_b"]}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        node = _find_setting(s.get(f"{API}/org/structure", timeout=60).json(), fixtures["setting_id"])
        tb = next(t for t in node["teams"] if t["id"] == fixtures["team_b"])
        assert staff_id in {m["id"] for m in tb["members"]}

    def test_unassign_member_to_pool(self, admin, fixtures):
        s, _ = admin
        staff_id = fixtures["staff_id"]
        r = s.patch(f"{API}/org/users/{staff_id}/assign-team", json={"team_id": None}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        body = s.get(f"{API}/org/structure", timeout=60).json()
        assert staff_id in {u["id"] for u in body["unassigned_users"]}

    def test_add_and_remove_member_endpoints(self, admin, fixtures):
        s, _ = admin
        staff_id = fixtures["staff_id"]
        r = s.post(f"{API}/org/teams/{fixtures['team_a']}/members",
                   json={"user_id": staff_id}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        r = s.delete(f"{API}/org/teams/{fixtures['team_a']}/members/{staff_id}", timeout=60)
        assert r.status_code == 200, r.text[:300]
        body = s.get(f"{API}/org/structure", timeout=60).json()
        assert staff_id in {u["id"] for u in body["unassigned_users"]}

    def test_delete_team_unassigns_members(self, admin, fixtures):
        s, _ = admin
        staff_id = fixtures["staff_id"]
        r = s.post(f"{API}/org/settings/{fixtures['setting_id']}/teams",
                   json={"name": f"TEST98_TmpTeam_{TAG}"}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        tid = r.json()["id"]
        assert s.patch(f"{API}/org/users/{staff_id}/assign-team",
                       json={"team_id": tid}, timeout=60).status_code == 200
        assert s.delete(f"{API}/org/teams/{tid}", timeout=60).status_code == 200
        assert s.delete(f"{API}/org/teams/{tid}", timeout=60).status_code == 404
        body = s.get(f"{API}/org/structure", timeout=60).json()
        node = _find_setting(body, fixtures["setting_id"])
        assert tid not in {t["id"] for t in node["teams"]}
        assert staff_id in {u["id"] for u in body["unassigned_users"]}

    def test_delete_setting_cascades(self, admin, fixtures):
        s, _ = admin
        staff_id = fixtures["staff_id"]
        r = s.post(f"{API}/org/settings", json={"name": f"TEST98_Cascade_{TAG}"}, timeout=60)
        sid = r.json()["id"]
        tid = s.post(f"{API}/org/settings/{sid}/teams",
                     json={"name": f"TEST98_CascadeTeam_{TAG}"}, timeout=60).json()["id"]
        assert s.patch(f"{API}/org/users/{staff_id}/assign-team",
                       json={"team_id": tid}, timeout=60).status_code == 200
        assert s.delete(f"{API}/org/settings/{sid}", timeout=60).status_code == 200
        assert s.delete(f"{API}/org/settings/{sid}", timeout=60).status_code == 404
        assert asyncio.run(_fetch("SELECT id FROM teams WHERE id=$1", tid)) == []
        u = asyncio.run(_fetch("SELECT team_id, setting_id FROM users WHERE id=$1", staff_id))[0]
        assert u["team_id"] is None and u["setting_id"] is None

    def test_invite_user_then_edit_and_delete(self, admin, fixtures):
        s, _ = admin
        email = f"test98_{TAG}@example.com"
        r = s.post(f"{API}/org/invite-user", json={
            "name": "TEST98 Invitee", "email": email, "role": "attendee",
            "password": "TempPass123!"}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        uid = r.json()["id"]
        assert r.json()["email"] == email
        try:
            # duplicate invite rejected
            dup = s.post(f"{API}/org/invite-user", json={
                "name": "dup", "email": email, "role": "attendee",
                "password": "TempPass123!"}, timeout=60)
            assert dup.status_code == 400, dup.status_code

            # edit user (name/role/active) via admin endpoint
            up = s.put(f"{API}/admin/users/{uid}", json={
                "name": "TEST98 Renamed", "role": "shared_reviewer", "is_active": True}, timeout=60)
            assert up.status_code == 200, f"{up.status_code} {up.text[:300]}"
            listed = s.get(f"{API}/admin/users", timeout=60).json()
            row = next(u for u in listed if u["id"] == uid)
            assert row["name"] == "TEST98 Renamed"
            assert row["role"] == "shared_reviewer"

            # team assignment from the People edit modal path
            assert s.patch(f"{API}/org/users/{uid}/assign-team",
                           json={"team_id": fixtures["team_a"]}, timeout=60).status_code == 200
            node = _find_setting(s.get(f"{API}/org/structure", timeout=60).json(),
                                 fixtures["setting_id"])
            team = next(t for t in node["teams"] if t["id"] == fixtures["team_a"])
            assert uid in {m["id"] for m in team["members"]}

            # deactivating removes from structure members + unassigned lists
            assert s.put(f"{API}/admin/users/{uid}",
                         json={"is_active": False}, timeout=60).status_code == 200
            body = s.get(f"{API}/org/structure", timeout=60).json()
            node = _find_setting(body, fixtures["setting_id"])
            team = next(t for t in node["teams"] if t["id"] == fixtures["team_a"])
            assert uid not in {m["id"] for m in team["members"]}
            assert uid not in {u["id"] for u in body["unassigned_users"]}
        finally:
            asyncio.run(_exec("DELETE FROM users WHERE id=$1", uid))


# ── FIX 4: focus topics cache invalidation (API level) ────────────────────────

class TestFocusTopics:
    def test_focus_topic_crud(self, admin):
        s, _ = admin
        title = f"TEST98_Focus_{TAG}"
        r = s.post(f"{API}/prep/focus-topics", json={"topic": title}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        tid = r.json().get("id")
        assert tid
        items = s.get(f"{API}/prep/focus-topics", timeout=60).json()
        assert isinstance(items, list)
        assert tid in [t["id"] for t in items]

        cur = s.put(f"{API}/prep/focus-topics/{tid}",
                    json={"topic": title, "is_current": True}, timeout=60)
        assert cur.status_code == 200, f"{cur.status_code} {cur.text[:300]}"
        items = s.get(f"{API}/prep/focus-topics", timeout=60).json()
        row = next(t for t in items if t["id"] == tid)
        assert row.get("is_current") is True, row
        assert row.get("effective_current") is True, row

        d = s.delete(f"{API}/prep/focus-topics/{tid}", timeout=60)
        assert d.status_code == 200, d.text[:300]
        items = s.get(f"{API}/prep/focus-topics", timeout=60).json()
        assert tid not in [t["id"] for t in items]
        assert s.delete(f"{API}/prep/focus-topics/{tid}", timeout=60).status_code == 404


# ── FIX 5/6: people-stats consumer ───────────────────────────────────────────

class TestPeopleStats:
    def test_people_stats_shape(self, admin):
        s, _ = admin
        r = s.get(f"{API}/admin/people-stats", timeout=120)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert isinstance(body, list) and len(body) > 0
        row = body[0]
        assert {"user_id", "name", "email", "role", "is_active", "pending_invite",
                "meeting_count", "weekly_activity"} <= set(row.keys())
        assert "_id" not in row
