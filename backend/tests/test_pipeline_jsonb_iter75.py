"""
Iteration 75 — processing.py AI-analysis pipeline JSONB soundness.

Runs the REAL `run_transcription_and_analysis()` coroutine in-process against the
real database, with only the external AI/storage calls stubbed (AssemblyAI,
analyze_meeting, diarization, summariser, prep-coverage). Every SQL statement /
JSONB bind in processing.py executes unmodified, so this proves the write paths
(transcripts.safety_warnings, analyses.actions/risks/cqc_mappings/
care_cert_mappings/custom_mappings/achievements/learning_needs,
meeting_prep.coverage_results) store real JSONB arrays/objects.

Asserted IMMEDIATELY after processing (no backend restart), so the startup
repair migration cannot mask a live write bug.
"""
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone

import pytest
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend")
for k, v in dotenv_values("/app/backend/.env").items():
    os.environ.setdefault(k, v)

ORG = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"
ADMIN_ID = "f72ac550-e6b8-4ffc-b2da-46a54a4c06d5"

ANALYSIS = {
    "summary": "TEST_ITER75 summary",
    "actions": [{"description": "TEST action", "assigned_to": "Test Admin", "due_date": None}],
    "risks": [{"description": "TEST risk", "severity": "low"}],
    "cqc_mappings": [{"regulation_ref": "9", "evidence_summary": "TEST evidence"}],
    "care_cert_mappings": [{"standard_ref": "1", "evidence_summary": "TEST evidence"}],
    "custom_mappings": [{"criterion_ref": "1.1", "evidence_summary": "TEST evidence"}],
    "achievements": [{"description": "TEST achievement"}],
    "learning_needs": [{"description": "TEST learning need"}],
}
SAFETY_WARNINGS = [{"type": "low_confidence", "detail": "TEST warning"}]
COVERAGE = {"results": {"q1": {"covered": True, "evidence": "TEST"}},
            "checked_at": datetime.now(timezone.utc).isoformat()}


def _run(coro_fn):
    async def main():
        import database
        await database.create_pool()
        try:
            return await coro_fn(database)
        finally:
            await database.close_pool()
    return asyncio.run(main())


@pytest.fixture(scope="module")
def pipeline_result():
    """Create meeting + prep, run the pipeline, capture DB state, then clean up."""
    import routers.processing as proc
    from utils import ai as ai_mod

    mid = str(uuid.uuid4())
    prep_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    async def _do(database):
        async with database.with_admin() as conn:
            await conn.execute(
                """INSERT INTO meetings (id, org_id, title, date, meeting_type, created_by,
                       created_by_name, attendees, status, created_at, updated_at)
                   VALUES ($1,$2,$3,$4,'supervision',$5,'Test Admin',$6::jsonb,'uploaded',$7,$7)""",
                mid, ORG, "TEST_ITER75 pipeline meeting", now[:10], ADMIN_ID,
                [{"user_id": ADMIN_ID, "name": "Test Admin", "email": "admin@supervision.com",
                  "role": "admin", "present": True}], now)
            await conn.execute(
                """INSERT INTO meeting_prep (id, meeting_id, org_id, sections, coverage_results,
                       included_source_ids, created_at, updated_at)
                   VALUES ($1,$2,$3,$4::jsonb,'{}'::jsonb,'[]'::jsonb,$5,$5)""",
                prep_id, mid, ORG,
                [{"title": "TEST section",
                  "questions": [{"id": "q1", "text": "How is your workload?", "included": True}]}],
                now)

        # ── stub external calls only ──
        proc.get_audio = lambda path: asyncio.sleep(0, result=(b"FAKEAUDIO", "audio/wav"))

        async def fake_transcribe(audio_data, speakers_expected=None):
            return ("TEST transcript text", "Speaker 1: hello", "[00:00] Speaker 1: hello", SAFETY_WARNINGS)
        proc.transcribe_with_assemblyai = fake_transcribe

        async def fake_analyze(*a, **kw):
            return json.loads(json.dumps(ANALYSIS))
        proc.analyze_meeting = fake_analyze

        async def fake_map(*a, **kw):
            return "Test Admin: hello"
        proc.map_speaker_numbers_to_names = fake_map
        proc.diarize_transcript = fake_map

        async def fake_summary(*a, **kw):
            return "TEST dedicated summary"
        proc.generate_meeting_summary = fake_summary

        async def fake_coverage(*a, **kw):
            return COVERAGE
        ai_mod.check_prep_coverage = fake_coverage

        os.environ["ASSEMBLYAI_API_KEY"] = os.environ.get("ASSEMBLYAI_API_KEY") or "TEST"

        await proc.run_transcription_and_analysis(mid, "audio/TEST_ITER75.wav")

        async with database.with_admin() as conn:
            m = await conn.fetchrow(
                "SELECT status, processing_error, analysis_id, transcript_id FROM meetings WHERE id=$1", mid)
            a = await conn.fetchrow(
                """SELECT jsonb_typeof(actions) actions, jsonb_typeof(risks) risks,
                          jsonb_typeof(cqc_mappings) cqc_mappings,
                          jsonb_typeof(care_cert_mappings) care_cert_mappings,
                          jsonb_typeof(custom_mappings) custom_mappings,
                          jsonb_typeof(achievements) achievements,
                          jsonb_typeof(learning_needs) learning_needs,
                          actions AS actions_v, summary
                     FROM analyses WHERE meeting_id=$1""", mid)
            t = await conn.fetchrow(
                "SELECT jsonb_typeof(safety_warnings) sw, safety_warnings AS sw_v, speaker_text "
                "FROM transcripts WHERE meeting_id=$1", mid)
            p = await conn.fetchrow(
                "SELECT jsonb_typeof(coverage_results) cr, coverage_results AS cr_v "
                "FROM meeting_prep WHERE meeting_id=$1", mid)
        return {"meeting": dict(m), "analysis": dict(a) if a else None,
                "transcript": dict(t) if t else None, "prep": dict(p) if p else None}

    result = _run(_do)

    async def _cleanup(database):
        async with database.with_admin() as conn:
            await conn.execute("DELETE FROM analyses WHERE meeting_id=$1", mid)
            await conn.execute("DELETE FROM transcripts WHERE meeting_id=$1", mid)
            await conn.execute("DELETE FROM meeting_prep WHERE meeting_id=$1", mid)
            await conn.execute("DELETE FROM audit_logs WHERE meeting_id=$1", mid)
            await conn.execute("DELETE FROM meetings WHERE id=$1", mid)
    yield result
    _run(_cleanup)


def test_pipeline_completes(pipeline_result):
    m = pipeline_result["meeting"]
    assert m["status"] == "in_review", f"status={m['status']!r} error={m['processing_error']!r}"
    assert m["analysis_id"] and m["transcript_id"]


@pytest.mark.parametrize("col", ["actions", "risks", "cqc_mappings", "care_cert_mappings",
                                 "custom_mappings", "achievements", "learning_needs"])
def test_analyses_columns_are_arrays(pipeline_result, col):
    a = pipeline_result["analysis"]
    assert a is not None, "no analyses row written"
    assert a[col] == "array", f"analyses.{col} jsonb_typeof={a[col]!r} (double-encoded)"


def test_analyses_action_elements_are_objects(pipeline_result):
    v = pipeline_result["analysis"]["actions_v"]
    v = json.loads(v) if isinstance(v, str) else v
    assert v and all(isinstance(e, dict) for e in v), v
    assert v[0]["description"] == "TEST action"
    assert v[0].get("id", "").startswith("action_")


def test_transcript_safety_warnings_is_array(pipeline_result):
    t = pipeline_result["transcript"]
    assert t is not None, "no transcripts row written"
    assert t["sw"] == "array", f"transcripts.safety_warnings jsonb_typeof={t['sw']!r}"
    v = json.loads(t["sw_v"]) if isinstance(t["sw_v"], str) else t["sw_v"]
    assert all(isinstance(e, dict) for e in v), v
    assert v[0]["type"] == "low_confidence"


def test_prep_coverage_results_is_object(pipeline_result):
    p = pipeline_result["prep"]
    assert p is not None, "no meeting_prep row"
    assert p["cr"] == "object", f"meeting_prep.coverage_results jsonb_typeof={p['cr']!r}"
    v = json.loads(p["cr_v"]) if isinstance(p["cr_v"], str) else p["cr_v"]
    assert v.get("q1", {}).get("covered") is True, v


def test_summary_uses_dedicated_summariser(pipeline_result):
    assert pipeline_result["analysis"]["summary"] == "TEST dedicated summary"
