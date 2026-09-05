"""
Regression tests for iteration 124 — date/uuid column type migrations (m016–m019).

Covers:
  - DB-level: 4 migrations recorded, column types match, FK exists,
    zero data loss on meetings.date, evidence_feedback.evidence_item_id UNCHANGED (text).
  - meetings write/read: datetime-local ('YYYY-MM-DDTHH:MM') AND date-only ('YYYY-MM-DD')
    round-trip through the new TIMESTAMP column.
  - schedules write/read: POST + PUT with start_date, new DATE codec exercised.
  - doc-uploads write/read: POST with meeting_date, DATE codec write path.
  - team-insights date filters return 200 with the new TIMESTAMP column.
  - meeting_type_id column typed uuid, GET returns null cleanly.
"""
import os
import io
import uuid
import asyncio
import requests
import pytest
import asyncpg

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
DB_URL = os.environ["DATABASE_URL"]

ADMIN = ("admin@supervision.com", "Admin123!")
ORG_ID = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"


# ---------------- Fixtures ----------------

@pytest.fixture(scope="session")
def admin_session():
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    body = r.json()
    if body.get("mfa_required"):
        # bypass MFA using db override — set mfa_code to bcrypt("123456") via helper if present
        pytest.skip("MFA required for admin — pre-seed via helper if needed")
    return s


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def db(event_loop):
    conn = event_loop.run_until_complete(asyncpg.connect(DB_URL))
    yield conn, event_loop
    event_loop.run_until_complete(conn.close())


def _q(db, sql, *args):
    conn, loop = db
    return loop.run_until_complete(conn.fetch(sql, *args))


# ---------------- DB-level schema checks ----------------

class TestSchemaMigrations:
    def test_migrations_recorded(self, db):
        rows = _q(db, "SELECT version FROM schema_migrations WHERE version IN ($1,$2,$3,$4)",
                  "016_focus_topics_created_at", "017_meeting_type_id_uuid",
                  "018_date_columns_phase2", "019_meetings_date_timestamp")
        versions = {r["version"] for r in rows}
        assert versions == {
            "016_focus_topics_created_at", "017_meeting_type_id_uuid",
            "018_date_columns_phase2", "019_meetings_date_timestamp",
        }, f"missing migrations, got: {versions}"

    def test_column_types(self, db):
        rows = _q(db, """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE (table_name, column_name) IN (
                ('meetings','date'),
                ('schedules','start_date'),
                ('supervision_uploads','meeting_date'),
                ('focus_topics','created_at'),
                ('meetings','meeting_type_id'),
                ('evidence_feedback','evidence_item_id')
            )
        """)
        by_key = {(r["table_name"], r["column_name"]): r["data_type"] for r in rows}
        assert by_key[("meetings", "date")] == "timestamp without time zone"
        assert by_key[("schedules", "start_date")] == "date"
        assert by_key[("supervision_uploads", "meeting_date")] == "date"
        assert by_key[("focus_topics", "created_at")] == "timestamp with time zone"
        assert by_key[("meetings", "meeting_type_id")] == "uuid"
        # UNCHANGED — critical
        assert by_key[("evidence_feedback", "evidence_item_id")] == "text"

    def test_fk_meetings_meeting_type_id(self, db):
        rows = _q(db, """
            SELECT tc.constraint_name, rc.delete_rule
            FROM information_schema.table_constraints tc
            JOIN information_schema.referential_constraints rc
              ON tc.constraint_name = rc.constraint_name
            WHERE tc.table_name='meetings' AND tc.constraint_name='fk_meetings_meeting_type_id'
        """)
        assert len(rows) == 1, "fk_meetings_meeting_type_id missing"
        assert rows[0]["delete_rule"] == "SET NULL"

    def test_meetings_date_no_data_loss(self, db):
        rows = _q(db, "SELECT COUNT(*) AS c, COUNT(date) AS nn FROM meetings")
        assert rows[0]["c"] == rows[0]["nn"], "some meetings.date are NULL post-migration"
        assert rows[0]["c"] >= 18, f"expected >=18 pre-existing meetings, got {rows[0]['c']}"


# ---------------- Meetings write/read (TIMESTAMP codec) ----------------

class TestMeetingsDateRoundtrip:
    _created = []

    @classmethod
    def teardown_class(cls):
        # cleanup — best effort using a fresh session
        s = requests.Session()
        s.post(f"{BASE}/api/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]})
        for mid in cls._created:
            try:
                s.delete(f"{BASE}/api/meetings/{mid}")
            except Exception:
                pass

    def _create(self, sess, date_str):
        payload = {"title": f"TEST_iter124 {uuid.uuid4().hex[:6]}", "date": date_str,
                   "location": "TEST", "meeting_type": "supervision"}
        r = sess.post(f"{BASE}/api/meetings/", json=payload)
        assert r.status_code in (200, 201), f"{r.status_code}: {r.text}"
        mid = r.json()["id"]
        type(self)._created.append(mid)
        return mid

    def test_datetime_local_string(self, admin_session):
        mid = self._create(admin_session, "2026-09-10T14:30")
        r = admin_session.get(f"{BASE}/api/meetings/{mid}")
        assert r.status_code == 200
        date_val = r.json()["date"]
        assert date_val == "2026-09-10T14:30:00", f"got: {date_val!r}"
        # meeting_type_id should be null and not crash
        assert r.json().get("meeting_type_id") is None

    def test_date_only_string(self, admin_session):
        mid = self._create(admin_session, "2026-09-15")
        r = admin_session.get(f"{BASE}/api/meetings/{mid}")
        assert r.status_code == 200
        date_val = r.json()["date"]
        # Depending on codec, may be '2026-09-15' or '2026-09-15T00:00:00'
        assert date_val.startswith("2026-09-15"), f"got: {date_val!r}"

    def test_datetime_with_seconds(self, admin_session):
        mid = self._create(admin_session, "2026-10-01T09:15:30")
        r = admin_session.get(f"{BASE}/api/meetings/{mid}")
        assert r.status_code == 200
        assert r.json()["date"].startswith("2026-10-01T09:15:30"), r.json()["date"]


# ---------------- Schedules write/read (DATE codec) ----------------

class TestSchedulesDate:
    _created = []

    @classmethod
    def teardown_class(cls):
        s = requests.Session()
        s.post(f"{BASE}/api/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]})
        for sid in cls._created:
            try:
                s.delete(f"{BASE}/api/schedules/{sid}")
            except Exception:
                pass

    def test_list_schedules_ok(self, admin_session):
        r = admin_session.get(f"{BASE}/api/schedules/")
        assert r.status_code == 200
        for sch in r.json():
            # start_date should be a plain YYYY-MM-DD string (codec decodes to text)
            assert isinstance(sch["start_date"], str), f"start_date not str: {type(sch['start_date'])}"
            assert len(sch["start_date"]) == 10 and sch["start_date"][4] == "-", sch["start_date"]

    def test_create_and_update_schedule(self, admin_session):
        # Need a staff user id — find any user in the org
        r = admin_session.get(f"{BASE}/api/admin/users")
        if r.status_code != 200:
            pytest.skip("cannot list users")
        users = r.json()
        staff = next((u for u in users if u.get("role") in ("attendee", "manager")), None)
        assert staff, "no staff user found"

        # need a meeting_type_id — fetch existing ones
        r = admin_session.get(f"{BASE}/api/schedules/meeting-types")
        assert r.status_code == 200, r.text
        mts = r.json()
        assert mts, "no meeting_types seeded"
        mt_id = mts[0]["id"]

        payload = {
            "staff_user_id": staff["id"],
            "meeting_type_id": mt_id,
            "frequency": "monthly",
            "start_date": "2026-11-01",
        }
        r = admin_session.post(f"{BASE}/api/schedules/", json=payload)
        assert r.status_code in (200, 201), f"{r.status_code}: {r.text}"
        sid = r.json()["id"]
        type(self)._created.append(sid)
        assert r.json()["start_date"] == "2026-11-01"

        # Update
        r = admin_session.put(f"{BASE}/api/schedules/{sid}", json={
            "frequency": "quarterly", "start_date": "2026-12-15",
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text}"

        # Verify persistence via list
        r = admin_session.get(f"{BASE}/api/schedules/")
        assert r.status_code == 200
        found = next((x for x in r.json() if x["id"] == sid), None)
        assert found and found["start_date"] == "2026-12-15", found


# ---------------- Doc uploads DATE codec write path ----------------

class TestDocUploadMeetingDate:
    def test_upload_with_meeting_date(self, admin_session):
        # find a staff user first
        r = admin_session.get(f"{BASE}/api/admin/users")
        assert r.status_code == 200
        staff = next((u for u in r.json() if u.get("role") in ("attendee", "manager")), None)
        assert staff
        # minimal PDF header
        content = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"
        files = {"file": ("iter124.pdf", io.BytesIO(content), "application/pdf")}
        data = {"staff_id": staff["id"],
                "label": f"TEST_iter124_{uuid.uuid4().hex[:6]}",
                "doc_type": "policy", "meeting_date": "2026-08-20"}
        r = admin_session.post(f"{BASE}/api/doc-uploads/", files=files, data=data)
        assert r.status_code in (200, 201), f"{r.status_code}: {r.text}"
        upload_id = r.json()["id"]
        try:
            r = admin_session.get(f"{BASE}/api/doc-uploads/{upload_id}")
            assert r.status_code == 200
            md = r.json()["meeting_date"]
            assert md == "2026-08-20", f"got: {md!r}"
        finally:
            admin_session.delete(f"{BASE}/api/doc-uploads/{upload_id}")


# ---------------- Team insights date filters ----------------

class TestTeamInsightsDateFilter:
    def test_team_insights_filters_ok(self, admin_session):
        r = admin_session.get(f"{BASE}/api/admin/team-insights",
                              params={"date_from": "2025-01-01", "date_to": "2027-12-31"})
        assert r.status_code == 200, f"{r.status_code}: {r.text}"

    def test_action_stats_filter_ok(self, admin_session):
        r = admin_session.get(f"{BASE}/api/admin/team-insights/action-stats",
                              params={"date_from": "2025-01-01", "date_to": "2027-12-31"})
        assert r.status_code == 200, f"{r.status_code}: {r.text}"
