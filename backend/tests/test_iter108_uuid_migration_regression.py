"""Iteration 108 — Phase 2 TEXT -> UUID migration full regression suite.

Focus: every endpoint class that binds/compares/joins a migrated id or FK column.
Hunting for: 500s with 'operator does not exist: uuid = text', 'invalid input
syntax for type uuid', broken ANY($n::text[]) array casts, empty-string ('')
literals bound to uuid columns, RLS isolation breakage after policy rebuild.

Run: cd /app/backend && python3 -m pytest tests/test_iter108_uuid_migration_regression.py -n 0 -q
"""
import asyncio
import json
import sys
import uuid
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

ORG_A = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"   # Test Company
ORG_B = "3628a11d-36b8-42df-9d46-0479450ee22c"   # IDOR Test Org B
STAFF_ID = "831bdaef-14ca-49ed-8fb0-9b8d36bc1ef6"  # user@supervision.com
MANAGER_ID = "465c5101-bbc8-4f26-adaa-c906d3324dd5"
ADMIN_ID = "f72ac550-e6b8-4ffc-b2da-46a54a4c06d5"
P = "TEST_iter108_"

created = {"meetings": [], "settings": [], "teams": [], "users": [], "schedules": [],
           "orgs": [], "invitations": [], "topics": []}


# ───────────────────────── helpers ─────────────────────────
def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _db(fn):
    conn = await asyncpg.connect(DSN)
    try:
        return await fn(conn)
    finally:
        await conn.close()


def db(fn):
    return _run(_db(fn))


def login(email, password):
    db(lambda c: c.execute("DELETE FROM login_attempts"))
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=90)
    assert r.status_code == 200, f"login {email} -> {r.status_code}: {r.text[:300]}"
    data = r.json()
    if data.get("requires_mfa"):
        h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
        exp = datetime.now(timezone.utc) + timedelta(minutes=10)
        db(lambda c: c.execute(
            "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
            h, exp, email))
        r2 = s.post(f"{BASE}/auth/verify-mfa",
                    json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=90)
        assert r2.status_code == 200, f"verify-mfa {email} -> {r2.status_code}: {r2.text[:300]}"
    me = s.get(f"{BASE}/auth/me", timeout=60)
    assert me.status_code == 200, me.text[:300]
    return s


def ok(resp, ctx="", allow=(200, 201)):
    assert resp.status_code in allow, f"{ctx} -> {resp.status_code}: {resp.text[:500]}"
    return resp.json() if resp.content else {}


def no500(resp, ctx=""):
    assert resp.status_code < 500, f"{ctx} -> {resp.status_code}: {resp.text[:600]}"
    return resp


@pytest.fixture(scope="session")
def admin_s():
    return login("admin@supervision.com", "Admin123!")


@pytest.fixture(scope="session")
def manager_s():
    return login("manager@supervision.com", "Manager123!")


@pytest.fixture(scope="session")
def staff_s():
    return login("user@supervision.com", "Staff123!")


@pytest.fixture(scope="session")
def super_s():
    return login("superadmin@1two.one", "NewPass123!")


@pytest.fixture(scope="session")
def meeting(admin_s):
    """A TEST_ meeting created via the API with the staff user as attendee."""
    m = ok(admin_s.post(f"{BASE}/meetings/", json={
        "title": P + "meeting", "date": datetime.now(timezone.utc).isoformat(),
        "location": "TEST", "meeting_type": "supervision",
        "attendee_ids": [STAFF_ID], "sign_off_manager_id": MANAGER_ID,
    }, timeout=90), "create meeting")
    created["meetings"].append(m["id"])
    return m


@pytest.fixture(scope="session", autouse=True)
def cleanup():
    yield

    async def _c(c):
        for mid in created["meetings"]:
            await c.execute("DELETE FROM meetings WHERE id=$1", mid)
        for sid in created["schedules"]:
            await c.execute("DELETE FROM schedules WHERE id=$1", sid)
        for tid in created["teams"]:
            await c.execute("UPDATE users SET team_id=NULL WHERE team_id=$1", tid)
            await c.execute("DELETE FROM teams WHERE id=$1", tid)
        for sid in created["settings"]:
            await c.execute("UPDATE users SET setting_id=NULL WHERE setting_id=$1", sid)
            await c.execute("DELETE FROM teams WHERE setting_id=$1", sid)
            await c.execute("DELETE FROM org_settings WHERE id=$1", sid)
        await c.execute("DELETE FROM invitations WHERE user_id IN (SELECT id FROM users WHERE email LIKE $1)", P + "%")
        await c.execute("DELETE FROM users WHERE email LIKE $1", P + "%")
        await c.execute("DELETE FROM focus_topics WHERE text LIKE $1", P + "%")
        await c.execute("DELETE FROM meeting_types WHERE name LIKE $1", P + "%")
        for oid in created["orgs"]:
            await c.execute("DELETE FROM users WHERE org_id=$1", oid)
            await c.execute("DELETE FROM organisations WHERE id=$1", oid)
        await c.execute("DELETE FROM login_attempts")
    db(_c)


# ───────────────────────── 1. schema invariants ─────────────────────────
class TestSchema:
    def test_fk_and_rls_invariants(self):
        res = db(lambda c: c.fetch("""
            SELECT
              (SELECT count(*) FROM pg_constraint WHERE contype='f' AND connamespace='public'::regnamespace) AS fks,
              (SELECT count(*) FROM pg_constraint WHERE contype='f' AND NOT convalidated AND connamespace='public'::regnamespace) AS bad_fks,
              (SELECT count(*) FROM pg_policies WHERE schemaname='public') AS pols
        """))
        r = dict(res[0])
        assert r["fks"] == 39, f"FK count changed: {r}"
        assert r["bad_fks"] == 0
        assert r["pols"] == 21, f"RLS policy count changed: {r}"

    def test_core_id_columns_are_uuid(self):
        rows = db(lambda c: c.fetch("""
            SELECT table_name, column_name, data_type FROM information_schema.columns
            WHERE table_schema='public' AND column_name IN ('id','org_id','user_id','meeting_id',
              'team_id','setting_id','created_by','staff_user_id','analysis_id','transcript_id')
        """))
        bad = [dict(r) for r in rows if r["data_type"] != "uuid"]
        assert not bad, f"expected uuid, got: {bad}"

    def test_uuid_columns_reject_malformed_at_db_level(self):
        with pytest.raises(asyncpg.exceptions.DataError):
            db(lambda c: c.fetchval("SELECT id FROM meetings WHERE id=$1", "not-a-uuid"))


# ───────────────────────── 2. auth ─────────────────────────
class TestAuth:
    def test_admin_login_and_me(self, admin_s):
        me = ok(admin_s.get(f"{BASE}/auth/me", timeout=60), "admin me")
        assert me["email"] == "admin@supervision.com"
        assert me["id"] == ADMIN_ID and me["org_id"] == ORG_A
        assert isinstance(me["id"], str)

    def test_manager_login_and_me(self, manager_s):
        me = ok(manager_s.get(f"{BASE}/auth/me", timeout=60), "manager me")
        assert me["role"] == "manager" and me["id"] == MANAGER_ID

    def test_staff_login_no_mfa(self, staff_s):
        me = ok(staff_s.get(f"{BASE}/auth/me", timeout=60), "staff me")
        assert me["role"] == "attendee" and me["id"] == STAFF_ID

    def test_super_admin_login(self, super_s):
        me = ok(super_s.get(f"{BASE}/auth/me", timeout=60), "super me")
        assert me["role"] == "super_admin"


# ───────────────────────── 3. dashboard ─────────────────────────
class TestDashboard:
    @pytest.mark.parametrize("who", ["admin", "manager", "staff"])
    def test_dashboard_loads(self, who, admin_s, manager_s, staff_s):
        s = {"admin": admin_s, "manager": manager_s, "staff": staff_s}[who]
        d = ok(s.get(f"{BASE}/dashboard/", timeout=120), f"dashboard {who}")
        assert isinstance(d, dict) and "meetings" in d, list(d)[:10]
        assert isinstance(d["meetings"], list)


# ───────────────────────── 4. meetings CRUD ─────────────────────────
class TestMeetings:
    def test_create_meeting_persists_uuid_fks(self, admin_s, meeting):
        assert meeting["sign_off_manager_id"] == MANAGER_ID
        assert [a["user_id"] for a in meeting["attendees"]] == [STAFF_ID]
        got = ok(admin_s.get(f"{BASE}/meetings/{meeting['id']}", timeout=90), "get meeting")
        assert got["id"] == meeting["id"] and got["title"] == P + "meeting"
        assert got["attendees"][0]["user_id"] == STAFF_ID
        assert got["attendees"][0].get("email") == "user@supervision.com"

    @pytest.mark.parametrize("who", ["admin", "manager", "staff"])
    def test_list_meetings(self, who, admin_s, manager_s, staff_s, meeting):
        s = {"admin": admin_s, "manager": manager_s, "staff": staff_s}[who]
        lst = ok(s.get(f"{BASE}/meetings/", timeout=120), f"list {who}")
        assert isinstance(lst, list) and lst
        assert meeting["id"] in [m["id"] for m in lst], f"{who} cannot see the new meeting"

    def test_update_attendees_and_manager(self, admin_s, meeting):
        mid = meeting["id"]
        ok(admin_s.put(f"{BASE}/meetings/{mid}/attendees",
                       json={"attendee_ids": [STAFF_ID, "724367a3-1ca9-498b-890b-0516b2f122f5"]},
                       timeout=90), "put attendees")
        got = ok(admin_s.get(f"{BASE}/meetings/{mid}", timeout=90), "get after attendees")
        assert len(got["attendees"]) == 2
        ok(admin_s.put(f"{BASE}/meetings/{mid}/manager",
                       json={"manager_id": "53874ad3-8a98-4fab-8993-7c1b2d57a5b0"}, timeout=90),
           "put manager")
        got = ok(admin_s.get(f"{BASE}/meetings/{mid}", timeout=90), "get after manager")
        assert got["sign_off_manager_id"] == "53874ad3-8a98-4fab-8993-7c1b2d57a5b0"
        # restore
        ok(admin_s.put(f"{BASE}/meetings/{mid}/manager", json={"manager_id": MANAGER_ID}, timeout=90))
        ok(admin_s.put(f"{BASE}/meetings/{mid}/attendees", json={"attendee_ids": [STAFF_ID]}, timeout=90))

    def test_malformed_uuid_path_is_not_500(self, admin_s):
        for path in ("/meetings/not-a-uuid", "/meetings/123", f"/meetings/{'x'*36}"):
            r = admin_s.get(f"{BASE}{path}", timeout=60)
            no500(r, f"GET {path}")
            assert r.status_code in (400, 404, 422), f"GET {path} -> {r.status_code}: {r.text[:200]}"

    def test_nonexistent_uuid_returns_404(self, admin_s):
        r = admin_s.get(f"{BASE}/meetings/{uuid.uuid4()}", timeout=60)
        assert r.status_code == 404, r.text[:200]

    def test_delete_meeting_cascades(self, admin_s):
        m = ok(admin_s.post(f"{BASE}/meetings/", json={
            "title": P + "delete_me", "date": datetime.now(timezone.utc).isoformat(),
            "attendee_ids": [STAFF_ID]}, timeout=90), "create for delete")
        mid = m["id"]
        # seed child rows across every cascading FK table
        tid, aid = str(uuid.uuid4()), str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async def seed(c):
            await c.execute(
                "INSERT INTO transcripts (id, org_id, meeting_id, text, created_at) VALUES ($1,$2,$3,$4,$5)",
                tid, ORG_A, mid, "hello", now)
            await c.execute(
                "INSERT INTO analyses (id, org_id, meeting_id, summary, created_at) VALUES ($1,$2,$3,$4,$5)",
                aid, ORG_A, mid, "sum", now)
            await c.execute(
                "INSERT INTO reviewer_comments (id, org_id, meeting_id, user_id, user_name, role, text, created_at)"
                " VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                str(uuid.uuid4()), ORG_A, mid, ADMIN_ID, "Test Admin", "admin", "c", now)
            await c.execute(
                "INSERT INTO review_edits (id, org_id, meeting_id, user_id, user_name, action, detail, timestamp)"
                " VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                str(uuid.uuid4()), ORG_A, mid, ADMIN_ID, "Test Admin", "edit", "d", now)
            await c.execute("UPDATE meetings SET transcript_id=$1, analysis_id=$2 WHERE id=$3", tid, aid, mid)
        db(seed)

        ok(admin_s.delete(f"{BASE}/meetings/{mid}", timeout=90), "delete meeting")
        counts = db(lambda c: c.fetchrow("""
            SELECT (SELECT count(*) FROM meetings WHERE id=$1) m,
                   (SELECT count(*) FROM transcripts WHERE meeting_id=$1) t,
                   (SELECT count(*) FROM analyses WHERE meeting_id=$1) a,
                   (SELECT count(*) FROM reviewer_comments WHERE meeting_id=$1) rc,
                   (SELECT count(*) FROM review_edits WHERE meeting_id=$1) re
        """, mid))
        assert dict(counts) == {"m": 0, "t": 0, "a": 0, "rc": 0, "re": 0}, dict(counts)
        assert admin_s.get(f"{BASE}/meetings/{mid}", timeout=60).status_code == 404


# ───────────────────────── 5. org structure & FKs ─────────────────────────
class TestOrg:
    def test_structure_admin(self, admin_s):
        st = ok(admin_s.get(f"{BASE}/org/structure", timeout=90), "org structure admin")
        assert isinstance(st, dict), st
        assert "settings" in st, list(st)
        for s in st["settings"]:
            assert "teams" in s
        assert "unassigned_users" in st or "unassigned" in st, list(st)

    def test_structure_manager(self, manager_s):
        no500(manager_s.get(f"{BASE}/org/structure", timeout=90), "org structure manager")

    def test_setting_team_user_lifecycle(self, admin_s):
        # create setting
        st = ok(admin_s.post(f"{BASE}/org/settings", json={"name": P + "branch"}, timeout=90), "create setting")
        sid = st.get("id") or st.get("setting", {}).get("id")
        assert sid, st
        created["settings"].append(sid)
        # edit setting
        ok(admin_s.put(f"{BASE}/org/settings/{sid}", json={"name": P + "branch2"}, timeout=90), "edit setting")
        lst = ok(admin_s.get(f"{BASE}/org/settings", timeout=90), "list settings")
        lst = lst if isinstance(lst, list) else lst.get("settings", [])
        assert any(x["name"] == P + "branch2" for x in lst), lst
        # create team under setting
        tm = ok(admin_s.post(f"{BASE}/org/settings/{sid}/teams", json={"name": P + "team"}, timeout=90),
                "create team")
        tid = tm.get("id") or tm.get("team", {}).get("id")
        assert tid, tm
        created["teams"].append(tid)
        ok(admin_s.put(f"{BASE}/org/teams/{tid}", json={"name": P + "team2"}, timeout=90), "edit team")
        # add member + assign-team
        ok(admin_s.post(f"{BASE}/org/teams/{tid}/members", json={"user_id": STAFF_ID}, timeout=90),
           "add member")
        row = db(lambda c: c.fetchrow("SELECT team_id, setting_id FROM users WHERE id=$1", STAFF_ID))
        assert str(row["team_id"]) == tid
        # structure now reflects the new setting/team/member
        stt = ok(admin_s.get(f"{BASE}/org/structure", timeout=90), "structure after create")
        target = [s for s in stt["settings"] if s["id"] == sid]
        assert target, f"new setting missing from structure: {[s['id'] for s in stt['settings']]}"
        teams = target[0]["teams"]
        assert any(t["id"] == tid for t in teams), teams
        team = [t for t in teams if t["id"] == tid][0]
        assert any(u["id"] == STAFF_ID for u in team.get("users", team.get("members", []))), team
        # assign-team endpoint
        ok(admin_s.patch(f"{BASE}/org/users/{STAFF_ID}/assign-team", json={"team_id": tid}, timeout=90),
           "assign-team")
        # remove member
        ok(admin_s.delete(f"{BASE}/org/teams/{tid}/members/{STAFF_ID}", timeout=90), "remove member")
        assert db(lambda c: c.fetchval("SELECT team_id FROM users WHERE id=$1", STAFF_ID)) is None
        # unassign via assign-team null
        no500(admin_s.patch(f"{BASE}/org/users/{STAFF_ID}/assign-team", json={"team_id": None}, timeout=90),
              "assign-team null")
        # delete team + setting
        ok(admin_s.delete(f"{BASE}/org/teams/{tid}", timeout=90), "delete team")
        ok(admin_s.delete(f"{BASE}/org/settings/{sid}", timeout=90), "delete setting")
        assert db(lambda c: c.fetchval("SELECT count(*) FROM org_settings WHERE id=$1", sid)) == 0

    def test_invite_user(self, admin_s):
        email = P + "invitee@example.com"
        r = admin_s.post(f"{BASE}/org/invite-user",
                         json={"email": email, "name": "TEST Invitee", "role": "attendee",
                               "password": "TestPass123!"}, timeout=90)
        no500(r, "invite-user")
        assert r.status_code in (200, 201), r.text[:400]
        row = db(lambda c: c.fetchrow(
            "SELECT id, org_id, role, must_change_password FROM users WHERE email=$1", email.lower()))
        assert row, "invited user row not persisted"
        assert str(row["org_id"]) == ORG_A and row["role"] == "attendee"
        assert str(row["id"]) == r.json()["id"]

    def test_branding_endpoints(self, admin_s):
        ok(admin_s.get(f"{BASE}/org/branding", timeout=60), "get branding")
        no500(admin_s.get(f"{BASE}/org/branding/logo/{ORG_A}", timeout=60), "get logo")


# ───────────────────────── 6. recording flow ─────────────────────────
class TestRecording:
    def test_full_recording_lifecycle(self, admin_s, meeting):
        mid = meeting["id"]
        ok(admin_s.post(f"{BASE}/recording/{mid}/notice", timeout=90), "notice")
        ok(admin_s.post(f"{BASE}/recording/{mid}/start", json={}, timeout=90), "start")
        assert db(lambda c: c.fetchval("SELECT status FROM meetings WHERE id=$1", mid)) == "recording"
        ok(admin_s.post(f"{BASE}/recording/{mid}/pause", json={}, timeout=90), "pause")
        ok(admin_s.post(f"{BASE}/recording/{mid}/resume", json={}, timeout=90), "resume")
        ok(admin_s.post(f"{BASE}/recording/{mid}/stop", json={}, timeout=90), "stop")
        ev = ok(admin_s.get(f"{BASE}/recording/{mid}/events", timeout=90), "events")
        events = ev if isinstance(ev, list) else ev.get("recording_events", ev.get("events", []))
        types = [e.get("type") for e in events]
        assert {"started", "paused", "resumed", "stopped"} <= set(types), types
        for e in events:
            assert e.get("user_id") == ADMIN_ID


# ───────────────────────── 7. review flow ─────────────────────────
@pytest.fixture(scope="class")
def review_meeting(admin_s):
    """Meeting with transcript + analysis in in_review state, staff as attendee."""
    m = ok(admin_s.post(f"{BASE}/meetings/", json={
        "title": P + "review", "date": datetime.now(timezone.utc).isoformat(),
        "attendee_ids": [STAFF_ID], "sign_off_manager_id": MANAGER_ID}, timeout=90), "create review meeting")
    mid = m["id"]
    created["meetings"].append(mid)
    tid, aid = str(uuid.uuid4()), str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    async def seed(c):
        await c.execute(
            "INSERT INTO transcripts (id, org_id, meeting_id, text, speaker_text, created_at)"
            " VALUES ($1,$2,$3,$4,$5,$6)",
            tid, ORG_A, mid, "Manager: hello there\nStaff: hi", "Manager: hello there\nStaff: hi", now)
        await c.execute(
            "INSERT INTO analyses (id, org_id, meeting_id, summary, actions, risks,"
            " learning_needs, achievements, created_at)"
            " VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7::jsonb,$8::jsonb,$9)",
            aid, ORG_A, mid, "A summary",
            json.dumps([{"id": "a1", "text": "do thing", "completed": False}]),
            json.dumps([]), json.dumps([]), json.dumps([]), now)
        await c.execute(
            "UPDATE meetings SET transcript_id=$1, analysis_id=$2, status='in_review' WHERE id=$3",
            tid, aid, mid)
    db(seed)
    return {"id": mid, "transcript_id": tid, "analysis_id": aid}


class TestReview:
    def test_get_review(self, admin_s, review_meeting):
        r = ok(admin_s.get(f"{BASE}/review/{review_meeting['id']}", timeout=90), "get review")
        assert r.get("meeting", r).get("id") == review_meeting["id"] or r.get("id") == review_meeting["id"]

    def test_summary_edit_writes_review_edit_with_uuid_user(self, admin_s, review_meeting):
        mid = review_meeting["id"]
        ok(admin_s.put(f"{BASE}/review/{mid}/summary", json={"summary": "Edited summary TEST"}, timeout=90),
           "put summary")
        row = db(lambda c: c.fetchrow(
            "SELECT user_id, user_name, action, detail FROM review_edits WHERE meeting_id=$1"
            " ORDER BY timestamp DESC LIMIT 1", mid))
        assert row and str(row["user_id"]) == ADMIN_ID, dict(row) if row else None
        val = db(lambda c: c.fetchval("SELECT edited_summary FROM analyses WHERE id=$1",
                                      review_meeting["analysis_id"]))
        assert val == "Edited summary TEST"

    def test_speaker_text_edit(self, admin_s, review_meeting):
        mid = review_meeting["id"]
        r = admin_s.patch(f"{BASE}/review/{mid}/speaker-text",
                          json={"speaker_text": "Manager: edited line\nStaff: ok"}, timeout=120)
        ok(r, "patch speaker-text")
        st = db(lambda c: c.fetchrow(
            "SELECT speaker_text, speaker_text_backup_by FROM transcripts WHERE id=$1",
            review_meeting["transcript_id"]))
        assert "edited line" in st["speaker_text"]

    def test_comments_roundtrip(self, admin_s, manager_s, review_meeting):
        mid = review_meeting["id"]
        ok(admin_s.post(f"{BASE}/review/{mid}/comments", json={"text": "TEST admin comment"}, timeout=90),
           "post comment admin")
        ok(manager_s.post(f"{BASE}/review/{mid}/comments", json={"text": "TEST manager comment"}, timeout=90),
           "post comment manager")
        cs = ok(admin_s.get(f"{BASE}/review/{mid}/comments", timeout=90), "get comments")
        items = cs if isinstance(cs, list) else cs.get("comments", [])
        assert len(items) >= 2, items
        uids = {c["user_id"] for c in items}
        assert {ADMIN_ID, MANAGER_ID} <= uids, uids
        rows = db(lambda c: c.fetch("SELECT user_id FROM reviewer_comments WHERE meeting_id=$1", mid))
        assert len(rows) >= 2

    def test_audit_trail(self, admin_s, review_meeting):
        a = ok(admin_s.get(f"{BASE}/review/{review_meeting['id']}/audit-trail", timeout=120), "audit trail")
        assert isinstance(a, (list, dict))

    def test_action_toggle(self, admin_s, review_meeting):
        r = admin_s.patch(f"{BASE}/review/{review_meeting['id']}/actions/a1",
                          json={"completed": True}, timeout=90)
        no500(r, "toggle action")
        assert r.status_code == 200, r.text[:300]

    def test_mark_reviewed_then_signoff_then_reopen(self, admin_s, staff_s, manager_s, review_meeting):
        mid = review_meeting["id"]
        # staff attendee marks reviewed
        res = ok(staff_s.post(f"{BASE}/review/{mid}/mark-reviewed", timeout=90), "mark-reviewed staff")
        assert res["status"] in ("reviewed", "in_review")
        if res["status"] != "reviewed":
            db(lambda c: c.execute("UPDATE meetings SET status='reviewed' WHERE id=$1", mid))
        # manager signs off
        so = ok(manager_s.post(f"{BASE}/review/{mid}/signoff", timeout=120), "signoff")
        assert "signed_at" in so
        rec = db(lambda c: c.fetchrow("SELECT status, sign_off_record FROM meetings WHERE id=$1", mid))
        assert rec["status"] == "signed_off"
        sor = rec["sign_off_record"]
        sor = json.loads(sor) if isinstance(sor, str) else sor
        assert sor["signed_by"] == MANAGER_ID
        # share (only allowed post sign-off) — exercises shared_with uuid batch lookup
        SARAH = "53874ad3-8a98-4fab-8993-7c1b2d57a5b0"  # manager role — shareable
        sh = admin_s.post(f"{BASE}/review/{mid}/share", json={"user_ids": [SARAH]}, timeout=90)
        no500(sh, "share after signoff")
        assert sh.status_code in (200, 201), sh.text[:300]
        shared = db(lambda c: c.fetchval("SELECT shared_with FROM meetings WHERE id=$1", mid))
        shared = json.loads(shared) if isinstance(shared, str) else shared
        assert any(x.get("user_id") == SARAH for x in shared), shared
        # manager requests reopen
        rr = manager_s.post(f"{BASE}/review/{mid}/request-reopen", json={"reason": "TEST reopen"}, timeout=90)
        no500(rr, "request-reopen")
        assert rr.status_code == 200, rr.text[:300]
        req = db(lambda c: c.fetchval("SELECT reopen_requested_by FROM meetings WHERE id=$1", mid))
        assert str(req) == MANAGER_ID, req
        # admin approves
        ar = admin_s.post(f"{BASE}/review/{mid}/approve-reopen", json={"approve": True}, timeout=90)
        no500(ar, "approve-reopen")
        assert ar.status_code == 200, ar.text[:300]
        after = db(lambda c: c.fetchrow(
            "SELECT status, reopen_approved_by, reopen_requested_by FROM meetings WHERE id=$1", mid))
        assert after["status"] != "signed_off", dict(after)
        assert str(after["reopen_approved_by"]) == ADMIN_ID

    def test_export_transcript_and_pdf(self, admin_s, review_meeting):
        mid = review_meeting["id"]
        no500(admin_s.get(f"{BASE}/review/{mid}/export-transcript", timeout=120), "export-transcript")
        no500(admin_s.get(f"{BASE}/review/{mid}/export-pdf", timeout=180), "export-pdf")


# ───────────────────────── 8. prep ─────────────────────────
class TestPrep:
    def test_focus_topics_crud(self, admin_s):
        t = ok(admin_s.post(f"{BASE}/prep/focus-topics", json={"topic": P + "topic"}, timeout=90),
               "create topic")
        tid = t["id"]
        assert db(lambda c: c.fetchval("SELECT created_by FROM focus_topics WHERE id=$1", tid)) is not None
        ok(admin_s.put(f"{BASE}/prep/focus-topics/{tid}", json={"topic": P + "topic2"}, timeout=90),
           "update topic")
        lst = ok(admin_s.get(f"{BASE}/prep/focus-topics", timeout=90), "list topics")
        items = lst if isinstance(lst, list) else lst.get("topics", [])
        assert any(x["id"] == tid for x in items)
        ok(admin_s.delete(f"{BASE}/prep/focus-topics/{tid}", timeout=90), "delete topic")

    def test_prep_context_and_get(self, admin_s, meeting):
        no500(admin_s.get(f"{BASE}/prep/{meeting['id']}/context", timeout=120), "prep context")
        no500(admin_s.get(f"{BASE}/prep/{meeting['id']}", timeout=120), "prep get")

    def test_prep_save_and_share(self, admin_s, meeting):
        mid = meeting["id"]
        r = admin_s.put(f"{BASE}/prep/{mid}", json={
            "agenda_items": [{"id": "1", "text": "TEST agenda"}], "notes": "TEST notes"}, timeout=120)
        no500(r, "prep put")
        if r.status_code == 200:
            row = db(lambda c: c.fetchrow(
                "SELECT org_id, meeting_id, created_by FROM meeting_prep WHERE meeting_id=$1", mid))
            assert row and str(row["org_id"]) == ORG_A and str(row["meeting_id"]) == mid
            assert str(row["created_by"]) == ADMIN_ID
            sh = admin_s.post(f"{BASE}/prep/{mid}/share", json={}, timeout=120)
            no500(sh, "prep share")


# ───────────────────────── 9. schedules ─────────────────────────
class TestSchedules:
    def test_meeting_types_and_schedule_crud(self, admin_s):
        types = ok(admin_s.get(f"{BASE}/schedules/meeting-types", timeout=90), "meeting types")
        items = types if isinstance(types, list) else types.get("meeting_types", [])
        assert items, types
        mt_id = items[0]["id"]
        r = admin_s.post(f"{BASE}/schedules/", json={
            "staff_user_id": STAFF_ID, "meeting_type_id": mt_id,
            "frequency": "monthly", "start_date": datetime.now(timezone.utc).date().isoformat()}, timeout=90)
        no500(r, "create schedule")
        if r.status_code in (200, 201):
            sid = r.json().get("id") or r.json().get("schedule", {}).get("id")
            if sid:
                created["schedules"].append(sid)
                row = db(lambda c: c.fetchrow(
                    "SELECT staff_user_id, meeting_type_id, created_by FROM schedules WHERE id=$1", sid))
                assert str(row["staff_user_id"]) == STAFF_ID
                assert str(row["meeting_type_id"]) == str(mt_id)
                ok(admin_s.put(f"{BASE}/schedules/{sid}",
                               json={"frequency": "quarterly",
                                     "start_date": datetime.now(timezone.utc).date().isoformat(),
                                     "meeting_type_id": mt_id}, timeout=90), "update schedule")
                ok(admin_s.delete(f"{BASE}/schedules/{sid}", timeout=90), "delete schedule")
        lst = ok(admin_s.get(f"{BASE}/schedules/", timeout=90), "list schedules")
        assert isinstance(lst, (list, dict))
        no500(admin_s.get(f"{BASE}/schedules/due", timeout=90), "schedules due")


# ───────────────────────── 10. admin endpoints (batch uuid[] casts) ─────────────────────────
class TestAdmin:
    def test_users_list(self, admin_s):
        u = ok(admin_s.get(f"{BASE}/admin/users", timeout=90), "admin users")
        items = u if isinstance(u, list) else u.get("users", [])
        assert any(x["email"] == "user@supervision.com" for x in items), len(items)

    @pytest.mark.parametrize("path", [
        "/admin/standards", "/admin/standards/documents", "/admin/stats", "/admin/template",
        "/admin/team-insights", "/admin/people-stats", "/admin/team-insights/action-stats",
        "/admin/team-insights/registers", "/admin/meetings-brief", "/admin/integrations/health",
    ])
    def test_admin_get_endpoints(self, admin_s, path):
        r = admin_s.get(f"{BASE}{path}", timeout=180)
        no500(r, f"GET {path}")
        assert r.status_code == 200, f"GET {path} -> {r.status_code}: {r.text[:300]}"

    def test_export_batches_use_uuid_array_cast(self, admin_s):
        mids = db(lambda c: c.fetch(
            "SELECT id FROM meetings WHERE org_id=$1 AND analysis_id IS NOT NULL LIMIT 5", ORG_A))
        ids = [str(r["id"]) for r in mids]
        assert ids, "no analysed meetings to batch over"
        r = admin_s.post(f"{BASE}/admin/export-evidence", json={"meeting_ids": ids}, timeout=180)
        no500(r, "export-evidence batch")
        r2 = admin_s.post(f"{BASE}/admin/export-transcripts", json={"meeting_ids": ids}, timeout=180)
        no500(r2, "export-transcripts batch")
        r3 = admin_s.get(f"{BASE}/admin/export-cqc-excerpts", timeout=180)
        no500(r3, "export-cqc-excerpts")

    def test_admin_user_debug_endpoints(self, admin_s):
        no500(admin_s.get(f"{BASE}/admin/users/{STAFF_ID}/debug", timeout=90), "user debug")
        no500(admin_s.get(f"{BASE}/admin/users/debug-by-email",
                          params={"email": "user@supervision.com"}, timeout=90), "debug-by-email")

    def test_admin_user_crud(self, admin_s):
        email = P + "adminuser@example.com"
        r = admin_s.post(f"{BASE}/admin/users", json={
            "email": email, "name": "TEST AdminUser", "role": "attendee", "password": "TestPass123!"},
            timeout=90)
        no500(r, "admin create user")
        if r.status_code in (200, 201):
            uid = r.json().get("id") or r.json().get("user", {}).get("id")
            assert uid
            created["users"].append(uid)
            ok(admin_s.put(f"{BASE}/admin/users/{uid}", json={"name": "TEST Renamed"}, timeout=90),
               "admin update user")
            assert db(lambda c: c.fetchval("SELECT name FROM users WHERE id=$1", uid)) == "TEST Renamed"
            ok(admin_s.delete(f"{BASE}/admin/users/{uid}", timeout=90), "admin delete user")


# ───────────────────────── 11. portfolio & doc uploads ─────────────────────────
class TestPortfolioAndDocs:
    def test_portfolio(self, admin_s):
        r = admin_s.get(f"{BASE}/portfolio/{STAFF_ID}", timeout=180)
        no500(r, "portfolio")
        assert r.status_code == 200, r.text[:300]

    def test_doc_uploads_list(self, admin_s):
        r = admin_s.get(f"{BASE}/doc-uploads/", timeout=90)
        no500(r, "doc uploads list")
        assert r.status_code == 200


# ───────────────────────── 12. super admin ─────────────────────────
class TestSuperAdmin:
    def test_list_orgs(self, super_s):
        o = ok(super_s.get(f"{BASE}/super-admin/orgs", timeout=90), "list orgs")
        items = o if isinstance(o, list) else o.get("orgs", [])
        assert any(str(x["id"]) == ORG_A for x in items), items

    def test_create_org_and_detail(self, super_s):
        r = super_s.post(f"{BASE}/super-admin/orgs", json={
            "name": P + "org", "jurisdiction": "england"}, timeout=90)
        no500(r, "create org")
        assert r.status_code in (200, 201), r.text[:400]
        oid = r.json().get("id") or r.json().get("org", {}).get("id")
        assert oid, r.text[:300]
        created["orgs"].append(oid)
        u = super_s.get(f"{BASE}/super-admin/orgs/{oid}/users", timeout=90)
        no500(u, "org users")
        assert u.status_code == 200
        p = super_s.patch(f"{BASE}/super-admin/orgs/{oid}", json={"name": P + "org2"}, timeout=90)
        no500(p, "patch org")
        d = super_s.delete(f"{BASE}/super-admin/orgs/{oid}", timeout=90)
        no500(d, "delete org")
        if d.status_code == 200:
            created["orgs"].remove(oid)
            assert db(lambda c: c.fetchval("SELECT count(*) FROM organisations WHERE id=$1", oid)) == 0


# ───────────────────────── 13. cross-org RLS isolation ─────────────────────────
class TestRLSIsolation:
    def test_org_b_meeting_invisible_to_org_a_admin(self, admin_s):
        mid = db(lambda c: c.fetchval("SELECT id FROM meetings WHERE org_id=$1 LIMIT 1", ORG_B))
        assert mid, "no org B meeting fixture"
        r = admin_s.get(f"{BASE}/meetings/{mid}", timeout=90)
        assert r.status_code == 404, f"cross-org read leaked: {r.status_code} {r.text[:300]}"
        lst = ok(admin_s.get(f"{BASE}/meetings/", timeout=120), "list for leak check")
        assert str(mid) not in [m["id"] for m in lst], "org B meeting appears in org A list"

    def test_org_b_meeting_invisible_to_org_a_staff_and_manager(self, staff_s, manager_s):
        mid = str(db(lambda c: c.fetchval("SELECT id FROM meetings WHERE org_id=$1 LIMIT 1", ORG_B)))
        for name, s in (("staff", staff_s), ("manager", manager_s)):
            r = s.get(f"{BASE}/meetings/{mid}", timeout=90)
            assert r.status_code == 404, f"{name} cross-org read leaked: {r.status_code}"
            lst = ok(s.get(f"{BASE}/meetings/", timeout=120), f"list {name}")
            assert mid not in [m["id"] for m in lst], f"{name}: org B meeting leaked into list"

    def test_rls_policies_enforced_at_db_level(self):
        async def probe(c):
            out = {}
            await c.execute("SELECT set_config('app.current_org_id', $1, false)", ORG_A)
            await c.execute("SET ROLE app_rls_user")
            for table in ("meetings", "org_settings", "teams", "users", "analyses", "transcripts"):
                total_visible = await c.fetchval(f"SELECT count(*) FROM {table}")
                foreign = await c.fetchval(f"SELECT count(*) FROM {table} WHERE org_id::text <> $1", ORG_A)
                out[table] = (total_visible, foreign)
            await c.execute("RESET ROLE")
            return out
        res = db(probe)
        for table, (visible, foreign) in res.items():
            assert foreign == 0, f"RLS leak on {table}: {foreign} foreign-org rows visible (total {visible})"
        # Only invariant that matters: zero foreign-org rows, and the org's own
        # rows are still readable (absolute count drifts as tests seed data).
        assert res["meetings"][0] > 0, f"org A sees none of its own meetings: {res['meetings']}"

    def test_rls_blocks_empty_org_context(self):
        async def probe(c):
            await c.execute("SELECT set_config('app.current_org_id', '', false)")
            await c.execute("SET ROLE app_rls_user")
            n = await c.fetchval("SELECT count(*) FROM meetings")
            await c.execute("RESET ROLE")
            return n
        assert db(probe) == 0, "empty org context exposed rows (NULLIF cast broken)"

    def test_rls_write_denied_for_foreign_org(self):
        async def probe(c):
            await c.execute("SELECT set_config('app.current_org_id', $1, false)", ORG_A)
            await c.execute("SET ROLE app_rls_user")
            err = None
            try:
                await c.execute(
                    "INSERT INTO meetings (id, org_id, title, date, status, created_at, updated_at)"
                    " VALUES ($1,$2,$3,$4,'draft',now(),now())",
                    str(uuid.uuid4()), ORG_B, P + "rls_violation", datetime.now(timezone.utc))
            except Exception as e:
                err = type(e).__name__
            await c.execute("RESET ROLE")
            return err
        assert db(probe) is not None, "WITH CHECK policy allowed a cross-org INSERT"


# ───────────── 14. team-scoped manager (uuid = text risk in scoped branches) ─────────────
@pytest.fixture(scope="class")
def scoped_manager(admin_s):
    """Put manager@supervision.com in a TEST_ setting+team so get_manager_scope()
    returns a team-level scope, exercising every `scope['level'] != 'org'` SQL branch."""
    st = ok(admin_s.post(f"{BASE}/org/settings", json={"name": P + "scope_branch"}, timeout=90))
    sid = st["id"] if isinstance(st, dict) and "id" in st else st["setting"]["id"]
    created["settings"].append(sid)
    tm = ok(admin_s.post(f"{BASE}/org/settings/{sid}/teams", json={"name": P + "scope_team"}, timeout=90))
    tid = tm["id"] if isinstance(tm, dict) and "id" in tm else tm["team"]["id"]
    created["teams"].append(tid)
    db(lambda c: c.execute("UPDATE users SET team_id=$1, setting_id=$2 WHERE id = ANY($3::uuid[])",
                           tid, sid, [MANAGER_ID, STAFF_ID]))
    s = login("manager@supervision.com", "Manager123!")
    yield s
    db(lambda c: c.execute("UPDATE users SET team_id=NULL, setting_id=NULL WHERE id = ANY($1::uuid[])",
                           [MANAGER_ID, STAFF_ID]))


class TestScopedManager:
    def test_scope_is_team_level(self, scoped_manager):
        me = ok(scoped_manager.get(f"{BASE}/auth/me", timeout=60), "scoped me")
        assert me["team_id"] is not None, me

    @pytest.mark.parametrize("path", [
        "/dashboard/", "/meetings/", "/org/structure", "/admin/meetings-brief",
        "/admin/team-insights", "/admin/people-stats", "/admin/team-insights/action-stats",
        "/admin/team-insights/registers", "/admin/stats", "/admin/users", "/schedules/",
    ])
    def test_scoped_manager_get_endpoints(self, scoped_manager, path):
        r = scoped_manager.get(f"{BASE}{path}", timeout=180)
        no500(r, f"scoped manager GET {path}")
        assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:300]}"

    def test_scoped_manager_export_batches(self, scoped_manager):
        r = scoped_manager.post(f"{BASE}/admin/export-evidence", json={"format": "csv"}, timeout=180)
        no500(r, "scoped export-evidence")
        r2 = scoped_manager.post(f"{BASE}/admin/export-transcripts", json={}, timeout=180)
        no500(r2, "scoped export-transcripts")

    def test_export_evidence_with_staff_ids_filter(self, admin_s):
        r = admin_s.post(f"{BASE}/admin/export-evidence",
                         json={"format": "csv", "staff_ids": [STAFF_ID]}, timeout=180)
        no500(r, "export-evidence staff_ids filter")

    def test_scoped_manager_structure_scoped_only(self, scoped_manager):
        st = ok(scoped_manager.get(f"{BASE}/org/structure", timeout=90), "scoped structure")
        assert isinstance(st, dict) and "settings" in st


# ───────────── 15. supervision template (settings table id key) ─────────────
class TestSupervisionTemplate:
    def test_get_template(self, admin_s):
        r = admin_s.get(f"{BASE}/admin/template", timeout=90)
        no500(r, "GET /admin/template")
        assert r.status_code == 200, r.text[:300]

    def test_save_template(self, admin_s):
        """Non-destructive: snapshot the org template, write, then restore it.
        (iter109 fix — this test previously left 'TEST template'/'TEST step' as
        the org's live supervision template, polluting real org data.)"""
        before = admin_s.get(f"{BASE}/admin/template", timeout=90)
        assert before.status_code == 200, before.text[:300]
        original = before.json()
        try:
            r = admin_s.put(f"{BASE}/admin/template",
                            json={"steps": [{"id": "s1", "title": "TEST step"}],
                                  "name": "TEST template", "description": ""}, timeout=90)
            no500(r, "PUT /admin/template")
            assert r.status_code == 200, r.text[:300]
        finally:
            admin_s.put(f"{BASE}/admin/template", json=original, timeout=90)

    def test_template_lookup_used_by_pipeline(self):
        """The analysis pipeline and review rescan both look up
        settings WHERE id='supervision_template:<org>' — a non-UUID key."""
        async def probe(c):
            try:
                await c.fetchrow("SELECT data FROM settings WHERE id=$1",
                                 f"supervision_template:{ORG_A}")
                return None
            except Exception as e:
                return f"{type(e).__name__}: {e}"
        err = db(probe)
        assert err is None, f"settings id lookup broken: {err}"


# ───────────── 16. review rescan-evidence (template + uuid batch) ─────────────
class TestRescan:
    def test_rescan_evidence(self, admin_s):
        mid = str(db(lambda c: c.fetchval(
            "SELECT m.id FROM meetings m WHERE m.org_id=$1 AND m.analysis_id IS NOT NULL"
            " AND m.transcript_id IS NOT NULL LIMIT 1", ORG_A)))
        r = admin_s.post(f"{BASE}/review/{mid}/rescan-evidence", json={}, timeout=280)
        no500(r, f"rescan-evidence {mid}")
