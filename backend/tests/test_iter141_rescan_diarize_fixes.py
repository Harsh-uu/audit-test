"""Iter 141 — tests for AI-pipeline sequencing + rescan data-integrity fixes.

Covers:
  FIX 1: transcription_pipeline.py awaits diarisation BEFORE analyze_meeting.
         (Code-inspection assertion only — full pipeline requires a fresh
         multi-speaker recording which isn't feasible in this env.)
  FIX 2: rescan-generated cqc/care_cert/custom mapping ids are globally
         unique (uuid-hex[:12]), not model's sequential "cqc_1"/"cqc_2".
  FIX 3: rescan permanently preserves any evidence item whose status is
         not 'pending' (accepted / rejected / needs_followup).

Rescan is a real LLM call (Vertex/OpenAI fallback) and takes 1-2 min.
"""
import asyncio
import json
import os
import re
import sys
import time
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

# Existing meeting in Test Company org (admin@supervision.com) with analysis+transcript.
MEETING_ID = "25b5a9be-9f01-4a7d-8f70-9eff81c89bb4"
ANALYSIS_ID = "5d0c91ed-51fa-479d-8e86-9fc9bac306dc"

UUID_ID_RE = re.compile(r"^(cqc|cc|custom)_[a-f0-9]{12}$")


# ─── Auth ────────────────────────────────────────────────────────────────────

async def _bypass_mfa(email: str):
    conn = await asyncpg.connect(DSN, ssl="require")
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = datetime.now(timezone.utc) + timedelta(minutes=10)
    await conn.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, exp, email)
    await conn.close()


def _login(email: str, password: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=60)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    data = r.json()
    if data.get("requires_mfa"):
        asyncio.get_event_loop().run_until_complete(_bypass_mfa(email)) if False else asyncio.run(_bypass_mfa(email))
        r2 = s.post(f"{BASE}/auth/verify-mfa",
                    json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=60)
        assert r2.status_code == 200, f"verify-mfa failed: {r2.status_code} {r2.text[:200]}"
    return s


@pytest.fixture(scope="module")
def admin_session():
    return _login("admin@supervision.com", "Admin123!")


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _db_read_analysis(analysis_id: str):
    conn = await asyncpg.connect(DSN, ssl="require")
    row = await conn.fetchrow(
        "SELECT cqc_mappings, care_cert_mappings, custom_mappings FROM analyses WHERE id=$1",
        analysis_id)
    await conn.close()
    def _l(v):
        if v is None: return []
        if isinstance(v, str):
            try: return json.loads(v)
            except Exception: return []
        return v if isinstance(v, list) else []
    return {
        "cqc": _l(row["cqc_mappings"]),
        "cc":  _l(row["care_cert_mappings"]),
        "custom": _l(row["custom_mappings"]),
    }


async def _db_rescan_status(meeting_id: str) -> str:
    conn = await asyncpg.connect(DSN, ssl="require")
    row = await conn.fetchrow("SELECT rescan_status FROM meetings WHERE id=$1", meeting_id)
    await conn.close()
    return row["rescan_status"] if row else None


# ─── FIX 1: pipeline sequencing (code inspection) ────────────────────────────

class TestFix1PipelineSequencing:
    def test_diarize_awaited_before_analyze(self):
        """The pipeline must AWAIT diarize_coro before invoking analyze_meeting()."""
        path = "/app/backend/utils/transcription_pipeline.py"
        with open(path) as f:
            src = f.read()
        # Locate diarize_coro creation, its await, and analyze_meeting call
        m_diarize = re.search(r"diarize_coro\s*=", src)
        m_await   = re.search(r"await\s+diarize_coro", src)
        m_analyze = re.search(r"analyze_meeting\(", src)
        assert m_diarize and m_await and m_analyze, "diarize_coro / await / analyze_meeting not all found"
        assert m_diarize.start() < m_await.start() < m_analyze.start(), \
            "diarize_coro must be awaited BEFORE analyze_meeting is called"

    def test_diarize_not_in_gather_with_analyze(self):
        """diarize_coro must NOT be passed into asyncio.gather() alongside analyze_meeting."""
        path = "/app/backend/utils/transcription_pipeline.py"
        with open(path) as f:
            src = f.read()
        # Find every asyncio.gather(...) call and its args block
        for m in re.finditer(r"asyncio\.gather\(([^)]*)\)", src, flags=re.DOTALL):
            args = m.group(1)
            if "diarize_coro" in args and "analyze_meeting" in args:
                pytest.fail("diarize_coro is still passed to asyncio.gather() with analyze_meeting")


# ─── FIX 2 & 3: rescan behaviour ─────────────────────────────────────────────

class TestFix2And3Rescan:
    """One end-to-end rescan flow that exercises both FIX 2 (unique ids) and
    FIX 3 (preserving reviewed items)."""

    def test_baseline_analysis_has_items(self):
        pre = asyncio.run(_db_read_analysis(ANALYSIS_ID))
        assert len(pre["cqc"]) > 0, "test meeting must have at least one cqc mapping to be useful"

    def test_rescan_preserves_accepted_and_generates_uuid_ids(self, admin_session):
        # 1. Snapshot pre-rescan state
        pre = asyncio.run(_db_read_analysis(ANALYSIS_ID))

        # 2. Pick a pending cqc item, accept it (or use an existing accepted one)
        target = next((x for x in pre["cqc"] if x.get("status") == "pending"), None)
        assert target, "need at least one pending cqc mapping"
        target_id = target["id"]
        target_ref = target.get("regulation_ref")

        r = admin_session.put(
            f"{BASE}/review/{MEETING_ID}/evidence/{target_id}",
            json={"status": "accepted"}, timeout=30,
        )
        assert r.status_code == 200, f"accept failed: {r.status_code} {r.text[:300]}"

        # 2b. Also record an already-accepted care_cert item (cc_5 in seed data) —
        # doubles the FIX 3 coverage without another PUT.
        pre_accepted_cc = [x for x in pre["cc"] if x.get("status") == "accepted"]

        # 3. Trigger rescan
        r = admin_session.post(f"{BASE}/review/{MEETING_ID}/rescan-evidence", json={}, timeout=30)
        assert r.status_code == 200, f"rescan trigger failed: {r.status_code} {r.text[:300]}"
        assert r.json().get("status") == "processing"

        # 4. Poll rescan_status until 'done' (or fail)
        deadline = time.time() + 240   # 4 min max
        final_status = None
        while time.time() < deadline:
            final_status = asyncio.run(_db_rescan_status(MEETING_ID))
            if final_status and final_status != "processing":
                break
            time.sleep(5)
        assert final_status == "done", f"rescan did not finish successfully, final rescan_status={final_status}"

        # 5. Read post-rescan analysis
        post = asyncio.run(_db_read_analysis(ANALYSIS_ID))

        # 5a. FIX 3 — the previously-accepted cqc item must still be present, same id, still accepted
        preserved = [x for x in post["cqc"] if x.get("id") == target_id]
        assert len(preserved) >= 1, (
            f"FIX 3 broken: accepted cqc item id={target_id} (ref={target_ref}) "
            f"was DROPPED after rescan"
        )
        assert preserved[0].get("status") == "accepted", (
            f"FIX 3 broken: preserved cqc item id={target_id} status changed to "
            f"{preserved[0].get('status')} (should stay 'accepted')"
        )

        # 5b. FIX 3 — every pre-rescan accepted care_cert item must still exist with same status
        for old in pre_accepted_cc:
            match = [x for x in post["cc"] if x.get("id") == old.get("id")]
            assert match, f"FIX 3 broken: accepted cc item id={old.get('id')} dropped after rescan"
            assert match[0].get("status") == "accepted"

        # 5c. FIX 2 — every FRESHLY-added cqc/cc/custom item (i.e. id not in pre-set)
        # must have the new uuid-style id "<prefix>_<12hex>".
        pre_cqc_ids    = {x.get("id") for x in pre["cqc"]}
        pre_cc_ids     = {x.get("id") for x in pre["cc"]}
        pre_custom_ids = {x.get("id") for x in pre["custom"]}

        new_cqc    = [x for x in post["cqc"]    if x.get("id") not in pre_cqc_ids]
        new_cc     = [x for x in post["cc"]     if x.get("id") not in pre_cc_ids]
        new_custom = [x for x in post["custom"] if x.get("id") not in pre_custom_ids]

        # Something must have been re-generated by the fresh scan.
        assert (len(new_cqc) + len(new_cc) + len(new_custom)) > 0, (
            "rescan produced zero new mappings — cannot verify FIX 2"
        )

        bad = [x["id"] for x in (new_cqc + new_cc + new_custom) if not UUID_ID_RE.match(x.get("id", ""))]
        assert not bad, f"FIX 2 broken: fresh mapping(s) have non-uuid ids: {bad[:10]}"

        # 5d. FIX 2 — uniqueness within each list of fresh items
        for label, items in (("cqc", new_cqc), ("cc", new_cc), ("custom", new_custom)):
            ids = [x.get("id") for x in items]
            assert len(ids) == len(set(ids)), f"FIX 2 broken: duplicate ids in fresh {label}: {ids}"

    def test_rescan_forbidden_for_attendee(self):
        """Sanity: role gate still works — attendee cannot rescan."""
        s = _login("user@supervision.com", "AnotherNew789!")
        r = s.post(f"{BASE}/review/{MEETING_ID}/rescan-evidence", json={}, timeout=30)
        # 403 (role check) OR 404 (meeting not visible) both acceptable, MUST NOT be 200.
        assert r.status_code in (403, 404), f"attendee unexpectedly allowed to rescan: {r.status_code}"
