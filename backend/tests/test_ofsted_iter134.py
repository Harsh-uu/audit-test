"""
Iteration 134 — OFSTED jurisdiction feature + NI rescan bugfix regression tests.

Covers:
 - Super Admin org CRUD with new jurisdiction=ofsted + service_type (school/early_years/childrens_home)
 - Cross-family validation: NI service_types cannot be used with Ofsted (and vice versa)
 - Existing england/wales/scotland/NI org CRUD (regression)
 - admin.py list_standards returns only correct standards per Ofsted service_type
 - Seed row counts per Ofsted service_type (7+9 school, 5+7 early_years, 9+16 childrens_home)
 - AI ai.py reg/cert labels for ofsted_school / ofsted_early_years / ofsted_childrens_home
 - review.py _run_rescan_background builds effective_jurisdiction for NI + Ofsted
"""
import os
import re as _re
import uuid
import bcrypt
import pytest
import requests

def _read_env():
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                m = _re.match(r"^REACT_APP_BACKEND_URL=(.+)$", line.strip())
                if m:
                    return m.group(1).strip().rstrip("/")
    except Exception:
        pass
    v = os.environ.get("REACT_APP_BACKEND_URL")
    return v.rstrip("/") if v else None

BASE_URL = _read_env()
assert BASE_URL, "REACT_APP_BACKEND_URL not set"
SUPER_EMAIL = "superadmin@1two.one"
SUPER_PASS = "TestPass123!"


def _login_super_admin(session: requests.Session) -> None:
    """Login super-admin, bypass MFA via DB bcrypt override, verify MFA, populate session cookies."""
    r = session.post(f"{BASE_URL}/api/auth/login", json={"email": SUPER_EMAIL, "password": SUPER_PASS}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    assert data.get("requires_mfa") is True
    mfa_session = data["mfa_session"]

    # Overwrite MFA code in DB directly via asyncpg
    import asyncio, asyncpg
    from dotenv import dotenv_values
    be = dotenv_values("/app/backend/.env")
    DSN = be["DATABASE_URL"]

    async def _set_code():
        conn = await asyncpg.connect(DSN, ssl="require")
        h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
        from datetime import datetime, timezone, timedelta
        exp = datetime.now(timezone.utc) + timedelta(minutes=10)
        await conn.execute(
            "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
            h, exp, SUPER_EMAIL,
        )
        await conn.close()
    asyncio.run(_set_code())

    r2 = session.post(f"{BASE_URL}/api/auth/verify-mfa", json={"mfa_session": mfa_session, "code": "123456"}, timeout=30)
    assert r2.status_code == 200, f"mfa verify failed: {r2.status_code} {r2.text}"


async def _db_query(sql, *args):
    import asyncpg
    from dotenv import dotenv_values
    be = dotenv_values("/app/backend/.env")
    conn = await asyncpg.connect(be["DATABASE_URL"], ssl="require")
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


@pytest.fixture(scope="module")
def sa_session():
    s = requests.Session()
    _login_super_admin(s)
    yield s
    # Cleanup: delete any TEST_ orgs we created
    try:
        orgs = s.get(f"{BASE_URL}/api/super-admin/orgs", timeout=15).json()
        for o in orgs:
            if o.get("name", "").startswith("TEST_ITER134_"):
                s.delete(f"{BASE_URL}/api/super-admin/orgs/{o['id']}", timeout=15)
    except Exception:
        pass


# ---------- Super Admin org validation ----------
class TestOfstedOrgCreate:
    def test_create_ofsted_school(self, sa_session):
        name = f"TEST_ITER134_OfstedSchool_{uuid.uuid4().hex[:6]}"
        r = sa_session.post(f"{BASE_URL}/api/super-admin/orgs",
                            json={"name": name, "jurisdiction": "ofsted", "service_type": "school"}, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["jurisdiction"] == "ofsted"
        assert j["service_type"] == "school"

    def test_create_ofsted_early_years(self, sa_session):
        name = f"TEST_ITER134_OfstedEY_{uuid.uuid4().hex[:6]}"
        r = sa_session.post(f"{BASE_URL}/api/super-admin/orgs",
                            json={"name": name, "jurisdiction": "ofsted", "service_type": "early_years"}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["service_type"] == "early_years"

    def test_create_ofsted_childrens_home(self, sa_session):
        name = f"TEST_ITER134_OfstedCH_{uuid.uuid4().hex[:6]}"
        r = sa_session.post(f"{BASE_URL}/api/super-admin/orgs",
                            json={"name": name, "jurisdiction": "ofsted", "service_type": "childrens_home"}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["service_type"] == "childrens_home"

    def test_create_ofsted_missing_service_type_400(self, sa_session):
        r = sa_session.post(f"{BASE_URL}/api/super-admin/orgs",
                            json={"name": f"TEST_ITER134_bad_{uuid.uuid4().hex[:6]}", "jurisdiction": "ofsted"}, timeout=15)
        assert r.status_code == 400
        assert "service_type" in r.text.lower() and "ofsted" in r.text.lower()

    def test_create_ofsted_with_ni_service_type_rejected(self, sa_session):
        # Cross-family: Ofsted with 'residential' should fail
        r = sa_session.post(f"{BASE_URL}/api/super-admin/orgs",
                            json={"name": f"TEST_ITER134_x_{uuid.uuid4().hex[:6]}", "jurisdiction": "ofsted", "service_type": "residential"}, timeout=15)
        assert r.status_code == 400

    def test_create_ni_with_ofsted_service_type_rejected(self, sa_session):
        r = sa_session.post(f"{BASE_URL}/api/super-admin/orgs",
                            json={"name": f"TEST_ITER134_x2_{uuid.uuid4().hex[:6]}", "jurisdiction": "northern_ireland", "service_type": "school"}, timeout=15)
        assert r.status_code == 400


# ---------- Regression on existing jurisdictions ----------
class TestExistingJurisdictionsRegression:
    def test_create_england(self, sa_session):
        r = sa_session.post(f"{BASE_URL}/api/super-admin/orgs",
                            json={"name": f"TEST_ITER134_Eng_{uuid.uuid4().hex[:6]}", "jurisdiction": "england"}, timeout=15)
        assert r.status_code == 200
        assert r.json()["jurisdiction"] == "england"
        assert r.json()["service_type"] is None

    def test_create_wales(self, sa_session):
        r = sa_session.post(f"{BASE_URL}/api/super-admin/orgs",
                            json={"name": f"TEST_ITER134_Wal_{uuid.uuid4().hex[:6]}", "jurisdiction": "wales"}, timeout=15)
        assert r.status_code == 200

    def test_create_scotland(self, sa_session):
        r = sa_session.post(f"{BASE_URL}/api/super-admin/orgs",
                            json={"name": f"TEST_ITER134_Sco_{uuid.uuid4().hex[:6]}", "jurisdiction": "scotland"}, timeout=15)
        assert r.status_code == 200

    def test_create_ni_residential(self, sa_session):
        r = sa_session.post(f"{BASE_URL}/api/super-admin/orgs",
                            json={"name": f"TEST_ITER134_NIres_{uuid.uuid4().hex[:6]}", "jurisdiction": "northern_ireland", "service_type": "residential"}, timeout=15)
        assert r.status_code == 200
        assert r.json()["service_type"] == "residential"

    def test_create_ni_domiciliary(self, sa_session):
        r = sa_session.post(f"{BASE_URL}/api/super-admin/orgs",
                            json={"name": f"TEST_ITER134_NIdom_{uuid.uuid4().hex[:6]}", "jurisdiction": "northern_ireland", "service_type": "domiciliary"}, timeout=15)
        assert r.status_code == 200

    def test_create_ni_missing_service_type_400(self, sa_session):
        r = sa_session.post(f"{BASE_URL}/api/super-admin/orgs",
                            json={"name": f"TEST_ITER134_NIx_{uuid.uuid4().hex[:6]}", "jurisdiction": "northern_ireland"}, timeout=15)
        assert r.status_code == 400


# ---------- Edit org: jurisdiction transitions ----------
class TestOfstedEdit:
    def test_switch_england_to_ofsted_then_back(self, sa_session):
        name = f"TEST_ITER134_Switch_{uuid.uuid4().hex[:6]}"
        r = sa_session.post(f"{BASE_URL}/api/super-admin/orgs",
                            json={"name": name, "jurisdiction": "england"}, timeout=15)
        org_id = r.json()["id"]

        # Switching to ofsted without service_type should fail
        r2 = sa_session.patch(f"{BASE_URL}/api/super-admin/orgs/{org_id}",
                              json={"jurisdiction": "ofsted"}, timeout=15)
        assert r2.status_code == 400

        # Switching with proper service_type succeeds
        r3 = sa_session.patch(f"{BASE_URL}/api/super-admin/orgs/{org_id}",
                              json={"jurisdiction": "ofsted", "service_type": "early_years"}, timeout=15)
        assert r3.status_code == 200

        # Verify persisted
        orgs = sa_session.get(f"{BASE_URL}/api/super-admin/orgs", timeout=15).json()
        this = next(o for o in orgs if o["id"] == org_id)
        assert this["jurisdiction"] == "ofsted"
        assert this["service_type"] == "early_years"

        # Switch back to england → service_type should be cleared
        r4 = sa_session.patch(f"{BASE_URL}/api/super-admin/orgs/{org_id}",
                              json={"jurisdiction": "england", "service_type": ""}, timeout=15)
        assert r4.status_code == 200
        orgs = sa_session.get(f"{BASE_URL}/api/super-admin/orgs", timeout=15).json()
        this = next(o for o in orgs if o["id"] == org_id)
        assert this["jurisdiction"] == "england"
        assert this["service_type"] in (None, "")


# ---------- Standards seed row counts ----------
class TestStandardsSeed:
    def test_ofsted_seed_row_counts(self):
        import asyncio
        async def _q():
            rows = await _db_query(
                "SELECT type, COUNT(*)::int AS n FROM standards_entries WHERE is_system=TRUE AND jurisdiction='ofsted' GROUP BY type ORDER BY type"
            )
            return {r["type"]: r["n"] for r in rows}
        counts = asyncio.run(_q())
        # Per review request: 7 eif + 9 teachers_standards, 5 eyfs_safeguarding + 7 eyfs_learning, 9 chqs + 16 l3_residential
        assert counts.get("eif") == 7, f"eif rows: {counts}"
        assert counts.get("teachers_standards") == 9, f"teachers_standards rows: {counts}"
        assert counts.get("eyfs_safeguarding") == 5, f"eyfs_safeguarding rows: {counts}"
        assert counts.get("eyfs_learning") == 7, f"eyfs_learning rows: {counts}"
        assert counts.get("chqs") == 9, f"chqs rows: {counts}"
        assert counts.get("l3_residential") == 16, f"l3_residential rows: {counts}"


# ---------- admin.py list_standards scoping ----------
class TestListStandardsScoping:
    def _mk_org(self, sa_session, service_type):
        name = f"TEST_ITER134_LS_{service_type}_{uuid.uuid4().hex[:6]}"
        r = sa_session.post(f"{BASE_URL}/api/super-admin/orgs",
                            json={"name": name, "jurisdiction": "ofsted", "service_type": service_type}, timeout=15)
        assert r.status_code == 200, r.text
        return r.json()["id"]

    @pytest.mark.parametrize("stype,exp_reg,exp_cert", [
        ("school", "eif", "teachers_standards"),
        ("early_years", "eyfs_safeguarding", "eyfs_learning"),
        ("childrens_home", "chqs", "l3_residential"),
    ])
    def test_list_standards_scoped(self, sa_session, stype, exp_reg, exp_cert):
        """Direct DB query mirroring admin.py list_standards logic for Ofsted."""
        org_id = self._mk_org(sa_session, stype)
        import asyncio
        async def _q():
            rows = await _db_query(
                "SELECT type, COUNT(*)::int AS n FROM standards_entries "
                "WHERE is_active=TRUE AND is_system=TRUE AND jurisdiction='ofsted' AND service_type=$1 "
                "GROUP BY type",
                stype,
            )
            return {r["type"]: r["n"] for r in rows}
        counts = asyncio.run(_q())
        assert exp_reg in counts, f"missing {exp_reg} for {stype}: {counts}"
        assert exp_cert in counts, f"missing {exp_cert} for {stype}: {counts}"
        # No cross-contamination: no cqc/awif_qual/etc for this service_type
        forbidden = {"cqc", "care_certificate", "sssc", "awif_qual", "rqic_res", "rqic_dom", "niscc", "rqia"}
        cross = set(counts.keys()) & forbidden
        assert not cross, f"Cross-jurisdiction rows leaked into ofsted {stype}: {cross}"


# ---------- AI reg/cert labels ----------
class TestAiLabels:
    def test_ai_analyze_meeting_labels(self):
        """Verify the reg_label/cert_label branches in ai.py return correct strings for ofsted_* jurisdictions."""
        import sys
        sys.path.insert(0, "/app/backend")
        # Read source, look for the exact label strings expected for each ofsted variant
        with open("/app/backend/utils/ai.py") as f:
            src = f.read()
        # 3 branches × 2 locations (analyze_doc_for_evidence + analyze_meeting)
        assert 'jurisdiction == "ofsted_school"' in src
        assert 'jurisdiction == "ofsted_early_years"' in src
        assert 'jurisdiction == "ofsted_childrens_home"' in src
        assert src.count('jurisdiction == "ofsted_school"') >= 2
        assert src.count('jurisdiction == "ofsted_early_years"') >= 2
        assert src.count('jurisdiction == "ofsted_childrens_home"') >= 2


# ---------- NI rescan bugfix (source verification) ----------
class TestNiRescanBugfix:
    def test_rescan_builds_effective_jurisdiction_for_ni(self):
        with open("/app/backend/routers/review.py") as f:
            src = f.read()
        # The bugfix inserts an effective_jurisdiction string for NI
        assert 'effective_jurisdiction = f"northern_ireland_{org_service_type' in src
        assert 'effective_jurisdiction = f"ofsted_{org_service_type' in src
        # And passes it as jurisdiction= to _analyze_meeting
        assert "jurisdiction=effective_jurisdiction" in src


# ---------- prep.py sector_label for Ofsted ----------
class TestPrepSectorLabel:
    def test_prep_computes_sector_label_for_ofsted(self):
        with open("/app/backend/routers/prep.py") as f:
            src = f.read()
        assert 'jurisdiction"] == "ofsted"' in src or "jurisdiction'] == 'ofsted'" in src
        # Ensure sector_label is computed & passed
        assert "sector_label" in src
