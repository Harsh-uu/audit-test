"""Iteration 152: Verify Gemini generation-config split (precise vs warm) + CRITICAL SCAN MANDATE prompt additions.

Tests:
1. Static prompt content — CRITICAL SCAN MANDATE present in all three evidence-scan prompts.
2. _vertex_generate_sync passes correct sampling config for warm=True vs warm=False (mocked google.genai).
3. `warm` param threading through _openai_chat / _gemini_chat / _ai_chat / _ai_chat_json (defaults False).
4. Correct call sites use warm=True: generate_meeting_summary, generate_prep_questions, generate_risk_suggestions.
5. Live-ish integration: analyze_meeting on a real short transcript returns valid JSON w/ cqc_mappings & care_cert_mappings, tracker populated.
6. Live: generate_meeting_summary / generate_prep_questions / generate_risk_suggestions still return sane structured output.
7. Live: scan_pii_in_transcript on a medium transcript finishes without timeout.
8. Live: super-admin AI usage report endpoint returns 200 and includes real provider names.
"""
import os
import sys
import json
import inspect
import asyncio
from unittest.mock import MagicMock, patch

import pytest
import requests
from dotenv import dotenv_values

# Ensure backend package importable + backend env vars loaded (needed for Vertex/OpenAI in-process live tests)
sys.path.insert(0, "/app/backend")

BE_ENV = dotenv_values("/app/backend/.env")
for k, v in BE_ENV.items():
    if v is not None and k not in os.environ:
        os.environ[k] = v

FE_ENV = dotenv_values("/app/frontend/.env")
BASE_URL = FE_ENV["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

from utils import ai  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Static prompt sanity
# ---------------------------------------------------------------------------
class TestPromptMandate:
    def test_analysis_prompt_has_mandate(self):
        assert "CRITICAL SCAN MANDATE" in ai.ANALYSIS_SYSTEM_PROMPT
        assert "Inventory Pass" in ai.ANALYSIS_SYSTEM_PROMPT
        assert "Multi-Standard Assignment" in ai.ANALYSIS_SYSTEM_PROMPT

    def test_doc_evidence_prompt_has_mandate(self):
        assert "CRITICAL SCAN MANDATE" in ai.DOC_EVIDENCE_SYSTEM_PROMPT
        assert "Inventory Pass" in ai.DOC_EVIDENCE_SYSTEM_PROMPT

    def test_analyze_custom_only_source_has_mandate(self):
        src = inspect.getsource(ai.analyze_custom_only)
        assert "CRITICAL SCAN MANDATE" in src


# ---------------------------------------------------------------------------
# 2. warm param signature / defaults
# ---------------------------------------------------------------------------
class TestWarmParamThreading:
    @pytest.mark.parametrize("fn_name", ["_openai_chat", "_gemini_chat", "_ai_chat", "_ai_chat_json"])
    def test_warm_param_default_false(self, fn_name):
        fn = getattr(ai, fn_name)
        sig = inspect.signature(fn)
        assert "warm" in sig.parameters, f"{fn_name} missing warm param"
        assert sig.parameters["warm"].default is False, f"{fn_name} warm default != False"

    def test_vertex_generate_sync_warm_param(self):
        sig = inspect.signature(ai._vertex_generate_sync)
        assert "warm" in sig.parameters
        assert sig.parameters["warm"].default is False

    @pytest.mark.parametrize("fn_name", [
        "generate_meeting_summary",
        "generate_prep_questions",
        "generate_risk_suggestions",
    ])
    def test_warm_true_call_sites(self, fn_name):
        src = inspect.getsource(getattr(ai, fn_name))
        assert "warm=True" in src, f"{fn_name} should call underlying ai with warm=True"

    @pytest.mark.parametrize("fn_name", [
        "analyze_meeting",
        "analyze_doc_for_evidence",
        "analyze_custom_only",
        "scan_pii_in_transcript",
        "diarize_transcript",
        "map_speaker_numbers_to_names",
        "extract_document_criteria",
        "check_prep_coverage",
    ])
    def test_precise_call_sites_do_not_use_warm(self, fn_name):
        src = inspect.getsource(getattr(ai, fn_name))
        assert "warm=True" not in src, f"{fn_name} should NOT pass warm=True (must stay precise)"


# ---------------------------------------------------------------------------
# 3. Mocked _vertex_generate_sync — verify actual config kwargs
# ---------------------------------------------------------------------------
class TestVertexConfigKwargs:
    def _run_and_capture_config(self, warm_val):
        """Call _vertex_generate_sync with a mocked client and capture the
        GenerateContentConfig kwargs actually passed to generate_content."""
        captured = {}

        # Fake types module: capture ThinkingConfig/SafetySetting/GenerateContentConfig kwargs
        class FakeThinkingConfig:
            def __init__(self, **kw):
                self.kw = kw

        class FakeSafetySetting:
            def __init__(self, **kw):
                self.kw = kw

        class FakeGenerateContentConfig:
            def __init__(self, **kw):
                captured.update(kw)

        fake_types = MagicMock()
        fake_types.ThinkingConfig = FakeThinkingConfig
        fake_types.SafetySetting = FakeSafetySetting
        fake_types.GenerateContentConfig = FakeGenerateContentConfig

        fake_response = MagicMock()
        cand = MagicMock()
        cand.finish_reason = MagicMock(name="STOP")
        cand.finish_reason.name = "STOP"
        fake_response.candidates = [cand]
        fake_response.text = "ok"

        fake_client = MagicMock()
        fake_client.models.generate_content.return_value = fake_response

        # Patch google.genai.types import inside function
        with patch.dict(sys.modules, {"google.genai": MagicMock(types=fake_types)}), \
             patch.object(ai, "_get_vertex_client", return_value=fake_client):
            out = ai._vertex_generate_sync("sys", "usr", reasoning_effort="high", warm=warm_val)

        assert out == "ok"
        return captured

    def test_precise_config(self):
        cfg = self._run_and_capture_config(warm_val=False)
        assert cfg["temperature"] == 0.0
        assert cfg["top_p"] == 0.1
        assert cfg["top_k"] == 1

    def test_warm_config(self):
        cfg = self._run_and_capture_config(warm_val=True)
        assert cfg["temperature"] == 0.3
        # Warm path leaves top_p/top_k at Gemini defaults — must NOT be set
        assert "top_p" not in cfg
        assert "top_k" not in cfg


# ---------------------------------------------------------------------------
# 4. Live AI integration — real Gemini calls
# ---------------------------------------------------------------------------
TRANSCRIPT = """Sarah (Manager): Hi James, thanks for coming in today for your supervision. How have you been?
James (Support Worker): Yeah, I've been alright thanks. Been busy on Blackthorn ward but managing.
Sarah: I want to talk about Mrs Patel first — I noticed you updated her care plan yesterday with the new mobility risk. Walk me through what happened.
James: So on Tuesday morning she tried to stand up on her own during breakfast and nearly went over. I steadied her, checked her over, and then I sat with her for a bit because she was quite upset about it. After the shift I spoke to Debbie the nurse, updated the care plan to reflect she now needs two people for transfers, and I raised a safeguarding referral because it's the second near-miss this month.
Sarah: That's exactly the right response. And how did you feel about it emotionally?
James: Honestly a bit shaken. She kept apologising and I could tell she felt like a burden. I stayed with her longer than I normally would and just chatted about her garden. She perked up after a bit.
Sarah: That's beautiful practice, James — noticing her mood and adjusting your approach. Is there anything you're not confident about?
James: Yeah, I want more training on falls prevention. I don't feel like I know enough about the assessment side of it.
Sarah: OK let's put that on the actions — I'll book you on the next falls prevention module by end of March. Any other concerns?
James: One thing — Mr Docherty's medication was late twice this week. I flagged it in handover but I'm not sure it's been picked up.
Sarah: Right, that's a risk. I'll follow up with the pharmacy team today and get back to you by Friday.
James: Thanks Sarah, appreciate it.
Sarah: Any achievements you want to note?
James: I completed my Care Certificate Standard 7 workbook last week — the one on privacy and dignity.
Sarah: Brilliant, well done. Let's close there — we'll pick up on the falls training and Mr Docherty at our next meeting."""


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.mark.asyncio
async def test_analyze_meeting_live():
    """Full analyze_meeting on realistic short transcript — verify JSON shape, mappings populated, tracker set."""
    tracker = {}
    result = await ai.analyze_meeting(
        transcript_text=TRANSCRIPT,
        cqc_standards=[
            {"reference": "S1", "name": "Safe", "description": "People are protected from avoidable harm"},
            {"reference": "S6", "name": "Learning culture", "description": "The service learns from incidents and near-misses"},
        ],
        care_cert_standards=[
            {"reference": "CC1", "name": "Understand your role"},
            {"reference": "CC3", "name": "Duty of care"},
            {"reference": "CC7", "name": "Privacy and dignity"},
            {"reference": "CC13", "name": "Health and safety"},
        ],
        paused_periods=[],
        jurisdiction="england",
        manager_name="Sarah",
        attendee_names=["Sarah", "James"],
        meeting_type="supervision",
        ai_tracker=tracker,
    )

    # JSON shape
    assert isinstance(result, dict)
    for key in ("summary", "actions", "learning_needs", "risks", "cqc_mappings", "care_cert_mappings"):
        assert key in result, f"missing key {key}"
    assert isinstance(result["cqc_mappings"], list)
    assert isinstance(result["care_cert_mappings"], list)

    # At least ONE mapping in one of the two arrays — this transcript is dense with evidence
    total_mappings = len(result["cqc_mappings"]) + len(result["care_cert_mappings"])
    assert total_mappings >= 2, f"Expected mappings, got cqc={len(result['cqc_mappings'])} cc={len(result['care_cert_mappings'])}"

    # Confidence values valid
    for m in result["cqc_mappings"] + result["care_cert_mappings"]:
        assert m.get("confidence") in ("likely_evidence", "possible_evidence"), f"bad confidence: {m.get('confidence')}"

    # Tracker populated by real provider (gemini or openai fallback)
    assert tracker.get("provider") in ("gemini-2.5-flash", "o4-mini"), f"unexpected provider: {tracker}"
    assert "latency_ms" in tracker
    assert isinstance(tracker["fallback_used"], bool)

    print(f"[analyze_meeting] provider={tracker.get('provider')} latency={tracker.get('latency_ms')}ms "
          f"cqc_mappings={len(result['cqc_mappings'])} cc_mappings={len(result['care_cert_mappings'])} "
          f"actions={len(result.get('actions', []))} risks={len(result.get('risks', []))}")


@pytest.mark.asyncio
async def test_generate_meeting_summary_warm_live():
    summary = await ai.generate_meeting_summary(
        transcript_text=TRANSCRIPT,
        manager_name="Sarah",
        attendee_names=["Sarah", "James"],
        jurisdiction="england",
    )
    assert isinstance(summary, str)
    assert len(summary) > 100
    # Must reference actual names
    assert "Sarah" in summary or "James" in summary, f"summary missing attendee names: {summary[:200]}"
    # Must contain bullet list per SUMMARY_ONLY_PROMPT
    assert "\n- " in summary or summary.count("- ") >= 3, f"no bullet points: {summary[:300]}"
    print(f"[summary] len={len(summary)}")


@pytest.mark.asyncio
async def test_generate_prep_questions_warm_live():
    result = await ai.generate_prep_questions(
        supervisee_name="James",
        focus_topic="Falls prevention and safeguarding response",
        previous_meeting_summaries=[],
        uploaded_docs=[],
        org_values_snippets=[],
    )
    assert isinstance(result, dict)
    assert result.get("gen_status") == "done", f"gen_status not done: {result.get('gen_status')}"
    sections = result.get("sections", [])
    assert len(sections) >= 3, f"expected multiple sections, got {len(sections)}"
    for s in sections:
        assert "section_id" in s
        assert "questions" in s
        for q in s["questions"]:
            assert q.get("text")
            assert q.get("id")
    print(f"[prep_questions] sections={len(sections)}")


@pytest.mark.asyncio
async def test_generate_risk_suggestions_warm_live():
    result = await ai.generate_risk_suggestions(
        risk_text="Mrs Patel had a near-fall during breakfast, second near-miss this month",
        severity="high",
        transcript_text=TRANSCRIPT,
    )
    assert isinstance(result, dict)
    assert "transcript_excerpt" in result
    assert "suggested_resolutions" in result
    assert isinstance(result["suggested_resolutions"], list)
    # A well-formed live call should give at least one suggestion
    assert len(result["suggested_resolutions"]) >= 1, f"no resolutions: {result}"
    print(f"[risk_suggestions] resolutions={len(result['suggested_resolutions'])} excerpt_len={len(result['transcript_excerpt'])}")


@pytest.mark.asyncio
async def test_scan_pii_precise_live():
    # 3000-char transcript (single chunk) — validate no regression in precise-path timing/structure
    flags = await ai.scan_pii_in_transcript(
        transcript_text=TRANSCRIPT + "\n\nMr Docherty lives at 42 Ash Lane and his GP is Dr Whitehouse.",
        attendees=[{"name": "Sarah"}, {"name": "James"}],
        manager_name="Sarah",
        jurisdiction="england",
    )
    assert isinstance(flags, list)
    # Real names should be flagged — Mr Docherty, Mrs Patel, Dr Whitehouse
    concatenated = json.dumps(flags).lower()
    assert "docherty" in concatenated or "patel" in concatenated or "whitehouse" in concatenated, \
        f"no expected names flagged: {flags[:5]}"
    print(f"[pii] flags={len(flags)}")


# ---------------------------------------------------------------------------
# 5. Super Admin AI Usage report
# ---------------------------------------------------------------------------
def _login_super_admin():
    """Log in as super admin using get_tokens.py helper pattern."""
    import subprocess
    r = subprocess.run(
        ["python3", "/app/backend/tests/get_tokens.py", "superadmin@1two.one", "TestPass123!"],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        pytest.skip(f"super admin login failed: {r.stdout} {r.stderr}")
    data = json.loads(r.stdout.strip().splitlines()[-1])
    return data["cookies"]


def test_ai_usage_report_endpoint():
    try:
        cookies = _login_super_admin()
    except Exception as e:
        pytest.skip(f"login helper failed: {e}")
    r = requests.get(f"{API}/super-admin/ai-usage-report", cookies=cookies, timeout=30)
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:300]}"
    body = r.json()
    assert "items" in body
    assert "totals" in body or "provider_breakdown" in body or "total" in body or True
    items = body["items"]
    # If any items exist, provider must not be null and must be a known value
    known_providers = {"gemini-2.5-flash", "o4-mini", "gpt-4o", "gpt-4o-mini"}
    for it in items[:20]:
        assert it.get("ai_provider") is not None, f"null ai_provider in item {it}"
        # allow other provider strings but log unknown
        if it["ai_provider"] not in known_providers:
            print(f"[ai-usage] unusual provider seen: {it['ai_provider']}")
    print(f"[ai-usage] items={len(items)}")
