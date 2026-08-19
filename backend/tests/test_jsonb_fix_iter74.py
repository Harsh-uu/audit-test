"""
Iteration 74 — Regression suite for the JSONB double-encoding fix + 'caseload' ban.

Covers (backend/API level):
  * review.py  : PUT actions / learning_needs / evidence, PATCH risks, PATCH action toggle,
                 POST mark-reviewed, POST signoff, POST share
  * admin.py   : PATCH team-insights registers (actions / learning_needs / achievements)
  * utils/ai.py: _apply_uk_language() 'caseload' ban
  * DB assert  : every touched jsonb column must have jsonb_typeof = array/object (never 'string')

Every write is followed by a fresh GET (persistence check) AND a direct jsonb_typeof
DB check, then original state is restored.
"""
import asyncio
import copy
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend")

FE = dotenv_values("/app/frontend/.env")
BE = dotenv_values("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or FE["REACT_APP_BACKEND_URL"]).rstrip("/") + "/api"
DSN = BE["DATABASE_URL"]

ORG = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"
MEETING = "c20802af-17e3-4210-b497-13d09c9e67ec"          # in_review, rich analysis
SIGNOFF_MEETING = "2f1cc088-0687-48b9-9f40-1dabb5285640"  # in_review, used for reviewed/signoff/share
SARAH = "53874ad3-8a98-4fab-8993-7c1b2d57a5b0"


# ── DB helpers ────────────────────────────────────────────────────────────────

def _db(coro_fn):
    async def runner():
        import asyncpg
        conn = await asyncpg.connect(DSN, ssl="require")
        try:
            return await coro_fn(conn)
        finally:
            await conn.close()
    return asyncio.get_event_loop().run_until_complete(runner()) if False else asyncio.run(runner())


def jsonb_typeof(table, col, row_id):
    async def q(conn):
        return await conn.fetchval(f"SELECT jsonb_typeof({col}) FROM {table} WHERE id=$1", row_id)
    return _db(q)


def fetch_row(table, row_id):
    async def q(conn):
        r = await conn.fetchrow(f"SELECT * FROM {table} WHERE id=$1", row_id)
        return dict(r) if r else None
    return _db(q)


def analysis_id_for(meeting_id):
    async def q(conn):
        return await conn.fetchval("SELECT analysis_id FROM meetings WHERE id=$1", meeting_id)
    return _db(q)


def jl(v):
    if isinstance(v, str):
        v = json.loads(v)
    return v or []


def restore_analysis_col(analysis_id, col, value):
    async def q(conn):
        await conn.execute(
            f"UPDATE analyses SET {col} = $1::jsonb WHERE id = $2", json.dumps(value), analysis_id
        )
    _db(q)


def restore_meeting(meeting_id, snapshot):
    async def q(conn):
        await conn.execute(
            """UPDATE meetings SET status=$1, attendees=$2::jsonb, shared_with=$3::jsonb,
               sign_off_record=$4::jsonb, audio_deletion_status=$5 WHERE id=$6""",
            snapshot["status"],
            json.dumps(jl(snapshot["attendees"])),
            json.dumps(jl(snapshot["shared_with"])),
            json.dumps(snapshot["sign_off_record"]) if snapshot["sign_off_record"] not in (None, "") else None,
            snapshot.get("audio_deletion_status"),
            meeting_id,
        )
    _db(q)


# ── auth fixture ──────────────────────────────────────────────────────────────

_SESSION_CACHE = {}


def _clear_rate_limits():
    async def q(conn):
        await conn.execute("DELETE FROM login_attempts")
    try:
        _db(q)
    except Exception:
        pass


def _session_for(email, password):
    if email in _SESSION_CACHE:
        return _SESSION_CACHE[email]
    _clear_rate_limits()
    out = subprocess.run(
        [sys.executable, "/app/backend/tests/get_tokens.py", email, password],
        capture_output=True, text=True, timeout=180,
    )
    payload = json.loads(out.stdout.strip().splitlines()[-1])
    if "cookies" not in payload:
        pytest.fail(f"Login failed for {email}: {payload}")
    s = requests.Session()
    for k, v in payload["cookies"].items():
        s.cookies.set(k, v)
    _SESSION_CACHE[email] = s
    return s


@pytest.fixture(scope="module")
def mgr():
    return _session_for("manager@supervision.com", "Manager123!")


@pytest.fixture(scope="module")
def aid():
    a = analysis_id_for(MEETING)
    assert a, "test meeting has no analysis"
    return a


def get_review(sess, meeting_id=MEETING):
    r = sess.get(f"{BASE}/review/{meeting_id}", timeout=60)
    assert r.status_code == 200, f"GET review failed {r.status_code}: {r.text[:300]}"
    return r.json()


# ── review.py: learning needs (the reported 'Failed to Save' bug) ─────────────

class TestLearningNeeds:
    def test_add_learning_need_persists_as_jsonb_array(self, mgr, aid):
        original = jl(fetch_row("analyses", aid)["learning_needs"])
        try:
            new_ln = {
                "id": "TEST_ln_iter74",
                "text": "TEST_ Complete moving & handling refresher",
                "assigned_to": "Demo User",
                "due_date": "2026-12-31",
                "completed": False,
                "source": "manual",
            }
            payload = {"learning_needs": copy.deepcopy(original) + [new_ln]}
            r = mgr.put(f"{BASE}/review/{MEETING}/learning_needs", json=payload, timeout=60)
            assert r.status_code == 200, f"PUT learning_needs -> {r.status_code}: {r.text[:400]}"

            # DB: must be a jsonb array, NOT a double-encoded string
            assert jsonb_typeof("analyses", "learning_needs", aid) == "array"

            # Persistence via fresh GET (what the UI does after refresh)
            data = get_review(mgr)
            lns = jl(data.get("analysis", {}).get("learning_needs"))
            assert isinstance(lns, list) and len(lns) == len(original) + 1
            found = [l for l in lns if l.get("id") == "TEST_ln_iter74"]
            assert found, f"new learning need not returned by GET: {lns}"
            assert found[0]["text"] == new_ln["text"]
            assert found[0]["completed"] is False
        finally:
            restore_analysis_col(aid, "learning_needs", original)

    def test_toggle_learning_need_via_team_insights(self, mgr, aid):
        original = jl(fetch_row("analyses", aid)["learning_needs"])
        assert original, "no learning need to toggle"
        ln_id = original[0].get("id")
        try:
            r = mgr.patch(
                f"{BASE}/admin/team-insights/learning_needs/{MEETING}/{ln_id}",
                json={"completed": True}, timeout=60,
            )
            assert r.status_code == 200, f"PATCH register LN -> {r.status_code}: {r.text[:400]}"
            assert r.json().get("completed") is True
            assert jsonb_typeof("analyses", "learning_needs", aid) == "array"

            lns = jl(get_review(mgr).get("analysis", {}).get("learning_needs"))
            target = [l for l in lns if l.get("id") == ln_id]
            assert target and target[0]["completed"] is True

            # toggle back off
            r2 = mgr.patch(
                f"{BASE}/admin/team-insights/learning_needs/{MEETING}/{ln_id}",
                json={"completed": False}, timeout=60,
            )
            assert r2.status_code == 200
            lns = jl(get_review(mgr).get("analysis", {}).get("learning_needs"))
            assert [l for l in lns if l.get("id") == ln_id][0]["completed"] is False
        finally:
            restore_analysis_col(aid, "learning_needs", original)


# ── review.py: actions ────────────────────────────────────────────────────────

class TestActions:
    def test_add_and_remove_action(self, mgr, aid):
        original = jl(fetch_row("analyses", aid)["actions"])
        try:
            new_action = {"id": "TEST_action_iter74", "text": "TEST_ Book supervision follow-up",
                          "assigned_to": "Demo User", "due_date": "2026-12-31", "completed": False}
            r = mgr.put(f"{BASE}/review/{MEETING}/actions",
                        json={"actions": copy.deepcopy(original) + [new_action]}, timeout=60)
            assert r.status_code == 200, f"PUT actions -> {r.status_code}: {r.text[:400]}"
            assert jsonb_typeof("analyses", "actions", aid) == "array"
            acts = jl(get_review(mgr).get("analysis", {}).get("actions"))
            assert any(a.get("id") == "TEST_action_iter74" for a in acts)

            # remove it again
            r = mgr.put(f"{BASE}/review/{MEETING}/actions",
                        json={"actions": copy.deepcopy(original)}, timeout=60)
            assert r.status_code == 200
            acts = jl(get_review(mgr).get("analysis", {}).get("actions"))
            assert not any(a.get("id") == "TEST_action_iter74" for a in acts)
            assert jsonb_typeof("analyses", "actions", aid) == "array"
        finally:
            restore_analysis_col(aid, "actions", original)

    def test_toggle_action_on_report(self, mgr, aid):
        original = jl(fetch_row("analyses", aid)["actions"])
        action_id = original[0]["id"]
        try:
            r = mgr.patch(f"{BASE}/review/{MEETING}/actions/{action_id}",
                          json={"completed": True}, timeout=60)
            assert r.status_code == 200, f"PATCH action -> {r.status_code}: {r.text[:400]}"
            assert jsonb_typeof("analyses", "actions", aid) == "array"
            acts = jl(get_review(mgr).get("analysis", {}).get("actions"))
            assert [a for a in acts if a["id"] == action_id][0]["completed"] is True
        finally:
            restore_analysis_col(aid, "actions", original)

    def test_toggle_action_via_team_insights(self, mgr, aid):
        original = jl(fetch_row("analyses", aid)["actions"])
        action_id = original[0]["id"]
        try:
            r = mgr.patch(f"{BASE}/admin/team-insights/actions/{MEETING}/{action_id}",
                          json={"completed": True}, timeout=60)
            assert r.status_code == 200, f"PATCH register action -> {r.status_code}: {r.text[:400]}"
            assert jsonb_typeof("analyses", "actions", aid) == "array"
            acts = jl(get_review(mgr).get("analysis", {}).get("actions"))
            assert [a for a in acts if a["id"] == action_id][0]["completed"] is True
        finally:
            restore_analysis_col(aid, "actions", original)


# ── review.py: risks ──────────────────────────────────────────────────────────

class TestRisks:
    def test_update_risk_resolve_and_notes(self, mgr, aid):
        original = jl(fetch_row("analyses", aid)["risks"])
        risk_id = original[0]["id"]
        try:
            r = mgr.patch(f"{BASE}/review/{MEETING}/risks/{risk_id}",
                          json={"is_resolved": True, "notes": "TEST_ mitigated iter74"}, timeout=60)
            assert r.status_code == 200, f"PATCH risk -> {r.status_code}: {r.text[:400]}"
            assert jsonb_typeof("analyses", "risks", aid) == "array"
            risks = jl(get_review(mgr).get("analysis", {}).get("risks"))
            target = [x for x in risks if x["id"] == risk_id][0]
            assert target.get("is_resolved") is True
            assert target.get("notes") == "TEST_ mitigated iter74"
        finally:
            restore_analysis_col(aid, "risks", original)


# ── review.py: evidence mappings ──────────────────────────────────────────────

class TestEvidenceMappings:
    @pytest.mark.parametrize("col", ["cqc_mappings", "care_cert_mappings"])
    def test_update_mapping(self, mgr, aid, col):
        original = jl(fetch_row("analyses", aid)[col])
        if not original:
            pytest.skip(f"no {col} on test analysis")
        ev_id = original[0]["id"]
        try:
            r = mgr.put(f"{BASE}/review/{MEETING}/evidence/{ev_id}",
                        json={"status": "confirmed", "notes": "TEST_ note iter74",
                              "edited_evidence_summary": "TEST_ edited summary iter74"}, timeout=60)
            assert r.status_code == 200, f"PUT evidence -> {r.status_code}: {r.text[:400]}"
            assert jsonb_typeof("analyses", col, aid) == "array"
            maps = jl(get_review(mgr).get("analysis", {}).get(col))
            target = [m for m in maps if m["id"] == ev_id][0]
            assert target["status"] == "confirmed"
            assert target["notes"] == "TEST_ note iter74"
            assert target["edited_evidence_summary"] == "TEST_ edited summary iter74"
        finally:
            restore_analysis_col(aid, col, original)


# ── review.py: achievements register toggle ───────────────────────────────────

class TestAchievements:
    def test_toggle_achievement_via_team_insights(self, mgr, aid):
        original = jl(fetch_row("analyses", aid)["achievements"])
        if not original:
            pytest.skip("no achievements")
        ach_id = original[0]["id"]
        try:
            r = mgr.patch(f"{BASE}/admin/team-insights/achievements/{MEETING}/{ach_id}",
                          json={"acknowledged": True}, timeout=60)
            assert r.status_code == 200, f"PATCH register achievement -> {r.status_code}: {r.text[:400]}"
            assert jsonb_typeof("analyses", "achievements", aid) == "array"
            achs = jl(get_review(mgr).get("analysis", {}).get("achievements"))
            assert [a for a in achs if a["id"] == ach_id][0].get("acknowledged") is True
        finally:
            restore_analysis_col(aid, "achievements", original)


# ── review.py: mark-reviewed → signoff → share (meetings jsonb columns) ───────

class TestReviewLifecycle:
    def test_mark_reviewed_signoff_share(self, mgr):
        snapshot = fetch_row("meetings", SIGNOFF_MEETING)
        assert snapshot
        try:
            # 1. mark-reviewed (attendees jsonb write)
            r = mgr.post(f"{BASE}/review/{SIGNOFF_MEETING}/mark-reviewed", timeout=60)
            assert r.status_code == 200, f"mark-reviewed -> {r.status_code}: {r.text[:400]}"
            assert jsonb_typeof("meetings", "attendees", SIGNOFF_MEETING) == "array"
            att = jl(fetch_row("meetings", SIGNOFF_MEETING)["attendees"])
            mine = [a for a in att if a.get("email") == "manager@supervision.com"]
            assert mine and mine[0]["reviewed"] is True

            # force all attendees reviewed so sign-off is permitted
            async def q(conn):
                rows = await conn.fetchval("SELECT attendees FROM meetings WHERE id=$1", SIGNOFF_MEETING)
                lst = jl(rows)
                for a in lst:
                    a["reviewed"] = True
                    a["reviewed_at"] = datetime.now(timezone.utc).isoformat()
                await conn.execute(
                    "UPDATE meetings SET attendees=$1::jsonb, status='reviewed' WHERE id=$2",
                    json.dumps(lst), SIGNOFF_MEETING)
            _db(q)

            # 2. signoff (sign_off_record jsonb write)
            r = mgr.post(f"{BASE}/review/{SIGNOFF_MEETING}/signoff", timeout=60)
            assert r.status_code == 200, f"signoff -> {r.status_code}: {r.text[:400]}"
            assert jsonb_typeof("meetings", "sign_off_record", SIGNOFF_MEETING) == "object"
            rec = fetch_row("meetings", SIGNOFF_MEETING)["sign_off_record"]
            rec = json.loads(rec) if isinstance(rec, str) else rec
            assert rec.get("signed_by_name")

            # 3. share (shared_with jsonb write)
            r = mgr.post(f"{BASE}/review/{SIGNOFF_MEETING}/share",
                         json={"user_ids": [SARAH]}, timeout=60)
            assert r.status_code == 200, f"share -> {r.status_code}: {r.text[:400]}"
            assert jsonb_typeof("meetings", "shared_with", SIGNOFF_MEETING) == "array"
            sw = jl(fetch_row("meetings", SIGNOFF_MEETING)["shared_with"])
            assert any(s.get("user_id") == SARAH for s in sw), sw
        finally:
            restore_meeting(SIGNOFF_MEETING, snapshot)


# ── utils/ai.py: 'caseload' ban ───────────────────────────────────────────────

class TestCaseloadBan:
    def test_apply_uk_language_replaces_caseload(self):
        from utils.ai import _apply_uk_language
        out = _apply_uk_language("Discussed her caseload and Caseload pressures. CASELOAD is high.")
        assert "caseload" not in out.lower(), out
        assert "workload" in out.lower() or "people we support" in out.lower()

    def test_caseload_banned_in_system_prompts(self):
        import utils.ai as ai
        for name in ["ANALYSIS_SYSTEM_PROMPT", "DOC_EVIDENCE_SYSTEM_PROMPT", "SUMMARY_ONLY_PROMPT"]:
            prompt = getattr(ai, name, None)
            assert prompt, f"{name} missing"
            assert "caseload" in prompt.lower(), f"{name} has no caseload ban instruction"

    def test_no_caseload_in_stored_analyses(self):
        async def q(conn):
            return await conn.fetch(
                """SELECT id FROM analyses
                   WHERE summary ILIKE '%caseload%'
                      OR actions::text ILIKE '%caseload%'
                      OR risks::text ILIKE '%caseload%'
                      OR learning_needs::text ILIKE '%caseload%'
                      OR achievements::text ILIKE '%caseload%'
                      OR cqc_mappings::text ILIKE '%caseload%'"""
            )
        rows = _db(q)
        assert not rows, f"'caseload' present in {len(rows)} stored analyses (pre-existing rows): {[r['id'] for r in rows]}"


# ── Global data-integrity sweep: no double-encoded jsonb anywhere ─────────────

class TestNoDoubleEncodedJsonb:
    CHECKS = [
        ("analyses", ["actions", "risks", "cqc_mappings", "care_cert_mappings",
                      "custom_mappings", "achievements", "learning_needs"]),
        ("meetings", ["attendees", "shared_with", "pii_redactions",
                      "recording_events", "paused_periods", "sign_off_record"]),
        ("transcripts", ["speaker_colors"]),
        ("organisations", ["branding"]),
        ("standards_entries", ["keywords"]),
    ]

    @pytest.mark.parametrize("table,cols", CHECKS)
    def test_no_string_typed_jsonb(self, table, cols):
        async def q(conn):
            bad = {}
            for c in cols:
                n = await conn.fetchval(
                    f"SELECT count(*) FROM {table} WHERE {c} IS NOT NULL AND jsonb_typeof({c})='string'")
                if n:
                    bad[c] = n
            return bad
        bad = _db(q)
        assert not bad, f"{table}: double-encoded jsonb rows -> {bad}"


# ── review.py: speaker-text (transcripts.speaker_colors jsonb) ────────────────

class TestSpeakerText:
    def test_update_speaker_colors(self, mgr):
        def get_t(fn):
            return _db(fn)
        tid = get_t(lambda c: c.fetchval("SELECT transcript_id FROM meetings WHERE id=$1", MEETING))
        if not tid:
            pytest.skip("no transcript on test meeting")
        row = fetch_row("transcripts", tid)
        prev_text = row["speaker_text"]
        prev_colors = row["speaker_colors"]
        if not prev_text:
            pytest.skip("no speaker_text on transcript")
        try:
            r = mgr.patch(f"{BASE}/review/{MEETING}/speaker-text",
                          json={"speaker_text": prev_text,
                                "speaker_colors": {"Demo Manager": "#ff0000", "Demo User": "#00ff00"}},
                          timeout=90)
            assert r.status_code == 200, f"PATCH speaker-text -> {r.status_code}: {r.text[:400]}"
            assert jsonb_typeof("transcripts", "speaker_colors", tid) == "object"
            colors = fetch_row("transcripts", tid)["speaker_colors"]
            colors = json.loads(colors) if isinstance(colors, str) else colors
            assert colors.get("Demo Manager") == "#ff0000"
        finally:
            async def restore(c):
                await c.execute("UPDATE transcripts SET speaker_text=$1, speaker_colors=$2::jsonb WHERE id=$3",
                                prev_text,
                                json.dumps(json.loads(prev_colors) if isinstance(prev_colors, str) else prev_colors)
                                if prev_colors is not None else None,
                                tid)
            _db(restore)


# ── review.py: AI risk suggestions (writes risks jsonb) ──────────────────────

class TestRiskSuggestions:
    def test_risk_suggestions_writes_valid_jsonb(self, mgr, aid):
        original = jl(fetch_row("analyses", aid)["risks"])
        risk_id = original[-1]["id"]
        try:
            r = mgr.post(f"{BASE}/review/{MEETING}/risks/{risk_id}/suggestions", timeout=240)
            assert r.status_code == 200, f"risk suggestions -> {r.status_code}: {r.text[:400]}"
            body = r.json()
            assert "suggested_resolutions" in body
            assert jsonb_typeof("analyses", "risks", aid) == "array"
            assert "caseload" not in json.dumps(body).lower()
        finally:
            restore_analysis_col(aid, "risks", original)
