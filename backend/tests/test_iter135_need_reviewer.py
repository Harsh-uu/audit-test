"""Iteration 135 — Sector Override + Need Reviewer regression tests.

Covers:
1. `_ofsted_sector_override` returns empty string for england/wales/scotland/NI (byte-identical prompt regression).
2. `_ofsted_sector_override` returns correct block for Ofsted sub-sectors (school/early_years/childrens_home).
3. Migration m022: need_review_signals table + RLS policy + lookup index exist.
4. `process_need_review_signals`: threshold=3 injects a Need Reviewer risk with correct shape, ID, severity, text.
5. `process_need_review_signals`: hits 1 and 2 do NOT inject a risk (but DO persist rows).
6. `process_need_review_signals`: is a no-op for jurisdiction='ofsted' or 'ofsted_school' (no risk, no DB rows).
7. `process_need_review_signals`: dedupes within a single meeting (same person+category twice → 1 row).
8. `process_need_review_signals`: bad category / empty name are dropped.
9. `process_need_review_signals`: case-insensitive person matching for the count.
10. `process_need_review_signals`: multiple different persons/categories accumulate independently.
11. Backend /api/health responds 200.
"""
import os
import sys
import uuid
import asyncio
import pytest
import requests
from dotenv import load_dotenv

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")

import asyncpg  # noqa: E402
from utils.ai import _ofsted_sector_override, ANALYSIS_SYSTEM_PROMPT, DOC_EVIDENCE_SYSTEM_PROMPT, SUMMARY_ONLY_PROMPT, PII_SCAN_SYSTEM_PROMPT  # noqa: E402
from utils.need_reviewer import process_need_review_signals, THRESHOLD, CONCERN_CATEGORIES  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or "https://supervision-preview.preview.emergentagent.com"
DB_URL = os.environ["DATABASE_URL"]


# ---------- Sector Override regression ----------

class TestSectorOverride:
    @pytest.mark.parametrize("juris", ["england", "wales", "scotland", "northern_ireland", "northern_ireland_residential", "northern_ireland_domiciliary", "", None])
    def test_non_ofsted_returns_empty(self, juris):
        assert _ofsted_sector_override(juris) == ""

    def test_ofsted_school(self):
        s = _ofsted_sector_override("ofsted_school")
        assert "SECTOR OVERRIDE" in s
        assert "pupil" in s
        assert "school" in s.lower()
        assert "pastoral" in s.lower()

    def test_ofsted_early_years(self):
        s = _ofsted_sector_override("ofsted_early_years")
        assert "child" in s
        assert "nursery" in s.lower() or "early years" in s.lower()

    def test_ofsted_childrens_home(self):
        s = _ofsted_sector_override("ofsted_childrens_home")
        assert "child" in s
        assert "children's" in s.lower() or "childrens" in s.lower() or "residential" in s.lower()

    def test_ofsted_bare(self):
        # Bare 'ofsted' still activates override (defensive)
        s = _ofsted_sector_override("ofsted")
        assert "SECTOR OVERRIDE" in s

    def test_prompts_contain_need_review_signals_schema(self):
        # Verify need_review_signals is in ANALYSIS_SYSTEM_PROMPT only
        assert "need_review_signals" in ANALYSIS_SYSTEM_PROMPT
        # Categories referenced
        for cat in ["insufficient_visit_time", "repeated_falls", "missed_or_late_medication"]:
            assert cat in ANALYSIS_SYSTEM_PROMPT
        # Other prompts should NOT accidentally list need_review_signals
        assert "need_review_signals" not in DOC_EVIDENCE_SYSTEM_PROMPT
        assert "need_review_signals" not in SUMMARY_ONLY_PROMPT
        assert "need_review_signals" not in PII_SCAN_SYSTEM_PROMPT


# ---------- Migration m022 ----------

@pytest.mark.asyncio
class TestMigration022:
    async def test_table_and_policy_exist(self):
        conn = await asyncpg.connect(DB_URL)
        try:
            t = await conn.fetchval("SELECT to_regclass('need_review_signals')")
            assert t == "need_review_signals"
            rls = await conn.fetchrow("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname='need_review_signals'")
            assert rls["relrowsecurity"] is True
            assert rls["relforcerowsecurity"] is True
            pols = [r["polname"] for r in await conn.fetch("SELECT polname FROM pg_policy WHERE polrelid='need_review_signals'::regclass")]
            assert "need_review_signals_rls" in pols
            idx = [r["indexname"] for r in await conn.fetch("SELECT indexname FROM pg_indexes WHERE tablename='need_review_signals'")]
            assert "idx_need_review_signals_lookup" in idx
        finally:
            await conn.close()


# ---------- process_need_review_signals (real DB) ----------

@pytest.fixture
def test_org_id():
    return str(uuid.uuid4())


async def _cleanup(conn, org_id):
    await conn.execute("DELETE FROM need_review_signals WHERE org_id=$1", org_id)


@pytest.mark.asyncio
class TestProcessNeedReviewSignals:

    async def _connect(self):
        return await asyncpg.connect(DB_URL)

    async def test_below_threshold_no_risk(self, test_org_id):
        conn = await self._connect()
        try:
            result = {"risks": [{"id": "r1", "text": "existing"}], "need_review_signals": [
                {"person_name": "Edith", "concern_category": "insufficient_visit_time", "quote": "not enough time with Edith"}
            ]}
            # Hit 1
            await process_need_review_signals(conn, test_org_id, str(uuid.uuid4()), result, "england")
            assert len(result["risks"]) == 1, "No new risk on hit 1"

            # Hit 2 — fresh result dict
            result2 = {"risks": [], "need_review_signals": [
                {"person_name": "edith", "concern_category": "insufficient_visit_time", "quote": "again not enough"}
            ]}
            await process_need_review_signals(conn, test_org_id, str(uuid.uuid4()), result2, "wales")
            assert len(result2["risks"]) == 0, "No new risk on hit 2"

            # DB should have 2 rows total
            count = await conn.fetchval("SELECT COUNT(*) FROM need_review_signals WHERE org_id=$1", test_org_id)
            assert count == 2
        finally:
            await _cleanup(conn, test_org_id); await conn.close()

    async def test_threshold_injects_risk(self, test_org_id):
        conn = await self._connect()
        try:
            for i in range(2):
                r = {"risks": [], "need_review_signals": [
                    {"person_name": "Edith", "concern_category": "insufficient_visit_time", "quote": f"quote{i}"}
                ]}
                await process_need_review_signals(conn, test_org_id, str(uuid.uuid4()), r, "england")
                assert not any(str(x.get("id","")).startswith("needreview_") for x in r["risks"])
            # Third hit — must inject
            r3 = {"risks": [{"id": "orig", "text": "orig risk"}], "need_review_signals": [
                {"person_name": "EDITH", "concern_category": "insufficient_visit_time", "quote": "third time"}
            ]}
            await process_need_review_signals(conn, test_org_id, str(uuid.uuid4()), r3, "england")
            new = [x for x in r3["risks"] if str(x.get("id","")).startswith("needreview_")]
            assert len(new) == 1
            entry = new[0]
            assert entry["severity"] == "high"
            assert "Need Reviewer" in entry["text"]
            assert "EDITH" in entry["text"] or "Edith" in entry["text"]
            assert "insufficient visit time" in entry["text"]
            assert "3 times" in entry["text"]
            assert isinstance(entry["suggested_resolutions"], list) and len(entry["suggested_resolutions"]) >= 1
            # Original risk preserved
            assert any(x.get("id") == "orig" for x in r3["risks"])
        finally:
            await _cleanup(conn, test_org_id); await conn.close()

    async def test_ofsted_is_noop(self, test_org_id):
        conn = await self._connect()
        try:
            for j in ["ofsted", "ofsted_school", "ofsted_early_years"]:
                r = {"risks": [], "need_review_signals": [
                    {"person_name": "TommyPupil", "concern_category": "insufficient_visit_time", "quote": "q"}
                ]}
                await process_need_review_signals(conn, test_org_id, str(uuid.uuid4()), r, j)
                assert r["risks"] == [], f"Ofsted juris {j} should not inject"
            # Zero rows written for this org
            count = await conn.fetchval("SELECT COUNT(*) FROM need_review_signals WHERE org_id=$1", test_org_id)
            assert count == 0, "Ofsted must not write DB rows"
        finally:
            await _cleanup(conn, test_org_id); await conn.close()

    async def test_dedupe_within_meeting(self, test_org_id):
        conn = await self._connect()
        try:
            mid = str(uuid.uuid4())
            r = {"risks": [], "need_review_signals": [
                {"person_name": "Alice", "concern_category": "repeated_falls", "quote": "fell"},
                {"person_name": "alice", "concern_category": "repeated_falls", "quote": "fell again"},
                {"person_name": "Alice", "concern_category": "repeated_falls", "quote": "yet another"},
            ]}
            await process_need_review_signals(conn, test_org_id, mid, r, "england")
            count = await conn.fetchval("SELECT COUNT(*) FROM need_review_signals WHERE meeting_id=$1", mid)
            assert count == 1, "Dedupe should collapse same person+category to 1 row per meeting"
        finally:
            await _cleanup(conn, test_org_id); await conn.close()

    async def test_bad_input_dropped(self, test_org_id):
        conn = await self._connect()
        try:
            r = {"risks": [], "need_review_signals": [
                {"person_name": "", "concern_category": "repeated_falls", "quote": "q"},
                {"person_name": "Bob", "concern_category": "nonsense_category", "quote": "q"},
                "not-a-dict",
                {"person_name": "Carol", "concern_category": "missed_or_late_medication", "quote": "valid"},
            ]}
            await process_need_review_signals(conn, test_org_id, str(uuid.uuid4()), r, "england")
            count = await conn.fetchval("SELECT COUNT(*) FROM need_review_signals WHERE org_id=$1", test_org_id)
            assert count == 1
        finally:
            await _cleanup(conn, test_org_id); await conn.close()

    async def test_independent_persons_categories(self, test_org_id):
        conn = await self._connect()
        try:
            # Person A: 3 hits on category X → should trigger
            # Person B: 2 hits on category X → should NOT trigger
            # Person A: 1 hit on category Y → should NOT trigger
            for i in range(3):
                r = {"risks": [], "need_review_signals": [
                    {"person_name": "Alpha", "concern_category": "repeated_falls", "quote": f"a{i}"}
                ]}
                await process_need_review_signals(conn, test_org_id, str(uuid.uuid4()), r, "england")
                triggered = any(str(x.get("id","")).startswith("needreview_") for x in r["risks"])
                if i < 2:
                    assert not triggered
                else:
                    assert triggered

            for i in range(2):
                r = {"risks": [], "need_review_signals": [
                    {"person_name": "Beta", "concern_category": "repeated_falls", "quote": f"b{i}"}
                ]}
                await process_need_review_signals(conn, test_org_id, str(uuid.uuid4()), r, "england")
                assert not any(str(x.get("id","")).startswith("needreview_") for x in r["risks"])

            r = {"risks": [], "need_review_signals": [
                {"person_name": "Alpha", "concern_category": "family_requesting_more_support", "quote": "z"}
            ]}
            await process_need_review_signals(conn, test_org_id, str(uuid.uuid4()), r, "england")
            assert not any(str(x.get("id","")).startswith("needreview_") for x in r["risks"])
        finally:
            await _cleanup(conn, test_org_id); await conn.close()

    async def test_all_categories_valid(self):
        # Sanity — every category the prompt lists is in CONCERN_CATEGORIES set
        expected = {"insufficient_visit_time","missed_or_late_medication","repeated_falls",
                    "missed_or_incomplete_visits","deteriorating_condition_unaddressed",
                    "family_requesting_more_support","staffing_capacity_mismatch"}
        assert CONCERN_CATEGORIES == expected
        assert THRESHOLD == 3


# ---------- Backend health ----------

class TestBackendHealth:
    def test_health_endpoint(self):
        try:
            r = requests.get(f"{BASE_URL}/api/health", timeout=15)
            assert r.status_code in (200, 204), f"got {r.status_code}"
        except requests.RequestException as e:
            pytest.skip(f"backend not reachable: {e}")
