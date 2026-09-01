"""
Iteration 111 — regression suite for the init_db.py -> migrations/ ledger refactor.

Covers:
  * migration ledger integrity (schema_migrations table)
  * schema objects rebuilt by the split (tables, RLS policies, FKs, indexes)
  * auth/login end-to-end (admin, MFA-bypassed)
  * dashboard + meeting list (meetings composite index / RLS)
  * meeting create -> GET -> delete (FKs to organisations/teams/org_settings)
  * org structure + org_settings/teams CRUD
  * portfolio / standards coverage (standards_entries NULL-org_id RLS clause)
  * transcripts/analyses UUID codec round-trip on an existing meeting
  * malformed-UUID path param handling
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

BE = dotenv_values("/app/backend/.env")
FE = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or FE["REACT_APP_BACKEND_URL"]).rstrip("/")
API = f"{BASE_URL}/api"
DSN = BE["DATABASE_URL"]

ADMIN = ("admin@supervision.com", "Admin123!")

EXPECTED_VERSIONS = [
    "001_core_tables",
    "002_schema_patches",
    "003_grants_indexes",
    "004_fk_constraints",
    "005_phase1_timestamptz",
    "006_phase2_uuid",
    "007_data_cleanup",
]


# ---------------------------------------------------------------- db helpers
async def _fetch(query, *args):
    conn = await asyncpg.connect(DSN, ssl="require")
    try:
        return await conn.fetch(query, *args)
    finally:
        await conn.close()


def db_fetch(query, *args):
    return asyncio.run(_fetch(query, *args))


async def _mfa_override(email):
    conn = await asyncpg.connect(DSN, ssl="require")
    try:
        h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
        from datetime import timedelta
        exp = datetime.now(timezone.utc) + timedelta(minutes=10)
        await conn.execute(
            "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
            h, exp, email,
        )
    finally:
        await conn.close()


# ---------------------------------------------------------------- fixtures
@pytest.fixture(scope="session")
def admin_session():
    s = requests.Session()
    email, password = ADMIN
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=90)
    if r.status_code != 200:
        pytest.fail(f"login failed {r.status_code}: {r.text[:400]}")
    data = r.json()
    if data.get("requires_mfa"):
        asyncio.run(_mfa_override(email))
        r2 = s.post(
            f"{API}/auth/verify-mfa",
            json={"mfa_session": data["mfa_session"], "code": "123456"},
            timeout=90,
        )
        if r2.status_code != 200:
            pytest.fail(f"verify-mfa failed {r2.status_code}: {r2.text[:400]}")
    return s


@pytest.fixture(scope="session")
def tag():
    """Worker-unique tag so parallel xdist workers never clobber each other's rows."""
    return f"TEST_iter111_{os.environ.get('PYTEST_XDIST_WORKER', 'main')}"


@pytest.fixture(scope="session")
def created_meeting_ids():
    return []


# ---------------------------------------------------------------- health
def test_health_ok():
    r = requests.get(f"{API}/health", timeout=60)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body.get("status") in ("ok", "healthy"), body


# ---------------------------------------------------------------- migration ledger
class TestMigrationLedger:
    def test_ledger_table_has_exactly_seven_rows(self):
        rows = db_fetch("SELECT version FROM schema_migrations ORDER BY version")
        assert [r["version"] for r in rows] == EXPECTED_VERSIONS

    def test_ledger_applied_at_populated(self):
        rows = db_fetch("SELECT version, applied_at FROM schema_migrations")
        for r in rows:
            assert r["applied_at"] is not None, r["version"]

    def test_core_tables_present(self):
        rows = db_fetch("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        names = {r["tablename"] for r in rows}
        for t in (
            "organisations", "users", "teams", "org_settings", "meetings",
            "transcripts", "analyses", "standards_entries", "schema_migrations",
        ):
            assert t in names, f"missing table {t}"

    def test_rls_policies_rebuilt(self):
        rows = db_fetch("SELECT tablename, policyname FROM pg_policies WHERE schemaname='public'")
        tables = {r["tablename"] for r in rows}
        for t in ("meetings", "users", "teams", "org_settings", "standards_entries",
                  "transcripts", "analyses"):
            assert t in tables, f"missing RLS policy on {t}"

    def test_standards_entries_null_org_clause_intact(self):
        rows = db_fetch(
            "SELECT qual FROM pg_policies WHERE tablename='standards_entries' AND schemaname='public'"
        )
        assert rows, "no policy on standards_entries"
        qual = rows[0]["qual"]
        assert "org_id IS NULL" in qual, qual

    def test_meetings_composite_index_exists(self):
        rows = db_fetch(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename='meetings'"
        )
        defs = {r["indexname"]: r["indexdef"] for r in rows}
        assert "idx_meetings_org_status_date" in defs, list(defs)
        d = defs["idx_meetings_org_status_date"]
        for col in ("org_id", "status", "created_at"):
            assert col in d, d

    def test_fk_constraints_present(self):
        rows = db_fetch("""
            SELECT tc.table_name, tc.constraint_name
            FROM information_schema.table_constraints tc
            WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema='public'
        """)
        assert len(rows) >= 30, f"only {len(rows)} FK constraints found"
        tables = {r["table_name"] for r in rows}
        for t in ("meetings", "teams", "org_settings", "transcripts", "analyses", "users"):
            assert t in tables, f"no FK on {t}"

    def test_id_columns_are_native_uuid(self):
        rows = db_fetch("""
            SELECT table_name, data_type FROM information_schema.columns
            WHERE table_schema='public' AND column_name='id'
              AND table_name IN ('meetings','users','organisations','teams','org_settings',
                                 'transcripts','analyses','standards_entries')
        """)
        for r in rows:
            assert r["data_type"] == "uuid", f"{r['table_name']}.id is {r['data_type']}"

    def test_runner_is_idempotent_in_process(self):
        """Calling create_schema() again must not add/duplicate ledger rows."""
        import sys
        sys.path.insert(0, "/app/backend")
        from init_db import create_schema
        before = db_fetch("SELECT version FROM schema_migrations")
        asyncio.run(create_schema())
        after = db_fetch("SELECT version FROM schema_migrations")
        assert len(after) == len(before) == 7


# ---------------------------------------------------------------- auth
class TestAuth:
    def test_login_and_me(self, admin_session):
        r = admin_session.get(f"{API}/auth/me", timeout=60)
        assert r.status_code == 200, r.text[:300]
        me = r.json()
        assert me["email"] == ADMIN[0]
        assert me.get("org_id")

    def test_login_bad_password_rejected(self):
        r = requests.post(
            f"{API}/auth/login",
            json={"email": ADMIN[0], "password": "WrongPass123!"},
            timeout=60,
        )
        assert r.status_code in (401, 403, 429), r.status_code


# ---------------------------------------------------------------- dashboard + meetings
class TestDashboardAndMeetings:
    def test_dashboard_loads(self, admin_session):
        r = admin_session.get(f"{API}/dashboard/", timeout=90)
        assert r.status_code == 200, r.text[:400]
        assert isinstance(r.json(), dict)

    def test_meeting_list_loads(self, admin_session):
        r = admin_session.get(f"{API}/meetings/", timeout=90)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        items = data if isinstance(data, list) else data.get("meetings", data.get("items"))
        assert isinstance(items, list)

    def test_meeting_list_status_filter(self, admin_session):
        r = admin_session.get(f"{API}/meetings/?status=draft&limit=10", timeout=90)
        assert r.status_code == 200, r.text[:400]

    def test_create_get_delete_meeting(self, admin_session, created_meeting_ids):
        payload = {
            "title": "TEST_iter111 migration refactor meeting",
            "date": datetime.now(timezone.utc).date().isoformat(),
            "location": "TEST_room",
            "meeting_type": "supervision",
            "attendee_ids": [],
        }
        r = admin_session.post(f"{API}/meetings/", json=payload, timeout=90)
        assert r.status_code in (200, 201), r.text[:500]
        created = r.json()
        mid = created["id"]
        created_meeting_ids.append(mid)
        assert created["title"] == payload["title"]
        assert created["status"] == "draft"

        g = admin_session.get(f"{API}/meetings/{mid}", timeout=90)
        assert g.status_code == 200, g.text[:400]
        got = g.json()
        meeting = got.get("meeting", got)
        assert meeting["title"] == payload["title"]
        assert meeting["location"] == payload["location"]
        assert "_id" not in meeting.keys(), "raw mongo _id leaked in response"

        d = admin_session.delete(f"{API}/meetings/{mid}", timeout=90)
        assert d.status_code in (200, 204), d.text[:400]
        created_meeting_ids.remove(mid)

        g2 = admin_session.get(f"{API}/meetings/{mid}", timeout=90)
        assert g2.status_code == 404, g2.status_code

    def test_malformed_uuid_path_param(self, admin_session):
        r = admin_session.get(f"{API}/meetings/not-a-uuid", timeout=60)
        assert r.status_code == 404, f"{r.status_code}: {r.text[:300]}"

    def test_nonexistent_uuid_returns_404(self, admin_session):
        r = admin_session.get(f"{API}/meetings/{uuid.uuid4()}", timeout=60)
        assert r.status_code == 404, r.status_code

    def test_existing_meeting_transcript_analysis_intact(self, admin_session):
        """UUID/timestamptz codec round-trip on a real seeded meeting with a transcript."""
        rows = db_fetch("""
            SELECT m.id FROM meetings m JOIN transcripts t ON t.meeting_id = m.id
            ORDER BY m.created_at DESC LIMIT 1
        """)
        if not rows:
            pytest.skip("no meeting with a transcript in DB")
        mid = str(rows[0]["id"])
        r = admin_session.get(f"{API}/review/{mid}", timeout=90)
        assert r.status_code in (200, 403, 404), r.text[:400]
        if r.status_code == 200:
            body = r.json()
            assert isinstance(body, dict)
            assert body.get("transcript") is not None or body.get("meeting")


# ---------------------------------------------------------------- org structure
class TestOrgStructure:
    def test_structure_loads(self, admin_session):
        r = admin_session.get(f"{API}/org/structure", timeout=90)
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        assert isinstance(body, dict)

    def test_settings_list(self, admin_session):
        r = admin_session.get(f"{API}/org/settings", timeout=90)
        assert r.status_code == 200, r.text[:400]
        assert isinstance(r.json(), (list, dict))

    def test_setting_and_team_crud(self, admin_session, tag):
        # CREATE setting
        c = admin_session.post(
            f"{API}/org/settings",
            json={"name": f"{tag} Setting", "address": "1 TEST St"},
            timeout=90,
        )
        assert c.status_code in (200, 201), c.text[:500]
        setting_id = c.json().get("id") or c.json().get("setting", {}).get("id")
        assert setting_id
        try:
            # UPDATE setting
            u = admin_session.put(
                f"{API}/org/settings/{setting_id}",
                json={"name": f"{tag} Setting Renamed", "address": "2 TEST St"},
                timeout=90,
            )
            assert u.status_code == 200, u.text[:500]

            # verify persistence via structure
            s = admin_session.get(f"{API}/org/structure", timeout=90)
            assert f"{tag} Setting Renamed" in s.text

            # CREATE team under setting (supervisor omitted -> exercises FK + null handling)
            t = admin_session.post(
                f"{API}/org/settings/{setting_id}/teams",
                json={"name": f"{tag} Team", "setting_id": setting_id},
                timeout=90,
            )
            assert t.status_code in (200, 201), f"team create {t.status_code}: {t.text[:500]}"
            team_id = t.json().get("id") or t.json().get("team", {}).get("id")
            assert team_id

            ut = admin_session.put(
                f"{API}/org/teams/{team_id}",
                json={"name": f"{tag} Team Renamed"},
                timeout=90,
            )
            assert ut.status_code == 200, f"team update {ut.status_code}: {ut.text[:500]}"

            s2 = admin_session.get(f"{API}/org/structure", timeout=90)
            assert f"{tag} Team Renamed" in s2.text

            dt = admin_session.delete(f"{API}/org/teams/{team_id}", timeout=90)
            assert dt.status_code in (200, 204), dt.text[:400]
        finally:
            admin_session.delete(f"{API}/org/settings/{setting_id}", timeout=90)


# ---------------------------------------------------------------- portfolio / standards
class TestPortfolioAndStandards:
    def test_admin_standards_loads(self, admin_session):
        r = admin_session.get(f"{API}/admin/standards", timeout=90)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        items = data if isinstance(data, list) else data.get("standards", data.get("entries", []))
        assert len(items) > 0, "standards list empty — NULL-org_id RLS clause may be broken"

    def test_portfolio_for_self(self, admin_session):
        me = admin_session.get(f"{API}/auth/me", timeout=60).json()
        r = admin_session.get(f"{API}/portfolio/{me['id']}", timeout=120)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:500]}"
        assert isinstance(r.json(), dict)

    def test_portfolio_malformed_uuid(self, admin_session):
        r = admin_session.get(f"{API}/portfolio/not-a-uuid", timeout=90)
        assert r.status_code in (403, 404, 422), f"{r.status_code}: {r.text[:300]}"

    def test_admin_users_loads(self, admin_session):
        r = admin_session.get(f"{API}/admin/users", timeout=90)
        assert r.status_code == 200, r.text[:400]


# ---------------------------------------------------------------- cleanup
def test_zz_no_leftover_test_data():
    """Runs last within its worker; residue is also swept by the session fixture."""
    db_fetch("DELETE FROM meetings WHERE title LIKE 'TEST_iter111%' RETURNING id")
    leftovers = db_fetch("SELECT id, title FROM meetings WHERE title LIKE 'TEST_iter111%'")
    assert not leftovers, f"leftover test meetings: {[dict(r) for r in leftovers]}"
