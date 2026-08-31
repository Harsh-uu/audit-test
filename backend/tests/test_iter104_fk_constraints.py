"""Iteration 104 — regression suite for the 37 FOREIGN KEY constraints migration.

Covers:
  • schema audit (all 37 FKs present, correct ON DELETE action, zero orphans)
  • negative enforcement (bad parent refs rejected by Postgres)
  • meeting lifecycle + delete cascade (API + raw DB level)
  • org structure (setting/team/staff delete → SET NULL)
  • user deletion while referenced as supervisor/manager/schedule staff
  • schedule ↔ meeting_type SET NULL
  • CRUD smoke across admin / manager / attendee roles
  • regression on iteration_98..103 fixes (exports, share, org structure)

Run with:  cd /app/backend && python3 -m pytest tests/test_iter104_fk_constraints.py -n 0 -q
(-n 0 is mandatory: parallel workers race on the shared-account MFA override.)
"""
import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

BE = dotenv_values("/app/backend/.env")
FE = dotenv_values("/app/frontend/.env")
BASE = FE["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = BE["DATABASE_URL"]

ORG = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"
P = "TEST_iter104_"

ACT = {"a": "NO ACTION", "r": "RESTRICT", "c": "CASCADE", "n": "SET NULL", "d": "SET DEFAULT"}

EXPECTED_FKS = {
    ("users", "org_id", "organisations"): "CASCADE",
    ("users", "team_id", "teams"): "SET NULL",
    ("users", "setting_id", "org_settings"): "SET NULL",
    ("meetings", "org_id", "organisations"): "CASCADE",
    ("meetings", "team_id", "teams"): "SET NULL",
    ("meetings", "setting_id", "org_settings"): "SET NULL",
    ("meetings", "schedule_id", "schedules"): "SET NULL",
    ("transcripts", "meeting_id", "meetings"): "CASCADE",
    ("transcripts", "org_id", "organisations"): "CASCADE",
    ("analyses", "meeting_id", "meetings"): "CASCADE",
    ("analyses", "org_id", "organisations"): "CASCADE",
    ("audio_files", "meeting_id", "meetings"): "CASCADE",
    ("audio_files", "org_id", "organisations"): "CASCADE",
    ("review_edits", "meeting_id", "meetings"): "CASCADE",
    ("review_edits", "org_id", "organisations"): "CASCADE",
    ("reviewer_comments", "meeting_id", "meetings"): "CASCADE",
    ("reviewer_comments", "org_id", "organisations"): "CASCADE",
    ("audit_logs", "meeting_id", "meetings"): "CASCADE",
    ("audit_logs", "org_id", "organisations"): "CASCADE",
    ("org_settings", "org_id", "organisations"): "CASCADE",
    ("org_settings", "manager_user_id", "users"): "SET NULL",
    ("teams", "org_id", "organisations"): "CASCADE",
    ("teams", "setting_id", "org_settings"): "SET NULL",
    ("teams", "supervisor_user_id", "users"): "SET NULL",
    ("standards_entries", "org_id", "organisations"): "CASCADE",
    ("standards_documents", "org_id", "organisations"): "CASCADE",
    ("invitations", "org_id", "organisations"): "CASCADE",
    ("settings", "org_id", "organisations"): "CASCADE",
    ("meeting_types", "org_id", "organisations"): "CASCADE",
    ("focus_topics", "org_id", "organisations"): "CASCADE",
    ("meeting_prep", "org_id", "organisations"): "CASCADE",
    ("meeting_prep", "meeting_id", "meetings"): "CASCADE",
    ("schedules", "org_id", "organisations"): "CASCADE",
    ("schedules", "staff_user_id", "users"): "SET NULL",
    ("schedules", "meeting_type_id", "meeting_types"): "SET NULL",
    ("supervision_uploads", "org_id", "organisations"): "CASCADE",
    ("supervision_uploads", "staff_id", "users"): "SET NULL",
}


# ── infra helpers ─────────────────────────────────────────────────────────────
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


def clear_limits():
    db(lambda c: c.execute("DELETE FROM login_attempts"))


def login(email, password):
    clear_limits()
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=90)
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text[:300]}"
    data = r.json()
    if data.get("requires_mfa"):
        h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
        exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        db(lambda c: c.execute(
            "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
            h, exp, email))
        r2 = s.post(f"{BASE}/auth/verify-mfa",
                    json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=90)
        assert r2.status_code == 200, f"mfa failed {r2.status_code}: {r2.text[:300]}"
    me = s.get(f"{BASE}/auth/me", timeout=60)
    assert me.status_code == 200, f"/auth/me failed {me.status_code}"
    return s


@pytest.fixture(scope="session")
def admin_s():
    return login("admin@supervision.com", "Admin123!")


@pytest.fixture(scope="session")
def manager_s():
    return login("manager@supervision.com", "Manager123!")


@pytest.fixture(scope="session")
def jane_s():
    return login("jane@supervision.com", "Jane123!")


@pytest.fixture(scope="session")
def jane_id():
    return db(lambda c: c.fetchval("SELECT id FROM users WHERE email='jane@supervision.com'"))


def make_temp_user(admin_s, suffix, role="attendee"):
    """Create a throwaway org user via the admin API (must_change_password=True
    → DELETE /admin/users/{id} performs a real row delete, which is what
    exercises the new SET NULL constraints)."""
    email = f"{P}{suffix}_{uuid.uuid4().hex[:6]}@example.com"
    r = admin_s.post(f"{BASE}/admin/users",
                     json={"email": email, "name": f"{P}{suffix}", "role": role,
                           "password": "TempPass123!"}, timeout=90)
    assert r.status_code == 200, f"create user failed {r.status_code}: {r.text[:300]}"
    return r.json()["id"], email


def hard_delete_user(uid):
    db(lambda c: c.execute("DELETE FROM users WHERE id=$1", uid))


# ── 1. SCHEMA AUDIT ───────────────────────────────────────────────────────────
FK_QUERY = """
SELECT con.conname, src.relname AS child, tgt.relname AS parent, con.confdeltype,
       (SELECT string_agg(a.attname, ',') FROM unnest(con.conkey) k
          JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k) AS cols
FROM pg_constraint con
JOIN pg_class src ON src.oid = con.conrelid
JOIN pg_class tgt ON tgt.oid = con.confrelid
JOIN pg_namespace n ON n.oid = src.relnamespace
WHERE con.contype='f' AND n.nspname='public'
"""


def fetch_fks():
    rows = db(lambda c: c.fetch(FK_QUERY))
    out = {}
    for r in rows:
        d = r["confdeltype"]
        d = d.decode() if isinstance(d, bytes) else d
        out[(r["child"], r["cols"], r["parent"])] = ACT[d]
    return out


class TestFKSchema:
    def test_all_37_fks_present_with_correct_delete_action(self):
        actual = fetch_fks()
        assert len(actual) == 37, f"expected 37 FKs, found {len(actual)}: {sorted(actual)}"
        missing = {k: v for k, v in EXPECTED_FKS.items() if k not in actual}
        assert not missing, f"missing FKs: {missing}"
        wrong = {k: (actual[k], v) for k, v in EXPECTED_FKS.items() if actual[k] != v}
        assert not wrong, f"wrong ON DELETE action (actual, expected): {wrong}"

    def test_no_orphans_in_any_constrained_relationship(self):
        actual = fetch_fks()

        async def check(c):
            bad = {}
            for (child, col, parent) in actual:
                n = await c.fetchval(
                    f"SELECT count(*) FROM {child} t WHERE t.{col} IS NOT NULL "
                    f"AND NOT EXISTS (SELECT 1 FROM {parent} p WHERE p.id = t.{col})")
                if n:
                    bad[f"{child}.{col}->{parent}"] = n
            return bad

        assert not db(check), f"orphan rows found: {db(check)}"

    def test_preexisting_audit_log_orphans_cleaned_up(self):
        n = db(lambda c: c.fetchval(
            "SELECT count(*) FROM audit_logs a WHERE a.meeting_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM meetings m WHERE m.id=a.meeting_id)"))
        assert n == 0, f"{n} orphan audit_logs rows remain"

    def test_deliberately_excluded_relationships_are_not_constrained(self):
        actual = fetch_fks()
        for k in [("jobs", "meeting_id", "meetings"),
                  ("invitations", "user_id", "users"),
                  ("meetings", "created_by", "users"),
                  ("meetings", "sign_off_manager_id", "users"),
                  ("meetings", "transcript_id", "transcripts"),
                  ("meetings", "analysis_id", "analyses"),
                  ("meetings", "audio_file_id", "audio_files")]:
            assert k not in actual, f"{k} was documented as excluded but is constrained"


# ── 2. NEGATIVE ENFORCEMENT ───────────────────────────────────────────────────
class TestNegativeEnforcement:
    def test_meeting_with_bogus_org_id_rejected(self):
        with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
            db(lambda c: c.execute(
                "INSERT INTO meetings (id, org_id, title, status) VALUES ($1,$2,$3,$4)",
                f"{P}bad_meeting", "does-not-exist-org", f"{P}bad", "draft"))
        assert db(lambda c: c.fetchval(
            "SELECT count(*) FROM meetings WHERE id=$1", f"{P}bad_meeting")) == 0

    def test_transcript_with_bogus_meeting_id_rejected(self):
        with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
            db(lambda c: c.execute(
                "INSERT INTO transcripts (id, meeting_id, org_id, text) VALUES ($1,$2,$3,$4)",
                f"{P}bad_tr", "no-such-meeting", ORG, "x"))

    def test_team_with_bogus_setting_id_rejected(self):
        with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
            db(lambda c: c.execute(
                "INSERT INTO teams (id, org_id, setting_id, name) VALUES ($1,$2,$3,$4)",
                f"{P}bad_team", ORG, "no-such-setting", f"{P}bad"))

    def test_schedule_with_bogus_staff_user_rejected(self):
        with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
            db(lambda c: c.execute(
                "INSERT INTO schedules (id, org_id, staff_user_id, frequency) VALUES ($1,$2,$3,$4)",
                f"{P}bad_sched", ORG, "no-such-user", "monthly"))


# ── 3. MEETING LIFECYCLE + CASCADE ────────────────────────────────────────────
CHILD_TABLES = ["transcripts", "analyses", "audio_files", "review_edits",
                "reviewer_comments", "audit_logs", "meeting_prep"]


def child_counts(meeting_id):
    async def go(c):
        return {t: await c.fetchval(f"SELECT count(*) FROM {t} WHERE meeting_id=$1", meeting_id)
                for t in CHILD_TABLES}
    return db(go)


@pytest.fixture
def full_meeting(admin_s, jane_id):
    """Create a meeting through the API and populate every constrained child table."""
    now = datetime.now(timezone.utc).isoformat()
    r = admin_s.post(f"{BASE}/meetings/", json={
        "title": f"{P}lifecycle", "date": now[:10], "location": "Room 1",
        "meeting_type": "supervision", "attendee_ids": [jane_id]}, timeout=90)
    assert r.status_code == 200, f"create meeting failed {r.status_code}: {r.text[:300]}"
    mid = r.json()["id"]
    tid, aid, fid = f"{P}tr_{mid[:8]}", f"{P}an_{mid[:8]}", f"{P}af_{mid[:8]}"

    async def seed(c):
        await c.execute("INSERT INTO transcripts (id, meeting_id, org_id, text, created_at) VALUES ($1,$2,$3,$4,$5)",
                        tid, mid, ORG, "hello world transcript", now)
        await c.execute("INSERT INTO analyses (id, meeting_id, org_id, summary, created_at) VALUES ($1,$2,$3,$4,$5)",
                        aid, mid, ORG, "summary text", now)
        await c.execute("INSERT INTO audio_files (id, meeting_id, org_id, storage_path, created_at) VALUES ($1,$2,$3,$4,$5)",
                        fid, mid, ORG, "audio/x.webm", now)
        await c.execute("INSERT INTO meeting_prep (id, meeting_id, org_id, created_at) VALUES ($1,$2,$3,$4)",
                        f"{P}prep_{mid[:8]}", mid, ORG, now)
        await c.execute("INSERT INTO audit_logs (id, meeting_id, org_id, action, user_id, timestamp) VALUES ($1,$2,$3,$4,$5,$6)",
                        f"{P}al_{mid[:8]}", mid, ORG, "seeded", "x", now)
        await c.execute(
            "UPDATE meetings SET transcript_id=$1, analysis_id=$2, audio_file_id=$3, status='in_review' WHERE id=$4",
            tid, aid, fid, mid)
    db(seed)
    yield mid
    db(lambda c: c.execute("DELETE FROM meetings WHERE id=$1", mid))


class TestMeetingLifecycle:
    def test_review_edit_and_comment_created_via_api(self, admin_s, full_meeting):
        mid = full_meeting
        r = admin_s.put(f"{BASE}/review/{mid}/summary", json={"summary": f"{P}edited summary"}, timeout=90)
        assert r.status_code == 200, f"summary update {r.status_code}: {r.text[:300]}"
        r = admin_s.post(f"{BASE}/review/{mid}/comments", json={"text": f"{P}a comment"}, timeout=90)
        assert r.status_code == 200, f"comment {r.status_code}: {r.text[:300]}"
        counts = child_counts(mid)
        assert counts["review_edits"] >= 1, counts
        assert counts["reviewer_comments"] >= 1, counts

    def test_signoff_then_delete_cascades_everything(self, admin_s, full_meeting, jane_id):
        mid = full_meeting
        admin_s.put(f"{BASE}/review/{mid}/summary", json={"summary": f"{P}s"}, timeout=90)
        admin_s.post(f"{BASE}/review/{mid}/comments", json={"text": f"{P}c"}, timeout=90)

        # mark all attendees reviewed so sign-off is permitted
        async def mark(c):
            raw = await c.fetchval("SELECT attendees FROM meetings WHERE id=$1", mid)
            att = json.loads(raw) if isinstance(raw, str) else (raw or [])
            for a in att:
                a["reviewed"] = True
            await c.execute("UPDATE meetings SET attendees=$1::jsonb, status='reviewed' WHERE id=$2",
                            json.dumps(att), mid)
        db(mark)

        r = admin_s.post(f"{BASE}/review/{mid}/signoff", timeout=120)
        assert r.status_code == 200, f"signoff {r.status_code}: {r.text[:300]}"

        before = child_counts(mid)
        assert all(v >= 1 for v in before.values()), f"seed incomplete: {before}"

        r = admin_s.delete(f"{BASE}/meetings/{mid}", timeout=120)
        assert r.status_code == 200, f"delete meeting {r.status_code}: {r.text[:300]}"

        assert db(lambda c: c.fetchval("SELECT count(*) FROM meetings WHERE id=$1", mid)) == 0
        after = child_counts(mid)
        assert all(v == 0 for v in after.values()), f"orphans left behind: {after}"

    def test_raw_db_delete_cascades_children(self, jane_id):
        """Pure FK-level check: delete the meetings row directly (no app cascade loop)."""
        mid = f"{P}raw_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()

        async def seed(c):
            await c.execute("INSERT INTO meetings (id, org_id, title, status, created_at) VALUES ($1,$2,$3,$4,$5)",
                            mid, ORG, f"{P}raw", "draft", now)
            await c.execute("INSERT INTO transcripts (id, meeting_id, org_id, text) VALUES ($1,$2,$3,$4)",
                            f"{mid}_t", mid, ORG, "t")
            await c.execute("INSERT INTO analyses (id, meeting_id, org_id, summary) VALUES ($1,$2,$3,$4)",
                            f"{mid}_a", mid, ORG, "s")
            await c.execute("INSERT INTO audio_files (id, meeting_id, org_id, storage_path) VALUES ($1,$2,$3,$4)",
                            f"{mid}_f", mid, ORG, "p")
            await c.execute("INSERT INTO review_edits (id, meeting_id, org_id, action) VALUES ($1,$2,$3,$4)",
                            f"{mid}_re", mid, ORG, "x")
            await c.execute("INSERT INTO reviewer_comments (id, meeting_id, org_id, text) VALUES ($1,$2,$3,$4)",
                            f"{mid}_rc", mid, ORG, "x")
            await c.execute("INSERT INTO audit_logs (id, meeting_id, org_id, action) VALUES ($1,$2,$3,$4)",
                            f"{mid}_al", mid, ORG, "x")
            await c.execute("INSERT INTO meeting_prep (id, meeting_id, org_id) VALUES ($1,$2,$3)",
                            f"{mid}_mp", mid, ORG)
        db(seed)
        assert all(v >= 1 for v in child_counts(mid).values())
        db(lambda c: c.execute("DELETE FROM meetings WHERE id=$1", mid))
        assert child_counts(mid) == {t: 0 for t in CHILD_TABLES}


# ── 4. ORG STRUCTURE ──────────────────────────────────────────────────────────
class TestOrgStructure:
    def test_setting_team_staff_delete_flow(self, admin_s):
        mgr_id, _ = make_temp_user(admin_s, "branchmgr", "manager")
        sup_id, _ = make_temp_user(admin_s, "supervisor", "manager")
        staff_id, _ = make_temp_user(admin_s, "staff", "attendee")
        setting_id = team_id = None
        try:
            r = admin_s.post(f"{BASE}/org/settings",
                             json={"name": f"{P}branch", "manager_user_id": mgr_id}, timeout=90)
            assert r.status_code == 200, f"create setting {r.status_code}: {r.text[:300]}"
            setting_id = r.json()["id"]

            r = admin_s.post(f"{BASE}/org/settings/{setting_id}/teams",
                             json={"name": f"{P}team", "supervisor_user_id": sup_id}, timeout=90)
            assert r.status_code == 200, f"create team {r.status_code}: {r.text[:300]}"
            team_id = r.json()["id"]

            r = admin_s.post(f"{BASE}/org/teams/{team_id}/members",
                             json={"user_id": staff_id}, timeout=90)
            assert r.status_code == 200, f"add member {r.status_code}: {r.text[:300]}"
            assert db(lambda c: c.fetchval("SELECT team_id FROM users WHERE id=$1", staff_id)) == team_id

            # delete team → staff + supervisor team_id NULL, no error
            r = admin_s.delete(f"{BASE}/org/teams/{team_id}", timeout=90)
            assert r.status_code == 200, f"delete team {r.status_code}: {r.text[:300]}"
            assert db(lambda c: c.fetchval("SELECT count(*) FROM teams WHERE id=$1", team_id)) == 0
            for uid in (staff_id, sup_id):
                assert db(lambda c: c.fetchval("SELECT team_id FROM users WHERE id=$1", uid)) is None
            team_id = None

            # delete setting → users' setting_id NULL
            r = admin_s.delete(f"{BASE}/org/settings/{setting_id}", timeout=90)
            assert r.status_code == 200, f"delete setting {r.status_code}: {r.text[:300]}"
            assert db(lambda c: c.fetchval("SELECT count(*) FROM org_settings WHERE id=$1", setting_id)) == 0
            for uid in (mgr_id, sup_id, staff_id):
                assert db(lambda c: c.fetchval("SELECT setting_id FROM users WHERE id=$1", uid)) is None
            setting_id = None
        finally:
            if team_id:
                admin_s.delete(f"{BASE}/org/teams/{team_id}", timeout=90)
            if setting_id:
                admin_s.delete(f"{BASE}/org/settings/{setting_id}", timeout=90)
            for uid in (mgr_id, sup_id, staff_id):
                hard_delete_user(uid)

    def test_delete_setting_with_live_team_and_meetings(self, admin_s, jane_id):
        """A setting still holding a team + a meeting referencing it must delete cleanly
        (teams CASCADE-ish via app delete, meetings.setting_id SET NULL)."""
        setting_id = None
        mid = None
        try:
            r = admin_s.post(f"{BASE}/org/settings", json={"name": f"{P}branch2"}, timeout=90)
            assert r.status_code == 200, r.text[:300]
            setting_id = r.json()["id"]
            r = admin_s.post(f"{BASE}/org/settings/{setting_id}/teams",
                             json={"name": f"{P}team2"}, timeout=90)
            assert r.status_code == 200, r.text[:300]
            team_id = r.json()["id"]

            mid = f"{P}setmeet_{uuid.uuid4().hex[:8]}"
            db(lambda c: c.execute(
                "INSERT INTO meetings (id, org_id, title, status, team_id, setting_id) VALUES ($1,$2,$3,$4,$5,$6)",
                mid, ORG, f"{P}setmeet", "draft", team_id, setting_id))

            r = admin_s.delete(f"{BASE}/org/settings/{setting_id}", timeout=90)
            assert r.status_code == 200, f"delete setting {r.status_code}: {r.text[:300]}"

            row = db(lambda c: c.fetchrow("SELECT team_id, setting_id FROM meetings WHERE id=$1", mid))
            assert row is not None, "meeting was deleted by setting delete (over-cascade!)"
            assert row["team_id"] is None and row["setting_id"] is None, dict(row)
            setting_id = None
        finally:
            if mid:
                db(lambda c: c.execute("DELETE FROM meetings WHERE id=$1", mid))
            if setting_id:
                admin_s.delete(f"{BASE}/org/settings/{setting_id}", timeout=90)


# ── 5. USER DELETION WITH REFERENCES ──────────────────────────────────────────
class TestUserDeletion:
    def test_delete_user_referenced_as_supervisor_manager_and_schedule_staff(self, admin_s):
        uid, _ = make_temp_user(admin_s, "multiref", "manager")
        setting_id = team_id = sched_id = mt_id = None
        try:
            r = admin_s.post(f"{BASE}/org/settings",
                             json={"name": f"{P}branch3", "manager_user_id": uid}, timeout=90)
            assert r.status_code == 200, r.text[:300]
            setting_id = r.json()["id"]
            r = admin_s.post(f"{BASE}/org/settings/{setting_id}/teams",
                             json={"name": f"{P}team3", "supervisor_user_id": uid}, timeout=90)
            assert r.status_code == 200, r.text[:300]
            team_id = r.json()["id"]

            r = admin_s.post(f"{BASE}/schedules/meeting-types",
                             json={"name": f"{P}mt3", "default_frequency": "monthly"}, timeout=90)
            assert r.status_code == 200, r.text[:300]
            mt_id = r.json()["id"]
            r = admin_s.post(f"{BASE}/schedules/", json={
                "staff_user_id": uid, "meeting_type_id": mt_id,
                "frequency": "monthly", "start_date": "2026-07-01"}, timeout=90)
            assert r.status_code == 200, f"create schedule {r.status_code}: {r.text[:300]}"
            sched_id = r.json()["id"]

            r = admin_s.delete(f"{BASE}/admin/users/{uid}", timeout=90)
            assert r.status_code == 200, f"delete user {r.status_code}: {r.text[:300]}"
            assert db(lambda c: c.fetchval("SELECT count(*) FROM users WHERE id=$1", uid)) == 0, \
                "pending-invite user should be hard deleted"

            assert db(lambda c: c.fetchval("SELECT supervisor_user_id FROM teams WHERE id=$1", team_id)) is None
            assert db(lambda c: c.fetchval("SELECT manager_user_id FROM org_settings WHERE id=$1", setting_id)) is None
            row = db(lambda c: c.fetchrow("SELECT staff_user_id FROM schedules WHERE id=$1", sched_id))
            assert row is not None, "schedule was deleted with the user (over-cascade!)"
            assert row["staff_user_id"] is None, dict(row)
        finally:
            if sched_id:
                db(lambda c: c.execute("DELETE FROM schedules WHERE id=$1", sched_id))
            if mt_id:
                db(lambda c: c.execute("DELETE FROM meeting_types WHERE id=$1", mt_id))
            if team_id:
                db(lambda c: c.execute("DELETE FROM teams WHERE id=$1", team_id))
            if setting_id:
                db(lambda c: c.execute("DELETE FROM org_settings WHERE id=$1", setting_id))
            hard_delete_user(uid)

    def test_deactivate_active_user_still_works(self, admin_s):
        """Active (non pending-invite) users are soft-deactivated, not deleted."""
        uid, _ = make_temp_user(admin_s, "active")
        try:
            db(lambda c: c.execute("UPDATE users SET must_change_password=FALSE WHERE id=$1", uid))
            r = admin_s.delete(f"{BASE}/admin/users/{uid}", timeout=90)
            assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
            row = db(lambda c: c.fetchrow("SELECT is_active FROM users WHERE id=$1", uid))
            assert row is not None and row["is_active"] is False
        finally:
            hard_delete_user(uid)


# ── 6. SCHEDULE ↔ MEETING TYPE ────────────────────────────────────────────────
class TestScheduleMeetingType:
    def test_meeting_type_delete_leaves_schedule_with_null_type(self, admin_s, jane_id):
        mt_id = sched_id = None
        try:
            r = admin_s.post(f"{BASE}/schedules/meeting-types",
                             json={"name": f"{P}mt_{uuid.uuid4().hex[:5]}", "default_frequency": "weekly"}, timeout=90)
            assert r.status_code == 200, r.text[:300]
            mt_id = r.json()["id"]
            r = admin_s.post(f"{BASE}/schedules/", json={
                "staff_user_id": jane_id, "meeting_type_id": mt_id,
                "frequency": "weekly", "start_date": "2026-07-01"}, timeout=90)
            assert r.status_code == 200, f"create schedule {r.status_code}: {r.text[:300]}"
            sched_id = r.json()["id"]

            # API delete is a soft delete → schedule keeps its reference
            r = admin_s.delete(f"{BASE}/schedules/meeting-types/{mt_id}", timeout=90)
            assert r.status_code == 200, r.text[:300]
            assert db(lambda c: c.fetchval("SELECT meeting_type_id FROM schedules WHERE id=$1", sched_id)) == mt_id

            # hard delete exercises the new SET NULL constraint
            db(lambda c: c.execute("DELETE FROM meeting_types WHERE id=$1", mt_id))
            row = db(lambda c: c.fetchrow("SELECT id, meeting_type_id FROM schedules WHERE id=$1", sched_id))
            assert row is not None, "schedule deleted with meeting_type (over-cascade!)"
            assert row["meeting_type_id"] is None, dict(row)
            mt_id = None

            # schedules list endpoint must not 500 on the now-null type
            r = admin_s.get(f"{BASE}/schedules/", timeout=90)
            assert r.status_code == 200, f"list schedules {r.status_code}: {r.text[:300]}"
        finally:
            if sched_id:
                db(lambda c: c.execute("DELETE FROM schedules WHERE id=$1", sched_id))
            if mt_id:
                db(lambda c: c.execute("DELETE FROM meeting_types WHERE id=$1", mt_id))


# ── 7. CRUD SMOKE ACROSS ROLES ────────────────────────────────────────────────
READ_ENDPOINTS = [
    "/meetings/",
    "/dashboard/",
    "/schedules/meeting-types",
    "/prep/focus-topics",
]
ADMIN_READ_ENDPOINTS = [
    "/org/structure",
    "/admin/users",
    "/admin/standards",
    "/admin/standards/documents",
    "/admin/people-stats",
    "/admin/team-insights",
    "/admin/stats",
    "/schedules/",
    "/schedules/due",
]


class TestSmoke:
    @pytest.mark.parametrize("path", READ_ENDPOINTS)
    def test_common_reads(self, admin_s, manager_s, jane_s, path):
        for name, s in (("admin", admin_s), ("manager", manager_s), ("attendee", jane_s)):
            r = s.get(f"{BASE}{path}", timeout=120)
            assert r.status_code in (200, 403), f"{name} {path} → {r.status_code}: {r.text[:200]}"
            assert r.status_code != 500

    @pytest.mark.parametrize("path", ADMIN_READ_ENDPOINTS)
    def test_admin_manager_reads(self, admin_s, manager_s, path):
        for name, s in (("admin", admin_s), ("manager", manager_s)):
            r = s.get(f"{BASE}{path}", timeout=120)
            assert r.status_code == 200, f"{name} {path} → {r.status_code}: {r.text[:250]}"

    def test_meeting_detail_and_report_read(self, admin_s):
        r = admin_s.get(f"{BASE}/meetings/", timeout=120)
        assert r.status_code == 200
        items = r.json()
        items = items.get("meetings", items) if isinstance(items, dict) else items
        assert items, "no meetings to read"
        mid = items[0]["id"]
        for path in (f"/meetings/{mid}", f"/review/{mid}"):
            rr = admin_s.get(f"{BASE}{path}", timeout=120)
            assert rr.status_code == 200, f"{path} → {rr.status_code}: {rr.text[:250]}"

    def test_setting_and_team_crud(self, admin_s):
        r = admin_s.post(f"{BASE}/org/settings", json={"name": f"{P}crud"}, timeout=90)
        assert r.status_code == 200, r.text[:300]
        sid = r.json()["id"]
        r = admin_s.put(f"{BASE}/org/settings/{sid}", json={"name": f"{P}crud_renamed"}, timeout=90)
        assert r.status_code == 200, r.text[:300]
        r = admin_s.post(f"{BASE}/org/settings/{sid}/teams", json={"name": f"{P}crudteam"}, timeout=90)
        assert r.status_code == 200, r.text[:300]
        tid = r.json()["id"]
        r = admin_s.put(f"{BASE}/org/teams/{tid}", json={"name": f"{P}crudteam2"}, timeout=90)
        assert r.status_code == 200, r.text[:300]
        r = admin_s.delete(f"{BASE}/org/teams/{tid}", timeout=90)
        assert r.status_code == 200, r.text[:300]
        r = admin_s.delete(f"{BASE}/org/settings/{sid}", timeout=90)
        assert r.status_code == 200, r.text[:300]

    def test_standards_document_upload_and_delete(self, admin_s):
        files = {"file": (f"{P}doc.txt", b"Care standards sample text for FK regression test.", "text/plain")}
        r = admin_s.post(f"{BASE}/admin/standards/upload", files=files,
                         data={"label": f"{P}label"}, timeout=180)
        assert r.status_code == 200, f"upload {r.status_code}: {r.text[:300]}"
        doc_id = r.json().get("id") or r.json().get("document", {}).get("id")
        assert doc_id, r.text[:300]
        assert db(lambda c: c.fetchval("SELECT org_id FROM standards_documents WHERE id=$1", doc_id)) == ORG
        r = admin_s.delete(f"{BASE}/admin/standards/documents/{doc_id}", timeout=120)
        assert r.status_code == 200, f"delete doc {r.status_code}: {r.text[:300]}"

    def test_focus_topic_crud(self, admin_s):
        r = admin_s.post(f"{BASE}/prep/focus-topics", json={"topic": f"{P}topic", "is_current": False}, timeout=90)
        assert r.status_code in (200, 201), f"{r.status_code}: {r.text[:300]}"
        tid = r.json().get("id")
        if tid:
            r = admin_s.delete(f"{BASE}/prep/focus-topics/{tid}", timeout=90)
            assert r.status_code == 200, r.text[:300]


# ── 7b. ORG DELETION BLAST RADIUS (users.org_id / *.org_id CASCADE) ───────────
ORG_SCOPED_TABLES = ["users", "meetings", "transcripts", "analyses", "audio_files",
                     "review_edits", "reviewer_comments", "audit_logs", "org_settings",
                     "teams", "standards_entries", "standards_documents", "invitations",
                     "settings", "meeting_types", "focus_topics", "meeting_prep",
                     "schedules", "supervision_uploads"]


def org_row_counts(org_id):
    async def go(c):
        return {t: await c.fetchval(f"SELECT count(*) FROM {t} WHERE org_id=$1", org_id)
                for t in ORG_SCOPED_TABLES}
    return db(go)


@pytest.fixture(scope="session")
def superadmin_s():
    return login("superadmin@1two.one", "NewPass123!")


class TestOrgDeletionBlastRadius:
    def test_delete_throwaway_org_cascades_only_its_own_rows(self, superadmin_s):
        baseline = org_row_counts(ORG)
        name = f"{P}org_{uuid.uuid4().hex[:6]}"
        r = superadmin_s.post(f"{BASE}/super-admin/orgs", json={"name": name}, timeout=90)
        assert r.status_code == 200, f"create org {r.status_code}: {r.text[:300]}"
        new_org = r.json()["id"]
        now = datetime.now(timezone.utc).isoformat()
        try:
            r = superadmin_s.post(f"{BASE}/super-admin/orgs/{new_org}/users", json={
                "email": f"{P}orguser_{uuid.uuid4().hex[:6]}@example.com",
                "name": f"{P}orguser", "password": "TempPass123!", "role": "manager"}, timeout=90)
            assert r.status_code == 200, f"create org user {r.status_code}: {r.text[:300]}"
            uid = r.json()["id"]

            # seed one row in every org-scoped child table
            async def seed(c):
                sid, tid, mid = f"{new_org}_s", f"{new_org}_t", f"{new_org}_m"
                await c.execute("INSERT INTO org_settings (id, org_id, name, manager_user_id) VALUES ($1,$2,$3,$4)",
                                sid, new_org, f"{P}s", uid)
                await c.execute("INSERT INTO teams (id, org_id, setting_id, name, supervisor_user_id) VALUES ($1,$2,$3,$4,$5)",
                                tid, new_org, sid, f"{P}t", uid)
                await c.execute("UPDATE users SET team_id=$1, setting_id=$2 WHERE id=$3", tid, sid, uid)
                await c.execute("INSERT INTO meetings (id, org_id, title, status, team_id, setting_id, created_at) "
                                "VALUES ($1,$2,$3,$4,$5,$6,$7)", mid, new_org, f"{P}m", "draft", tid, sid, now)
                for tbl, cols in [("transcripts", "(id, meeting_id, org_id, text) VALUES ($1,$2,$3,'x')"),
                                  ("analyses", "(id, meeting_id, org_id, summary) VALUES ($1,$2,$3,'x')"),
                                  ("audio_files", "(id, meeting_id, org_id, storage_path) VALUES ($1,$2,$3,'x')"),
                                  ("review_edits", "(id, meeting_id, org_id, action) VALUES ($1,$2,$3,'x')"),
                                  ("reviewer_comments", "(id, meeting_id, org_id, text) VALUES ($1,$2,$3,'x')"),
                                  ("audit_logs", "(id, meeting_id, org_id, action) VALUES ($1,$2,$3,'x')"),
                                  ("meeting_prep", "(id, meeting_id, org_id) VALUES ($1,$2,$3)")]:
                    await c.execute(f"INSERT INTO {tbl} {cols}", f"{new_org}_{tbl[:3]}", mid, new_org)
                await c.execute("INSERT INTO meeting_types (id, org_id, name) VALUES ($1,$2,$3)",
                                f"{new_org}_mt", new_org, f"{P}mt")
                await c.execute("INSERT INTO schedules (id, org_id, staff_user_id, meeting_type_id, frequency) VALUES ($1,$2,$3,$4,'monthly')",
                                f"{new_org}_sch", new_org, uid, f"{new_org}_mt")
                await c.execute("INSERT INTO focus_topics (id, org_id, text) VALUES ($1,$2,$3)",
                                f"{new_org}_ft", new_org, f"{P}ft")
                await c.execute("INSERT INTO standards_entries (id, org_id, type, reference, name) VALUES ($1,$2,'cqc','R1',$3)",
                                f"{new_org}_se", new_org, f"{P}se")
                await c.execute("INSERT INTO standards_documents (id, org_id, filename) VALUES ($1,$2,$3)",
                                f"{new_org}_sd", new_org, f"{P}sd")
                await c.execute("INSERT INTO supervision_uploads (id, org_id, staff_id) VALUES ($1,$2,$3)",
                                f"{new_org}_su", new_org, uid)
                await c.execute("INSERT INTO settings (id, org_id) VALUES ($1,$2)", f"{new_org}_set", new_org)
            db(seed)

            seeded = org_row_counts(new_org)
            assert all(v >= 1 for k, v in seeded.items() if k != "invitations"), seeded

            r = superadmin_s.delete(f"{BASE}/super-admin/orgs/{new_org}", timeout=180)
            assert r.status_code == 200, f"delete org {r.status_code}: {r.text[:300]}"

            after = org_row_counts(new_org)
            assert all(v == 0 for v in after.values()), f"rows survived org delete: {after}"
            assert db(lambda c: c.fetchval("SELECT count(*) FROM organisations WHERE id=$1", new_org)) == 0

            # nothing from the real org was touched
            assert org_row_counts(ORG) == baseline, "row counts changed in an unrelated org!"
        finally:
            db(lambda c: c.execute("DELETE FROM organisations WHERE id=$1", new_org))


# ── 8. REGRESSION ON EARLIER SESSION FIXES ────────────────────────────────────
@pytest.fixture(scope="module")
def exportable_meetings(jane_id):
    """Seed 2 signed-off meetings with transcript + analysis (exports require both)."""
    ids = [f"{P}exp_{uuid.uuid4().hex[:8]}" for _ in range(2)]
    now = datetime.now(timezone.utc).isoformat()
    attendees = json.dumps([{"user_id": jane_id, "name": "Jane", "role": "attendee", "reviewed": True}])
    mappings = json.dumps([{"regulation_ref": "R9", "regulation_name": "Person-centred care",
                            "confidence": "high", "status": "confirmed",
                            "evidence_summary": "Discussed care planning."}])

    async def seed(c):
        for mid in ids:
            await c.execute(
                "INSERT INTO meetings (id, org_id, title, date, status, attendees, created_at) "
                "VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7)",
                mid, ORG, f"{P}export {mid[-4:]}", now[:10], "signed_off", attendees, now)
            await c.execute(
                "INSERT INTO transcripts (id, meeting_id, org_id, text, created_at) VALUES ($1,$2,$3,$4,$5)",
                f"{mid}_t", mid, ORG, "Speaker A: we discussed the care plan.", now)
            await c.execute(
                "INSERT INTO analyses (id, meeting_id, org_id, summary, cqc_mappings, created_at) "
                "VALUES ($1,$2,$3,$4,$5::jsonb,$6)",
                f"{mid}_a", mid, ORG, "Summary of supervision.", mappings, now)
            await c.execute(
                "UPDATE meetings SET transcript_id=$1, analysis_id=$2 WHERE id=$3",
                f"{mid}_t", f"{mid}_a", mid)
    db(seed)
    yield ids
    db(lambda c: c.execute("DELETE FROM meetings WHERE id = ANY($1::text[])", ids))


class TestRegressionEarlierFixes:
    @pytest.fixture(autouse=True)
    def _reset_export_limit(self):
        clear_limits()
        yield

    def test_export_evidence_multi_meeting_pdf(self, admin_s, exportable_meetings):
        r = admin_s.post(f"{BASE}/admin/export-evidence",
                         json={"format": "pdf", "meeting_ids": exportable_meetings}, timeout=180)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        assert r.content[:4] == b"%PDF", r.content[:40]

    def test_export_transcripts_multi_meeting_pdf(self, admin_s, exportable_meetings):
        r = admin_s.post(f"{BASE}/admin/export-transcripts",
                         json={"meeting_ids": exportable_meetings}, timeout=180)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        assert r.content[:4] == b"%PDF", r.content[:40]

    def test_share_meeting_with_multiple_users(self, admin_s, exportable_meetings):
        mid = exportable_meetings[0]
        rows = db(lambda c: c.fetch(
            "SELECT id FROM users WHERE org_id=$1 AND is_active=TRUE "
            "AND role IN ('manager','admin','shared_reviewer') LIMIT 2", ORG))
        uids = [r["id"] for r in rows]
        before = db(lambda c: c.fetchval("SELECT shared_with FROM meetings WHERE id=$1", mid))
        try:
            r = admin_s.post(f"{BASE}/review/{mid}/share", json={"user_ids": uids}, timeout=120)
            assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
            shared = r.json().get("shared_with", [])
            got = {s.get("user_id") for s in shared if isinstance(s, dict)}
            assert set(uids).issubset(got), f"{uids} not in {got}"
        finally:
            db(lambda c: c.execute("UPDATE meetings SET shared_with=$1::jsonb WHERE id=$2",
                                   before if isinstance(before, str) else json.dumps(before or []), mid))

    def test_org_structure_batched_query(self, admin_s):
        r = admin_s.get(f"{BASE}/org/structure", timeout=120)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        data = r.json()
        settings = data.get("settings", data if isinstance(data, list) else [])
        db_count = db(lambda c: c.fetchval("SELECT count(*) FROM org_settings WHERE org_id=$1", ORG))
        assert len(settings) == db_count, f"API {len(settings)} settings vs DB {db_count}"
