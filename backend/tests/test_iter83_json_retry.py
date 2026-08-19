"""
iteration_83 — unit coverage for the new `_ai_chat_json()` parse-level retry and
the `_vertex_generate_sync()` finish_reason != STOP guard.

No live LLM calls in this file (deterministic stubs only) — the live/repeated
analyze_meeting coverage lives in tests/_iter83_hammer.py and
tests/test_iter81_vertex_ai.py.
"""
import asyncio
import json
import logging
import sys
import types as pytypes

import pytest
from dotenv import load_dotenv

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")

from utils import ai as aimod  # noqa: E402
from tests.test_iter81_vertex_ai import CQC_STDS, CC_STDS  # noqa: E402

GOOD = '{"summary": "' + ("s" * 60) + '", "actions": [], "learning_needs": [], "risks": [{"id": "r1", "text": "safeguarding issue", "severity": "high"}], "cqc_mappings": [], "care_cert_mappings": []}'
BAD = '```json\n{"summary": "truncated mid'


# ── _ai_chat_json(): parse-level OpenAI retry ────────────────────────────────
class TestAiChatJsonRetry:
    def _patch(self, gemini_text, openai_text=None, openai_raises=None):
        self._orig_g, self._orig_o = aimod._gemini_chat, aimod._openai_chat
        self.calls = {"gemini": 0, "openai": 0}

        async def g(system, user, reasoning_effort=None, timeout_secs=360):
            self.calls["gemini"] += 1
            return gemini_text

        async def o(model, system, user, reasoning_effort=None, timeout_secs=360):
            self.calls["openai"] += 1
            if openai_raises:
                raise openai_raises
            return openai_text

        aimod._gemini_chat, aimod._openai_chat = g, o

    def teardown_method(self):
        if hasattr(self, "_orig_g"):
            aimod._gemini_chat, aimod._openai_chat = self._orig_g, self._orig_o

    def test_valid_gemini_json_no_openai_call(self):
        self._patch(GOOD)
        out = asyncio.run(aimod._ai_chat_json("o4-mini", "s", "u"))
        assert out["summary"].startswith("s")
        assert self.calls == {"gemini": 1, "openai": 0}

    def test_malformed_gemini_json_retries_via_openai(self, caplog):
        self._patch(BAD, openai_text=GOOD)
        with caplog.at_level(logging.WARNING, logger="utils.ai"):
            out = asyncio.run(aimod._ai_chat_json("o4-mini", "s", "u"))
        assert isinstance(out, dict) and len(out["summary"]) > 50
        assert self.calls["openai"] == 1, "OpenAI retry was not attempted on parse failure"
        assert "retrying directly via OpenAI" in caplog.text

    def test_both_malformed_raises_jsondecodeerror(self):
        self._patch(BAD, openai_text="still not json")
        with pytest.raises(json.JSONDecodeError):
            asyncio.run(aimod._ai_chat_json("o4-mini", "s", "u"))
        assert self.calls["openai"] == 1

    def test_analyze_meeting_recovers_from_malformed_gemini(self):
        """End-to-end through analyze_meeting: malformed Gemini body must NOT
        dead-end into the 'Analysis could not be parsed' placeholder."""
        self._patch(BAD, openai_text=GOOD)
        res = asyncio.run(aimod.analyze_meeting(
            transcript_text="x", cqc_standards=CQC_STDS,
            care_cert_standards=CC_STDS, paused_periods=[]))
        assert "could not be parsed" not in res["summary"], \
            "parse-level OpenAI retry did not rescue the analysis"
        assert res["risks"] and "custom_mappings" in res

    def test_analyze_meeting_placeholder_only_when_both_providers_malformed(self):
        self._patch(BAD, openai_text="no json here")
        res = asyncio.run(aimod.analyze_meeting(
            transcript_text="x", cqc_standards=CQC_STDS,
            care_cert_standards=CC_STDS, paused_periods=[]))
        assert "could not be parsed" in res["summary"]

    def test_all_eight_json_callsites_use_wrapper(self):
        src = open("/app/backend/utils/ai.py").read()
        assert src.count("_ai_chat_json(") >= 9  # 1 def + 8 call sites
        # no remaining manual `_extract_json(await _ai_chat(...))` pattern
        assert "_extract_json(await _ai_chat" not in src
        assert "_extract_json(raw_response)" not in src


# ── _vertex_generate_sync(): finish_reason guard ──────────────────────────────
class _FakeCandidate:
    def __init__(self, name):
        self.finish_reason = pytypes.SimpleNamespace(name=name)


class _FakeResponse:
    def __init__(self, name, text="ok text"):
        self.candidates = [_FakeCandidate(name)]
        self.text = text
        self.prompt_feedback = None


class _FakeModels:
    def __init__(self, resp):
        self._resp = resp

    def generate_content(self, **kwargs):
        return self._resp


class TestFinishReasonGuard:
    def _run(self, resp):
        orig = aimod._get_vertex_client
        aimod._get_vertex_client = lambda: pytypes.SimpleNamespace(models=_FakeModels(resp))
        try:
            return aimod._vertex_generate_sync("s", "u", "high")
        finally:
            aimod._get_vertex_client = orig

    def test_stop_returns_text(self):
        assert self._run(_FakeResponse("STOP")) == "ok text"

    @pytest.mark.parametrize("reason", ["MAX_TOKENS", "SAFETY", "RECITATION", "OTHER"])
    def test_non_stop_raises(self, reason):
        with pytest.raises(ValueError) as ei:
            self._run(_FakeResponse(reason, text="partial {"))
        assert reason in str(ei.value)

    def test_no_candidates_raises(self):
        resp = _FakeResponse("STOP")
        resp.candidates = []
        with pytest.raises(ValueError):
            self._run(resp)

    def test_non_stop_triggers_openai_fallback_in_ai_chat(self, caplog):
        """A truncated Gemini response must be caught BEFORE the JSON parser and
        route to OpenAI via _ai_chat's existing except-block."""
        orig_sync, orig_openai = aimod._vertex_generate_sync, aimod._openai_chat
        calls = {"openai": 0}

        def truncated(system, user, reasoning_effort=None):
            raise ValueError("Vertex AI response truncated/blocked (finish_reason=MAX_TOKENS)")

        async def fake_openai(model, system, user, reasoning_effort=None, timeout_secs=360):
            calls["openai"] += 1
            return GOOD

        aimod._vertex_generate_sync = truncated
        aimod._openai_chat = fake_openai
        try:
            with caplog.at_level(logging.WARNING, logger="utils.ai"):
                out = asyncio.run(aimod._ai_chat_json("o4-mini", "s", "u"))
        finally:
            aimod._vertex_generate_sync = orig_sync
            aimod._openai_chat = orig_openai
        assert calls["openai"] == 1
        assert isinstance(out, dict)
        assert "MAX_TOKENS" in caplog.text and "falling back to OpenAI" in caplog.text

    def test_live_successful_call_finish_reason_is_stop(self):
        """Regression guard: the new check must not false-trigger on real calls."""
        out = asyncio.run(aimod._gemini_chat("Be terse.", "Reply with the single word: STOPOK", timeout_secs=120))
        assert "STOPOK" in out.upper()
