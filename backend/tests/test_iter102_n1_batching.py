"""Iteration 102 — regression suite for the N+1 query-batching rewrite.

Covers the 6 rewritten functions:
  super_admin.list_orgs, admin.export_evidence, admin.export_cqc_excerpts,
  admin.export_cc_excerpts, admin.export_transcripts,
  dashboard.fetch_structure, review.share_meeting

Run with:  cd /app/backend && python3 -m pytest tests/test_iter102_n1_batching.py -n 0 -q
(-n 0 is mandatory: parallel workers race on the shared-account MFA override.)

Seed fixtures come from tests/_iter102_seed.py (run `seed` before, `cleanup` after).
"""
import asyncio
import csv
import io
import json
import os
import re
from datetime import datetime, timedelta, timezone

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values
from pypdf import PdfReader

BE = dotenv_values("/app/backend/.env")
FE = dotenv_values("/app/frontend/.env")
BASE = FE["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = BE["DATABASE_URL"]

ORG = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"
SETTING_ONE = "70591fed-9a98-4d09-a16a-b911735c63e4"
SETTING_TWO = "f93046b6-8211-48ce-b89a-c09f399efa8d"
P = "TEST_iter102_"
M1, M2, M3, M4 = [f"{P}m{i}" for i in (1, 2, 3, 4)]
TEAM_A, TEAM_B = f"{P}teamA", f"{P}teamB"
REVIEWER_ID = f"{P}reviewer"
MARIA_ID = "f742ddf2-bfb5-44e5-8cd8-14eebb2d0cc4"
DIANE_ID = "2412f428-8452-42ad-9905-d0cf9341ac30"
JANE_ID = "724367a3-1ca9-498b-890b-0516b2f122f5"
MANAGER_ID = "465c5101-bbc8-4f26-adaa-c906d3324dd5"
SARAH_ID = "53874ad3-8a98-4fab-8993-7c1b2d57a5b0"
ADMIN_ID = "f72ac550-e6b8-4ffc-b2da-46a54a4c06d5"


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
    """Password login + DB MFA bypass. Returns an authenticated requests.Session."""
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
def superadmin_s():
    return login("superadmin@1two.one", "NewPass123!")


@pytest.fixture(autouse=True)
def reset_export_limit():
    """Exports share a 10/hour bucket in login_attempts — clear before each test."""
    clear_limits()
    yield


def pdf_text(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


# ── SUPER ADMIN: GET /api/super-admin/orgs ────────────────────────────────────
class TestSuperAdminListOrgs:
    def test_counts_match_db_for_every_org(self, superadmin_s):
        r = superadmin_s.get(f"{BASE}/super-admin/orgs", timeout=90)
        assert r.status_code == 200, r.text[:300]
        orgs = r.json()
        assert isinstance(orgs, list) and len(orgs) >= 2

        async def real(c):
            out = {}
            for row in await c.fetch("SELECT id, name, slug, status, jurisdiction, service_type, created_at FROM organisations"):
                out[row["id"]] = {
                    "row": dict(row),
                    "users": await c.fetchval("SELECT COUNT(*) FROM users WHERE org_id=$1", row["id"]),
                    "meetings": await c.fetchval("SELECT COUNT(*) FROM meetings WHERE org_id=$1", row["id"]),
                }
            return out

        expected = db(real)
        assert len(orgs) == len(expected), f"API returned {len(orgs)} orgs, DB has {len(expected)}"
        for o in orgs:
            exp = expected[o["id"]]
            assert o["user_count"] == exp["users"], f"{o['name']}: user_count {o['user_count']} != {exp['users']}"
            assert o["meeting_count"] == exp["meetings"], f"{o['name']}: meeting_count {o['meeting_count']} != {exp['meetings']}"

    def test_fields_present_and_ordered(self, superadmin_s):
        orgs = superadmin_s.get(f"{BASE}/super-admin/orgs", timeout=90).json()
        expected = db(lambda c: c.fetch("SELECT id, name, slug, status, jurisdiction, service_type, created_at FROM organisations"))
        by_id = {r["id"]: dict(r) for r in expected}
        names = [o["name"] for o in orgs]
        assert names == sorted(names), f"orgs not sorted by name ASC: {names}"
        for o in orgs:
            src = by_id[o["id"]]
            for f in ("id", "name", "slug", "status", "jurisdiction", "service_type", "created_at", "user_count", "meeting_count"):
                assert f in o, f"missing field {f} in {o}"
            assert o["name"] == src["name"]
            assert o["slug"] == src["slug"]
            assert o["status"] == src["status"]
            assert o["jurisdiction"] == (src["jurisdiction"] or "england")
            assert o["service_type"] == src["service_type"]
            assert str(o["created_at"])[:10] == str(src["created_at"])[:10]
            assert isinstance(o["user_count"], int) and isinstance(o["meeting_count"], int)


# ── EVIDENCE EXPORT: POST /api/admin/export-evidence ──────────────────────────
# Expected CSV rows for the seeded meetings (sign-off manager attendee excluded)
EXP_M1 = [
    ("Maria Santos", f"{P}M1 Maria", "CQC", "R9", "Person-centred care", "high", "accepted", "ITER102A1CQC evidence about [Redacted]"),
    ("Maria Santos", f"{P}M1 Maria", "Care Cert", "CC1", "Understand your role", "medium", "pending", "ITER102A1CC evidence"),
]
EXP_M2 = [
    ("Diane Fletcher", f"{P}M2 Diane", "CQC", "R10", "Dignity and respect", "low", "rejected", "ITER102A2CQCREJ evidence"),
    ("Diane Fletcher", f"{P}M2 Diane", "CQC", "R11", "Need for consent", "high", "accepted", "ITER102A2CQC evidence"),
    ("Diane Fletcher", f"{P}M2 Diane", "Care Cert", "CC2", "Your personal development", "high", "accepted", "ITER102A2CC evidence"),
    ("Diane Fletcher", f"{P}M2 Diane", "Organisational", "ORG1", "Local policy", "medium", "accepted", "ITER102A2CUSTOM evidence"),
]
EXP_M3 = [
    (n, f"{P}M3 MariaJane", t, ref, name, conf, st, summ)
    for n in ("Maria Santos", "Jane Smith")
    for (t, ref, name, conf, st, summ) in (
        ("CQC", "R9", "Person-centred care", "medium", "accepted", "ITER102A3CQC evidence"),
        ("Care Cert", "CC1", "Understand your role", "low", "pending", "ITER102A3CC1 evidence"),
        ("Care Cert", "CC3", "Duty of care", "high", "accepted", "ITER102A3CC3 evidence"),
    )
]


def _csv_tuples(text):
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    header = rows[0]
    assert header[0] == "Staff Member" and header[-1] == "Evidence Summary", header
    out = []
    for r in rows[1:]:
        if not r or not r[1].startswith(P):
            continue
        out.append((r[0], r[1], r[3], r[4], r[5], r[6], r[7], r[8]))
    return out


class TestEvidenceExport:
    def test_csv_meeting_ids_all_meetings_present(self, admin_s):
        r = admin_s.post(f"{BASE}/admin/export-evidence",
                         json={"format": "csv", "meeting_ids": [M1, M2, M3, M4]}, timeout=120)
        assert r.status_code == 200, r.text[:300]
        assert "text/csv" in r.headers.get("content-type", "")
        got = _csv_tuples(r.text)
        expected = EXP_M1 + EXP_M2 + EXP_M3
        assert sorted(got) == sorted(expected), (
            f"\nMISSING: {sorted(set(expected) - set(got))}\nEXTRA: {sorted(set(got) - set(expected))}")
        assert f"{P}M4" not in r.text, "meeting with dangling analysis_id must be skipped, not error"

    def test_csv_shared_analysis_and_per_meeting_redaction(self, admin_s):
        """M1 redacts 'Maria Santos'; the same phrase must survive unredacted in M2/M3."""
        r = admin_s.post(f"{BASE}/admin/export-evidence",
                         json={"format": "csv", "meeting_ids": [M1, M2, M3]}, timeout=120)
        assert r.status_code == 200
        rows = _csv_tuples(r.text)
        m1 = [x for x in rows if x[1].startswith(f"{P}M1")]
        assert all("Maria Santos" not in x[7] for x in m1), m1
        assert any("[Redacted]" in x[7] for x in m1)
        others = [x for x in rows if not x[1].startswith(f"{P}M1")]
        assert all("[Redacted]" not in x[7] for x in others), "redaction leaked across meetings"

    def test_pdf_format_contains_every_meeting(self, admin_s):
        r = admin_s.post(f"{BASE}/admin/export-evidence",
                         json={"format": "pdf", "meeting_ids": [M1, M2, M3, M4]}, timeout=120)
        assert r.status_code == 200, r.text[:300]
        assert r.content[:4] == b"%PDF"
        txt = squash(pdf_text(r.content))
        for marker in ("ITER102A1CQC", "ITER102A2CQC", "ITER102A3CQC"):
            assert marker in txt, f"{marker} missing from PDF export"
        assert squash(f"{P}M4 Dangling") not in txt

    def test_staff_ids_filter(self, admin_s):
        r = admin_s.post(f"{BASE}/admin/export-evidence",
                         json={"format": "csv", "staff_ids": [MARIA_ID],
                               "date_from": "2026-06-01", "date_to": "2026-06-30"}, timeout=120)
        assert r.status_code == 200, r.text[:300]
        rows = _csv_tuples(r.text)
        titles = {x[1] for x in rows}
        assert f"{P}M1 Maria" in titles and f"{P}M3 MariaJane" in titles
        assert f"{P}M2 Diane" not in titles, "staff_ids filter leaked a meeting without that staff member"

    def test_date_range_filter_includes_all_seeded(self, admin_s):
        r = admin_s.post(f"{BASE}/admin/export-evidence",
                         json={"format": "csv", "date_from": "2026-06-01", "date_to": "2026-06-30"}, timeout=120)
        assert r.status_code == 200, r.text[:300]
        got = _csv_tuples(r.text)
        expected = EXP_M1 + EXP_M2 + EXP_M3
        assert set(expected).issubset(set(got)), f"MISSING: {sorted(set(expected) - set(got))}"


# ── CQC EXCERPTS: GET /api/admin/export-cqc-excerpts ─────────────────────────
def _expected_mappings(field, ref_key):
    async def q(c):
        rows = await c.fetch(
            """SELECT m.id, m.title, a.""" + field + """ AS maps
               FROM meetings m JOIN analyses a ON a.id = m.analysis_id
               WHERE m.org_id=$1 AND m.status IN ('in_review','reviewed','signed_off','shared')
                 AND m.analysis_id IS NOT NULL""", ORG)
        refs, meetings = set(), set()
        for r in rows:
            maps = r["maps"]
            if isinstance(maps, str):
                maps = json.loads(maps or "[]")
            for mp in maps or []:
                if not isinstance(mp, dict) or mp.get("status") == "rejected":
                    continue
                ref = mp.get(ref_key) or ""
                if ref:
                    refs.add(ref)
                    meetings.add(r["id"])
        return refs, meetings
    return db(q)


class TestCqcExcerptsExport:
    def test_all_refs_and_meetings_present(self, admin_s):
        r = admin_s.get(f"{BASE}/admin/export-cqc-excerpts", timeout=180)
        assert r.status_code == 200, r.text[:300]
        assert r.content[:4] == b"%PDF"
        txt = squash(pdf_text(r.content))
        refs, meetings = _expected_mappings("cqc_mappings", "regulation_ref")
        assert refs, "no expected CQC refs in DB — seed problem"
        missing = [ref for ref in refs if squash(ref) not in txt]
        assert not missing, f"regulation refs missing from PDF: {missing} (expected {len(refs)} refs)"
        for marker in ("ITER102A1CQC", "ITER102A2CQC", "ITER102A3CQC"):
            assert marker in txt, f"{marker} missing"
        assert "ITER102A2CQCREJ" not in txt, "rejected mapping must be excluded"
        # per-item context
        assert squash("Diane Fletcher") in txt and squash("Demo Manager") in txt
        assert squash(f"{P}M1 Maria") in txt and squash(f"{P}M3 MariaJane") in txt
        # M1 analysis text is redacted, its attendee list is not (pre-existing behaviour)
        assert "aboutMariaSantos" not in txt


# ── CARE CERT EXCERPTS: GET /api/admin/export-cc-excerpts ────────────────────
class TestCcExcerptsExport:
    def test_all_staff(self, admin_s):
        r = admin_s.get(f"{BASE}/admin/export-cc-excerpts", timeout=180)
        assert r.status_code == 200, r.text[:300]
        txt = squash(pdf_text(r.content))
        refs, _ = _expected_mappings("care_cert_mappings", "standard_ref")
        missing = [ref for ref in refs if squash(ref) not in txt]
        assert not missing, f"standard refs missing: {missing}"
        for marker in ("ITER102A1CC", "ITER102A2CC", "ITER102A3CC1", "ITER102A3CC3"):
            assert marker in txt, f"{marker} missing"
        assert squash("All staff") in txt

    def test_staff_ids_filter_scopes_meetings(self, admin_s):
        r = admin_s.get(f"{BASE}/admin/export-cc-excerpts", params={"staff_ids": MARIA_ID}, timeout=180)
        assert r.status_code == 200, r.text[:300]
        txt = squash(pdf_text(r.content))
        assert "ITER102A1CC" in txt and "ITER102A3CC1" in txt and "ITER102A3CC3" in txt
        assert "ITER102A2CC" not in txt, "meeting without the selected staff member leaked in"
        assert squash(f"{P}M2 Diane") not in txt
        assert squash("Maria Santos") in txt
        assert "Maria_Santos" in r.headers.get("content-disposition", "")

    def test_staff_ids_filter_attendee_context_only_selected(self, admin_s):
        """M3 has Maria + Jane; filtering on Maria must not print Jane in M3's context."""
        r = admin_s.get(f"{BASE}/admin/export-cc-excerpts", params={"staff_ids": MARIA_ID}, timeout=180)
        txt = pdf_text(r.content)
        idx = txt.find(f"{P}M3")
        assert idx != -1, "M3 missing from Maria-filtered CC export"
        window = squash(txt[idx:idx + 400])
        assert squash("Jane Smith") not in window, f"unselected attendee leaked: {window[:200]}"

    def test_unknown_staff_returns_404(self, admin_s):
        r = admin_s.get(f"{BASE}/admin/export-cc-excerpts",
                        params={"staff_ids": "no-such-user-iter102"}, timeout=180)
        assert r.status_code == 404, f"expected 404, got {r.status_code}"


# ── TRANSCRIPTS EXPORT: POST /api/admin/export-transcripts ───────────────────
class TestTranscriptsExport:
    def test_all_meetings_present_and_dangling_skipped(self, admin_s):
        r = admin_s.post(f"{BASE}/admin/export-transcripts",
                         json={"meeting_ids": [M1, M2, M3, M4]}, timeout=180)
        assert r.status_code == 200, r.text[:300]
        assert r.content[:4] == b"%PDF"
        txt = squash(pdf_text(r.content))
        for marker in ("ITER102T1", "ITER102T2", "ITER102T3"):
            assert marker in txt, f"{marker} transcript missing from batched export"
        assert squash(f"{P}M4 Dangling") not in txt, "dangling transcript_id meeting must be skipped"

    def test_redaction_is_per_meeting_m1(self, admin_s):
        r = admin_s.post(f"{BASE}/admin/export-transcripts", json={"meeting_ids": [M1]}, timeout=180)
        assert r.status_code == 200, r.text[:300]
        txt = squash(pdf_text(r.content))
        # NOTE: attendee/header metadata is intentionally not redacted (pre-existing
        # behaviour, unchanged by the batching rewrite) — assert on the transcript body.
        assert "ITER102T1S[Redacted]spoke" in txt, "M1 transcript redaction not applied"
        assert "ITER102T1SMariaSantos" not in txt

    def test_redaction_does_not_cross_apply_m2(self, admin_s):
        r = admin_s.post(f"{BASE}/admin/export-transcripts", json={"meeting_ids": [M2]}, timeout=180)
        assert r.status_code == 200, r.text[:300]
        txt = squash(pdf_text(r.content))
        assert "ITER102T2SMariaSantosspoke" in txt, "M2 must keep its unredacted transcript text"
        assert "[Redacted]" not in txt, "M1's redaction leaked into M2"

    def test_batched_export_matches_per_meeting_exports(self, admin_s):
        """Batched output must equal the union of individual exports (M1 redacted, M2/M3 not)."""
        r = admin_s.post(f"{BASE}/admin/export-transcripts",
                         json={"meeting_ids": [M1, M2, M3]}, timeout=180)
        assert r.status_code == 200
        txt = squash(pdf_text(r.content))
        assert "ITER102T1S[Redacted]spoke" in txt, "M1 body should be redacted in batched export"
        assert "ITER102T2SMariaSantosspoke" in txt, "M2 body should be unredacted in batched export"
        assert "ITER102T3S" in txt

    def test_no_match_returns_404(self, admin_s):
        r = admin_s.post(f"{BASE}/admin/export-transcripts",
                         json={"meeting_ids": ["iter102-nope"]}, timeout=120)
        assert r.status_code == 404


# ── DASHBOARD: GET /api/dashboard structure scoping ──────────────────────────
def _set_manager_scope(setting_id, team_id):
    db(lambda c: c.execute(
        "UPDATE users SET setting_id=$1, team_id=$2 WHERE email='manager@supervision.com'",
        setting_id, team_id))


class TestDashboardStructure:
    @pytest.fixture(autouse=True)
    def restore_scope(self):
        yield
        _set_manager_scope(None, None)

    def test_admin_sees_all_settings_and_teams(self, admin_s):
        r = admin_s.get(f"{BASE}/dashboard", timeout=120)
        assert r.status_code == 200, r.text[:300]
        struct = r.json().get("org_structure")
        assert struct is not None, "org_structure missing for admin (fetch_structure raised — asyncio.gather masks it)"
        settings = {s["id"]: s for s in struct["settings"]}
        expected = db(lambda c: c.fetch("SELECT id FROM org_settings WHERE org_id=$1", ORG))
        assert set(settings) == {r["id"] for r in expected}
        teams = db(lambda c: c.fetch(
            "SELECT id, setting_id FROM teams WHERE org_id=$1 AND setting_id IS NOT NULL", ORG))
        for t in teams:
            ids = [x["id"] for x in settings[t["setting_id"]]["teams"]]
            assert t["id"] in ids, f"team {t['id']} missing under setting {t['setting_id']}"
        one = settings[SETTING_ONE]["teams"]
        assert {TEAM_A, TEAM_B}.issubset({t["id"] for t in one}), one
        names = [t["name"] for t in one]
        assert names == sorted(names), f"teams not sorted by name: {names}"

    def test_setting_scoped_manager_sees_only_own_setting_with_all_its_teams(self):
        _set_manager_scope(SETTING_ONE, None)
        s = login("manager@supervision.com", "Manager123!")
        r = s.get(f"{BASE}/dashboard", timeout=120)
        assert r.status_code == 200, r.text[:300]
        struct = r.json()["org_structure"]
        assert [x["id"] for x in struct["settings"]] == [SETTING_ONE]
        team_ids = {t["id"] for t in struct["settings"][0]["teams"]}
        assert {TEAM_A, TEAM_B}.issubset(team_ids), team_ids

    def test_team_scoped_manager_sees_only_own_team(self):
        _set_manager_scope(SETTING_ONE, TEAM_A)
        s = login("manager@supervision.com", "Manager123!")
        r = s.get(f"{BASE}/dashboard", timeout=120)
        assert r.status_code == 200, r.text[:300]
        struct = r.json()["org_structure"]
        assert [x["id"] for x in struct["settings"]] == [SETTING_ONE]
        team_ids = [t["id"] for t in struct["settings"][0]["teams"]]
        assert team_ids == [TEAM_A], f"team-scoped manager saw {team_ids}"


# ── SHARE MEETING: POST /api/review/{id}/share ───────────────────────────────
def _reset_share(meeting_id):
    db(lambda c: c.execute(
        "UPDATE meetings SET status='signed_off', shared_with='[]'::jsonb WHERE id=$1", meeting_id))


class TestShareMeeting:
    @pytest.fixture(autouse=True)
    def clean_share_state(self):
        _reset_share(M3)
        yield
        _reset_share(M3)

    def _shared_ids_in_db(self):
        raw = db(lambda c: c.fetchval("SELECT shared_with FROM meetings WHERE id=$1", M3))
        rows = json.loads(raw) if isinstance(raw, str) else (raw or [])
        return [x["user_id"] for x in rows]

    def test_share_with_multiple_users_at_once(self, admin_s):
        r = admin_s.post(f"{BASE}/review/{M3}/share",
                         json={"user_ids": [SARAH_ID, ADMIN_ID, REVIEWER_ID]}, timeout=90)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert "3 new user(s)" in body["message"], body["message"]
        got = [x["user_id"] for x in body["shared_with"]]
        assert sorted(got) == sorted([SARAH_ID, ADMIN_ID, REVIEWER_ID])
        assert sorted(self._shared_ids_in_db()) == sorted(got)
        for entry in body["shared_with"]:
            assert entry["name"] and entry["email"] and entry["shared_at"]
        assert db(lambda c: c.fetchval("SELECT status FROM meetings WHERE id=$1", M3)) == "shared"

    def test_reshare_only_adds_new_users(self, admin_s):
        r1 = admin_s.post(f"{BASE}/review/{M3}/share", json={"user_ids": [SARAH_ID, ADMIN_ID]}, timeout=90)
        assert r1.status_code == 200 and "2 new user(s)" in r1.json()["message"]
        r2 = admin_s.post(f"{BASE}/review/{M3}/share",
                          json={"user_ids": [SARAH_ID, ADMIN_ID, MANAGER_ID]}, timeout=90)
        assert r2.status_code == 200, r2.text[:300]
        assert "1 new user(s)" in r2.json()["message"], r2.json()["message"]
        ids = [x["user_id"] for x in r2.json()["shared_with"]]
        assert sorted(ids) == sorted([SARAH_ID, ADMIN_ID, MANAGER_ID])
        assert len(ids) == len(set(ids)), f"duplicates in shared_with: {ids}"

    def test_attendee_role_silently_skipped(self, admin_s):
        r = admin_s.post(f"{BASE}/review/{M3}/share", json={"user_ids": [JANE_ID]}, timeout=90)
        assert r.status_code == 200, r.text[:300]
        assert "0 new user(s)" in r.json()["message"], r.json()["message"]
        assert r.json()["shared_with"] == []
        assert self._shared_ids_in_db() == []

    def test_duplicate_user_id_in_same_request_added_once(self, admin_s):
        r = admin_s.post(f"{BASE}/review/{M3}/share",
                         json={"user_ids": [SARAH_ID, SARAH_ID, SARAH_ID]}, timeout=90)
        assert r.status_code == 200, r.text[:300]
        assert "1 new user(s)" in r.json()["message"], r.json()["message"]
        ids = [x["user_id"] for x in r.json()["shared_with"]]
        assert ids == [SARAH_ID], ids
        assert self._shared_ids_in_db() == [SARAH_ID]

    def test_mixed_valid_invalid_and_duplicate(self, admin_s):
        r = admin_s.post(f"{BASE}/review/{M3}/share",
                         json={"user_ids": [SARAH_ID, "iter102-bogus-user", JANE_ID, SARAH_ID, REVIEWER_ID]},
                         timeout=90)
        assert r.status_code == 200, r.text[:300]
        assert "2 new user(s)" in r.json()["message"], r.json()["message"]
        assert sorted(x["user_id"] for x in r.json()["shared_with"]) == sorted([SARAH_ID, REVIEWER_ID])

    def test_empty_user_ids(self, admin_s):
        r = admin_s.post(f"{BASE}/review/{M3}/share", json={"user_ids": []}, timeout=90)
        assert r.status_code == 200, r.text[:300]
        assert "0 new user(s)" in r.json()["message"]

    def test_draft_meeting_rejected(self, admin_s):
        db(lambda c: c.execute("UPDATE meetings SET status='draft' WHERE id=$1", M3))
        try:
            r = admin_s.post(f"{BASE}/review/{M3}/share", json={"user_ids": [SARAH_ID]}, timeout=90)
            assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text[:200]}"
        finally:
            _reset_share(M3)


# ── Extra edge cases for the batched queries ─────────────────────────────────
CROSS_ORG_ADMIN = "830588a1-3f79-4d35-af32-d0b285656077"  # admin in "IDOR Test Org B"


class TestBatchingEdgeCases:
    def test_share_cross_org_user_is_skipped(self, admin_s):
        _reset_share(M3)
        try:
            r = admin_s.post(f"{BASE}/review/{M3}/share",
                             json={"user_ids": [CROSS_ORG_ADMIN, SARAH_ID]}, timeout=90)
            assert r.status_code == 200, r.text[:300]
            assert "1 new user(s)" in r.json()["message"], r.json()["message"]
            ids = [x["user_id"] for x in r.json()["shared_with"]]
            assert ids == [SARAH_ID], f"cross-org user leaked into shared_with: {ids}"
        finally:
            _reset_share(M3)

    def test_dashboard_scope_with_nonexistent_setting_returns_empty(self):
        """Empty setting_ids list must not blow up ANY($1::text[])."""
        _set_manager_scope("iter102-nonexistent-setting", None)
        try:
            s = login("manager@supervision.com", "Manager123!")
            r = s.get(f"{BASE}/dashboard", timeout=120)
            assert r.status_code == 200, r.text[:300]
            struct = r.json()["org_structure"]
            assert struct is not None, "fetch_structure raised (masked by asyncio.gather)"
            assert struct["settings"] == [], struct["settings"]
        finally:
            _set_manager_scope(None, None)

    def test_scoped_manager_evidence_export_param_ordering(self):
        """SEC-002 scope filter + meeting_ids filter placeholders must stay aligned."""
        _set_manager_scope(SETTING_ONE, None)
        try:
            s = login("manager@supervision.com", "Manager123!")
            clear_limits()
            r = s.post(f"{BASE}/admin/export-evidence",
                       json={"format": "csv", "meeting_ids": [M1, M2, M3, M4]}, timeout=120)
            assert r.status_code == 200, r.text[:300]
            got = _csv_tuples(r.text)
            expected = EXP_M1 + EXP_M2 + EXP_M3
            # all seeded meetings have sign_off_manager_id = this manager, so all are in scope
            assert sorted(got) == sorted(expected), (
                f"\nMISSING: {sorted(set(expected) - set(got))}\nEXTRA: {sorted(set(got) - set(expected))}")
        finally:
            _set_manager_scope(None, None)

    def test_scoped_manager_transcripts_export_param_ordering(self):
        _set_manager_scope(SETTING_ONE, None)
        try:
            s = login("manager@supervision.com", "Manager123!")
            clear_limits()
            r = s.post(f"{BASE}/admin/export-transcripts",
                       json={"meeting_ids": [M1, M2, M3, M4]}, timeout=180)
            assert r.status_code == 200, r.text[:300]
            txt = squash(pdf_text(r.content))
            assert "ITER102T1S[Redacted]spoke" in txt
            assert "ITER102T2SMariaSantosspoke" in txt
            assert "ITER102T3S" in txt
        finally:
            _set_manager_scope(None, None)
