"""
Iteration 81 — Vertex AI (Gemini 2.5 Flash) primary / OpenAI fallback routing.

Covers utils/ai.py:
  - _get_vertex_client()  : client builds from GCP_* env vars
  - _gemini_chat()        : live Vertex AI call in europe-west2
  - _ai_chat()            : Gemini-first, OpenAI fallback on ANY exception
  - analyze_meeting()     : full analysis JSON structure via the new wrapper
  - secondary AI features : PII scan, summary regen, prep coverage, risk suggestions,
                            document criteria extraction, doc evidence scan
"""
import os
import sys
import json
import asyncio
import time
import logging

import pytest
from dotenv import load_dotenv

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")

from utils import ai as aimod  # noqa: E402


TRANSCRIPT = """Manager: Morning Sarah, thanks for coming in. How have things been on shift this week?
Sarah: Honestly a bit full on. I'm shattered, to be fair. We've been two down on the early shift.
Manager: That sounds tough. Anything specific you want to raise?
Sarah: Well, there was one thing. Mrs Patel's nephew was going through her bedside drawer on Tuesday. I didn't say anything to be honest, none of us really do, it's kind of just normal now.
Manager: Right. And did you record that anywhere?
Sarah: No. I probably should have. It seemed minor at the time.
Manager: OK, we'll need to come back to that. How about the medication round?
Sarah: Fine. I always know what to do with meds, never had a problem.
Manager: And your training — you mentioned last time you weren't confident about the Mental Capacity Act?
Sarah: Yeah, I still find capacity assessments hard. I asked Mrs Jones first before helping her dress because she can decide that for herself, but the formal side I don't get.
Manager: I noticed you handled Mr Doyle's distress really well on Friday — you stayed calm and gave him space.
Sarah: Thanks. I'm fine really, just tired. Things at home are a bit difficult at the moment but it hasn't affected me so far.
"""

CQC_STDS = [
    {"reference": "Regulation 13", "name": "Safeguarding service users from abuse and improper treatment",
     "description": "Service users must be protected from abuse and improper treatment."},
    {"reference": "Regulation 18", "name": "Staffing",
     "description": "Sufficient numbers of suitably qualified, competent, skilled staff must be deployed."},
    {"reference": "Regulation 17", "name": "Good governance",
     "description": "Accurate, complete and contemporaneous records must be maintained."},
    {"reference": "QS Safe 3", "name": "Safeguarding",
     "description": "People are protected from abuse and neglect."},
]
CC_STDS = [
    {"reference": "Standard 2", "name": "Your personal development",
     "sub_outcomes": [
         {"ref": "2.1a", "desc": "Describe the processes for identifying own learning needs"},
         {"ref": "2.2h", "desc": "Agree a personal development plan with the appropriate people"},
     ]},
    {"reference": "Standard 10", "name": "Safeguarding adults",
     "sub_outcomes": [
         {"ref": "10.1a", "desc": "Explain the term safeguarding adults"},
         {"ref": "10.3a", "desc": "Describe how to raise and report a safeguarding concern"},
     ]},
    {"reference": "Standard 9", "name": "Awareness of mental health, dementia and learning disability",
     "sub_outcomes": [
         {"ref": "9.4a", "desc": "Explain the meaning of the term capacity"},
     ]},
]


# ── 1. Vertex client / config ────────────────────────────────────────────────
class TestVertexConfig:
    def test_gcp_env_vars_present(self):
        for key in ("GCP_PROJECT_ID", "GCP_LOCATION", "GCP_SERVICE_ACCOUNT_JSON"):
            assert os.environ.get(key), f"{key} missing from backend/.env"
        assert os.environ["GCP_LOCATION"] == "europe-west2"
        sa = json.loads(os.environ["GCP_SERVICE_ACCOUNT_JSON"])
        assert sa.get("type") == "service_account"
        assert sa.get("project_id") == os.environ["GCP_PROJECT_ID"]

    def test_vertex_client_builds(self):
        aimod._vertex_client = None
        aimod._vertex_client_failed_at = None
        client = aimod._get_vertex_client()
        assert client is not None, "Vertex client failed to build - see logs"

    def test_model_is_gemini_25_flash(self):
        assert aimod.GEMINI_MODEL == "gemini-2.5-flash"


# ── 2. Live Gemini + fallback routing ───────────────────────────────────────
class TestAiChatRouting:
    def test_gemini_chat_live(self):
        out = asyncio.run(aimod._gemini_chat(
            "You are a terse assistant. Reply with a single word.",
            "Reply with the single word: VERTEXOK", timeout_secs=120))
        assert isinstance(out, str) and out.strip(), "Gemini returned empty text"
        assert "VERTEXOK" in out.upper()

    def test_ai_chat_uses_gemini_no_fallback(self, caplog):
        calls = {"openai": 0}
        orig = aimod._openai_chat

        async def spy(*a, **k):
            calls["openai"] += 1
            return await orig(*a, **k)

        aimod._openai_chat = spy
        try:
            with caplog.at_level(logging.WARNING, logger="utils.ai"):
                out = asyncio.run(aimod._ai_chat("gpt-4o", "Be terse.",
                                                 "Reply with the single word: PRIMARY"))
            assert "PRIMARY" in out.upper()
            assert calls["openai"] == 0, "OpenAI was called even though Gemini should have succeeded"
            assert "[Vertex AI]" not in caplog.text
        finally:
            aimod._openai_chat = orig

    def test_ai_chat_falls_back_to_openai_on_vertex_failure(self, caplog):
        """Force a Vertex failure -> must transparently return an OpenAI result."""
        orig_sync = aimod._vertex_generate_sync

        def boom(system, user, reasoning_effort=None):
            raise RuntimeError("SIMULATED vertex outage")

        aimod._vertex_generate_sync = boom
        try:
            with caplog.at_level(logging.WARNING, logger="utils.ai"):
                out = asyncio.run(aimod._ai_chat("gpt-4o", "Be terse.",
                                                 "Reply with the single word: FALLBACK"))
            assert "FALLBACK" in out.upper(), f"unexpected fallback output: {out!r}"
            assert "SIMULATED vertex outage" in caplog.text
            assert "falling back to OpenAI" in caplog.text
        finally:
            aimod._vertex_generate_sync = orig_sync

    def test_ai_chat_raises_only_if_both_providers_fail(self):
        """Sanity: error surfaces only when BOTH providers fail (no silent empty string)."""
        orig_sync, orig_openai = aimod._vertex_generate_sync, aimod._openai_chat

        def boom(system, user, reasoning_effort=None):
            raise RuntimeError("SIMULATED vertex outage")

        async def boom_oai(*a, **k):
            raise RuntimeError("SIMULATED openai outage")

        aimod._vertex_generate_sync = boom
        aimod._openai_chat = boom_oai
        try:
            with pytest.raises(RuntimeError):
                asyncio.run(aimod._ai_chat("gpt-4o", "x", "y"))
        finally:
            aimod._vertex_generate_sync = orig_sync
            aimod._openai_chat = orig_openai


# ── 3. Main meeting analysis through the wrapper ─────────────────────────────
@pytest.fixture(scope="module")
def analysis():
    return asyncio.run(aimod.analyze_meeting(
        transcript_text=TRANSCRIPT,
        cqc_standards=CQC_STDS,
        care_cert_standards=CC_STDS,
        paused_periods=[],
    ))


class TestAnalyzeMeeting:
    def test_json_parsed_not_fallback_error(self, analysis):
        assert isinstance(analysis, dict)
        assert "could not be parsed" not in analysis.get("summary", ""), \
            "JSON parsing of the Gemini response FAILED (parser fallback returned)"

    def test_all_required_keys_present(self, analysis):
        for key in ("summary", "actions", "learning_needs", "risks",
                    "cqc_mappings", "care_cert_mappings", "custom_mappings"):
            assert key in analysis, f"missing key: {key}"
        for key in ("actions", "learning_needs", "risks", "cqc_mappings",
                    "care_cert_mappings", "custom_mappings"):
            assert isinstance(analysis[key], list), f"{key} is not a list"
        assert isinstance(analysis["summary"], str) and len(analysis["summary"]) > 50

    def test_achievements_present(self, analysis):
        assert "achievements" in analysis, "achievements key missing from analysis"
        assert isinstance(analysis["achievements"], list)

    def test_risks_structure_and_content(self, analysis):
        risks = analysis["risks"]
        assert len(risks) >= 2, f"expected multiple risks from this transcript, got {len(risks)}"
        for r in risks:
            assert r.get("id"), "risk missing id"
            assert r.get("text"), "risk missing text"
            assert r.get("severity") in ("high", "medium", "low"), f"bad severity: {r.get('severity')}"
            assert isinstance(r.get("suggested_resolutions", []), list)
        blob = json.dumps(risks).lower()
        assert "safeguard" in blob, "safeguarding boundary-violation risk (nephew in drawer) not detected"

    def test_mappings_structure(self, analysis):
        assert len(analysis["cqc_mappings"]) >= 1, "no CQC mappings produced"
        for m in analysis["cqc_mappings"]:
            assert m.get("regulation_ref") and m.get("evidence_summary")
            assert m.get("confidence") in ("likely_evidence", "possible_evidence")
        for m in analysis["care_cert_mappings"]:
            assert m.get("standard_ref") and m.get("outcome_ref")
            assert m.get("confidence") in ("likely_evidence", "possible_evidence")

    def test_learning_needs_detected(self, analysis):
        assert len(analysis["learning_needs"]) >= 1, "MCA/capacity learning need not detected"

    def test_analysis_served_by_gemini_without_openai_fallback(self):
        """Disable OpenAI entirely: analysis must still complete purely on Vertex AI."""
        orig = aimod._openai_chat

        async def blocked(*a, **k):
            raise AssertionError("OpenAI fallback was used - Gemini did not serve the analysis")

        aimod._openai_chat = blocked
        try:
            res = asyncio.run(aimod.analyze_meeting(
                transcript_text=TRANSCRIPT, cqc_standards=CQC_STDS,
                care_cert_standards=CC_STDS, paused_periods=[]))
        finally:
            aimod._openai_chat = orig
        assert "could not be parsed" not in res.get("summary", "")
        assert res["risks"] and res["cqc_mappings"]

    def test_uk_language_sanitiser_applied(self, analysis):
        blob = json.dumps(analysis).lower()
        for banned in ("pastoral", "caseload"):
            assert banned not in blob, f"banned US/inappropriate term present: {banned}"


# ── 4. Secondary AI features through the wrapper ─────────────────────────────
class TestSecondaryAiFeatures:
    def test_pii_scan(self):
        flags = asyncio.run(aimod.scan_pii_in_transcript(
            TRANSCRIPT + "\nSarah: You can reach her daughter Emily Patel on 07700900123.",
            attendees=["Sarah"], manager_name="Manager"))
        assert isinstance(flags, list)
        assert len(flags) >= 1, "PII scan returned nothing (expected phone + third-party names)"
        assert all(f.get("id") and f.get("original") for f in flags)
        blob = json.dumps(flags)
        assert "07700900123" in blob, "UK phone number not flagged"

    def test_regenerate_summary(self):
        out = asyncio.run(aimod.generate_meeting_summary(TRANSCRIPT))
        assert isinstance(out, str) and len(out) > 80
        assert "pastoral" not in out.lower()

    def test_prep_coverage_check(self):
        questions = [
            {"id": "q1", "text": "How are you finding your workload this month?"},
            {"id": "q2", "text": "Do you have any safeguarding concerns to raise?"},
            {"id": "q3", "text": "How is your knowledge of the Mental Capacity Act?"},
            {"id": "q4", "text": "Have you completed your fire safety training?"},
        ]
        res = asyncio.run(aimod.check_prep_coverage(TRANSCRIPT, questions))
        assert isinstance(res, dict), f"unexpected type {type(res)}"
        assert res.get("checked_at"), "checked_at is None -> AI call/JSON parse FAILED (silent default)"
        results = res.get("results") or {}
        assert len(results) == 4, f"expected coverage for all 4 questions, got {results}"
        for qid, r in results.items():
            assert r.get("status") in ("covered", "partial", "missed"), f"bad status for {qid}: {r}"
        assert results["q4"]["status"] == "missed", f"fire-safety question should be missed: {results['q4']}"

    def test_risk_suggestions(self):
        res = asyncio.run(aimod.generate_risk_suggestions(
            "Visitor observed going through service user's bedside drawer, not reported",
            "high", TRANSCRIPT))
        assert isinstance(res, dict)
        assert res.get("suggested_resolutions"), "no resolutions -> AI call/JSON parse FAILED (silent default)"
        assert len(res["suggested_resolutions"]) >= 2
        assert res.get("transcript_excerpt"), "no transcript excerpt located"

    def test_extract_document_criteria(self):
        doc = ("Company Values Policy\n"
               "1. Compassion - we treat every person with kindness and empathy.\n"
               "2. Dignity - we respect privacy and personal choice at all times.\n"
               "3. Accountability - we record accurately and escalate concerns promptly.\n"
               "4. Learning - we reflect on practice and seek development.\n")
        res = asyncio.run(aimod.extract_document_criteria(doc, "Company Values Policy"))
        assert isinstance(res, dict)
        assert res.get("criteria"), "no criteria extracted"
        assert 3 <= len(res["criteria"]) <= 20
        for c in res["criteria"]:
            assert c.get("ref") and c.get("name")


    def test_doc_evidence_scan(self):
        doc = ("Supervision Record - 12/05/2026\n"
               "Supervisee: Sarah Ali (Care Assistant). Supervisor: J Bell (Registered Manager).\n"
               "Sarah demonstrated safe medication administration during a spot check on 05/05/2026; "
               "she checked the MAR chart, confirmed the resident's identity and recorded the dose immediately.\n"
               "Sarah explained how she supported Mrs Jones to make her own decision about getting dressed, "
               "showing an understanding of best interests and consent.\n"
               "Learning need identified: formal Mental Capacity Act assessments - training booked for June.\n"
               "Sarah reported the team is two staff short on early shifts; manager to review the rota.\n")
        res = asyncio.run(aimod.analyze_doc_for_evidence(doc, CQC_STDS, CC_STDS))
        assert isinstance(res, dict)
        for key in ("cqc_mappings", "care_cert_mappings", "custom_mappings"):
            assert key in res and isinstance(res[key], list)
        total = len(res["cqc_mappings"]) + len(res["care_cert_mappings"])
        assert total >= 1, f"doc evidence scan produced no mappings (parse failure?): {res}"
        for m in res["cqc_mappings"]:
            assert m.get("regulation_ref") and m.get("evidence_summary")
            assert m.get("confidence") in ("likely_evidence", "possible_evidence")


class TestJsonFenceParsing:
    """Gemini frequently wraps JSON in ```json fences and sometimes adds prose.
    Verify the shared parsing path in analyze_meeting tolerates these shapes."""

    def _run_with_stub(self, stub_text):
        async def stub(system, user, reasoning_effort=None, timeout_secs=360):
            return stub_text
        orig_g, orig_o = aimod._gemini_chat, aimod._openai_chat

        async def no_openai(*a, **k):
            raise AssertionError("should not reach OpenAI")

        aimod._gemini_chat = stub
        aimod._openai_chat = no_openai
        try:
            return asyncio.run(aimod.analyze_meeting(
                transcript_text="x", cqc_standards=CQC_STDS,
                care_cert_standards=CC_STDS, paused_periods=[]))
        finally:
            aimod._gemini_chat = orig_g
            aimod._openai_chat = orig_o

    PAYLOAD = '{"summary": "' + ("s" * 60) + '", "actions": [], "learning_needs": [], "risks": [], "cqc_mappings": [], "care_cert_mappings": []}'

    def test_bare_json(self):
        res = self._run_with_stub(self.PAYLOAD)
        assert "could not be parsed" not in res["summary"]

    def test_json_code_fence(self):
        res = self._run_with_stub("```json\n" + self.PAYLOAD + "\n```")
        assert "could not be parsed" not in res["summary"]

    def test_code_fence_with_trailing_newline(self):
        res = self._run_with_stub("```json\n" + self.PAYLOAD + "\n```\n")
        assert "could not be parsed" not in res["summary"], \
            "trailing newline after closing fence breaks the parser"

    def test_prose_before_fence(self):
        res = self._run_with_stub("Here is the analysis:\n\n```json\n" + self.PAYLOAD + "\n```")
        assert "could not be parsed" not in res["summary"], \
            "leading prose before the JSON fence breaks the parser"

    def test_prose_after_fence(self):
        res = self._run_with_stub("```json\n" + self.PAYLOAD + "\n```\n\nLet me know if you need more.")
        assert "could not be parsed" not in res["summary"]

    def test_prose_around_unfenced_json(self):
        res = self._run_with_stub("Sure! Here you go:\n" + self.PAYLOAD + "\nHope that helps.")
        assert "could not be parsed" not in res["summary"]


# ── iteration_82: direct unit tests for the shared _extract_json() helper ────
class TestExtractJsonHelper:
    OBJ = '{"a": 1, "b": [1, 2]}'
    LST = '[{"a": 1}, {"b": 2}]'

    def test_fenced_object(self):
        assert aimod._extract_json("```json\n" + self.OBJ + "\n```") == {"a": 1, "b": [1, 2]}

    def test_bare_object(self):
        assert aimod._extract_json(self.OBJ) == {"a": 1, "b": [1, 2]}

    def test_prose_before_and_after_unfenced(self):
        raw = "Certainly, here is the JSON:\n" + self.OBJ + "\nLet me know."
        assert aimod._extract_json(raw) == {"a": 1, "b": [1, 2]}

    def test_outer_list_preferred_when_prose_has_braces(self):
        raw = "Result (note: {see above}):\n" + self.LST
        out = aimod._extract_json(raw)
        assert isinstance(out, list) and len(out) == 2

    def test_fence_without_json_tag(self):
        assert aimod._extract_json("```\n" + self.LST + "\n```") == [{"a": 1}, {"b": 2}]

    def test_invalid_raises_jsondecodeerror(self):
        import json as _json
        with pytest.raises(_json.JSONDecodeError):
            aimod._extract_json("there is no json here at all")

    def test_empty_raises(self):
        import json as _json
        with pytest.raises(_json.JSONDecodeError):
            aimod._extract_json("")


# ── iteration_82: recoverable vertex-client latch (5 min TTL) ────────────────
class TestVertexClientLatchTtl:
    def teardown_method(self):
        aimod._vertex_client = None
        aimod._vertex_client_failed_at = None
        assert aimod._get_vertex_client() is not None

    def test_ttl_constant_is_5_minutes(self):
        assert aimod._VERTEX_RETRY_AFTER_SECS == 300

    def test_latch_set_when_config_missing_and_suppresses_retry(self, monkeypatch):
        aimod._vertex_client = None
        aimod._vertex_client_failed_at = None
        monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
        assert aimod._get_vertex_client() is None
        assert aimod._vertex_client_failed_at is not None
        # within TTL: still suppressed even if config comes back
        monkeypatch.setenv("GCP_PROJECT_ID", "two-one-production")
        assert aimod._get_vertex_client() is None

    def test_client_recovers_after_ttl_elapses(self, monkeypatch):
        aimod._vertex_client = None
        # simulate a failure that happened just over the TTL ago
        aimod._vertex_client_failed_at = time.time() - (aimod._VERTEX_RETRY_AFTER_SECS + 1)
        assert aimod._get_vertex_client() is not None, "client did not recover after TTL expiry"
        assert aimod._vertex_client_failed_at is None


# ── iteration_82: ThinkingConfig budget mapping ──────────────────────────────
class TestThinkingBudgets:
    def test_budget_map(self):
        assert aimod._THINKING_BUDGETS["high"] == 16384
        assert aimod._THINKING_BUDGETS["medium"] == 4096
        assert aimod._THINKING_BUDGETS.get(None, 0) == 0
        assert aimod._THINKING_BUDGETS.get("unknown-effort", 0) == 0

    def test_max_output_tokens_within_gemini_limit(self):
        src = open("/app/backend/utils/ai.py").read()
        assert "max_output_tokens=65535" in src
        assert "max_output_tokens=65536" not in src

    def test_reasoning_effort_forwarded_to_vertex_sync(self):
        seen = {}

        def fake_sync(system, user, reasoning_effort=None):
            seen["effort"] = reasoning_effort
            return "ok"

        orig = aimod._vertex_generate_sync
        aimod._vertex_generate_sync = fake_sync
        try:
            out = asyncio.run(aimod._gemini_chat("s", "u", "high", 30))
        finally:
            aimod._vertex_generate_sync = orig
        assert out == "ok"
        assert seen["effort"] == "high"
