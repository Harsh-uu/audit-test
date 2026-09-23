"""
Tests for the mandatory 'practice_impact' section (Impact on Practice) in AI-generated
supervision prep agendas. This section must ALWAYS appear, decoupled from standard
PREP_SECTIONS, separate from 'aob' and 'bonus'. Backed by:
 1. Prompt rule 10 in utils/ai.py generate_prep_questions
 2. Code-level fallback safety-net that injects the section if the LLM omits it.

Test strategy:
 - Directly call generate_prep_questions() several times with different contexts
   (context-rich and blank slate).
 - Also exercise the full HTTP pipeline: login -> POST /generate -> poll GET /prep.
"""

import asyncio
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or None
API = f"{BASE_URL}/api" if BASE_URL else None

ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PASS = "Admin123!X"
CONTEXT_MEETING_ID = "a8527134-cb7c-42d3-8d82-a4cffc523f55"

# Ensure backend package is importable + backend env is loaded (OPENAI_API_KEY etc.)
import sys
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")


# ─── Direct-invocation tests (bypass HTTP) ─────────────────────────────────────

@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _has_practice_impact(sections):
    return [s for s in sections if s.get("section_id") == "practice_impact"]


def _run_generate(context_rich=True):
    from utils.ai import generate_prep_questions
    if context_rich:
        prev = [{
            "title": "May 1:1",
            "date": "2025-05-01",
            "summary": "Discussed medication administration and handover concerns on night shift.",
            "actions": [{"text": "Complete moving and handling refresher", "completed": False}],
        }]
        docs = [{
            "label": "Care Certificate Standard 6",
            "doc_type": "policy",
            "content_snippet": "Communication in adult social care: staff must ensure accurate handover of resident information at each shift change.",
        }]
        values = [{"name": "Kindness", "snippet": "We treat every resident with dignity."}]
        focus = "Improving handover quality"
        supervisee = "Alex Carer"
    else:
        prev, docs, values, focus, supervisee = [], [], [], "", "Sam NewStarter"
    return asyncio.get_event_loop().run_until_complete(
        generate_prep_questions(supervisee, focus, prev, docs, values)
    )


@pytest.mark.parametrize("run_idx", range(3))
def test_practice_impact_present_context_rich(run_idx):
    """Run 3 context-rich generations; practice_impact must be present each time with exactly 1 question."""
    result = _run_generate(context_rich=True)
    sections = result.get("sections", [])
    matches = _has_practice_impact(sections)
    assert len(matches) == 1, f"Run {run_idx}: expected exactly one practice_impact section, got {len(matches)}. Section IDs: {[s.get('section_id') for s in sections]}"
    sec = matches[0]
    assert sec.get("label") == "Impact on Practice", f"Wrong label: {sec.get('label')}"
    qs = sec.get("questions", [])
    assert len(qs) == 1, f"Run {run_idx}: expected 1 question, got {len(qs)}"
    assert qs[0].get("text", "").strip(), "Question text is empty"
    # Should not merge with aob
    aob_ids = [s for s in sections if s.get("section_id") == "aob"]
    assert len(aob_ids) == 1, "AOB section should still be present exactly once"


def test_practice_impact_present_blank_slate():
    """Blank-slate: no docs/prev/focus. Section must still appear (either LLM or fallback)."""
    result = _run_generate(context_rich=False)
    sections = result.get("sections", [])
    matches = _has_practice_impact(sections)
    assert len(matches) == 1, f"Blank slate missing practice_impact. Sections: {[s.get('section_id') for s in sections]}"
    assert len(matches[0].get("questions", [])) == 1


def test_standard_six_sections_still_present():
    """Regression: the 6 standard sections + bonus + practice_impact all present."""
    result = _run_generate(context_rich=True)
    ids = [s.get("section_id") for s in result.get("sections", [])]
    for expected in ["wellbeing", "working_well", "needs_attention", "learning_development", "achievements", "aob", "practice_impact", "bonus"]:
        assert expected in ids, f"Missing section_id '{expected}' — sections returned: {ids}"


def test_fallback_injection_when_llm_omits():
    """Directly simulate LLM omission by monkeypatching _ai_chat_json → practice_impact must be auto-injected."""
    from utils import ai as ai_mod

    async def fake_chat(*args, **kwargs):
        return {
            "sections": [
                {"section_id": "wellbeing", "label": "Wellbeing", "questions": [{"id": "q1", "text": "Test?"}]},
                {"section_id": "aob", "label": "Any Other Business", "questions": [{"id": "q2", "text": "Test AOB?"}]},
                {"section_id": "bonus", "label": "We thought you might also want to ask this", "questions": [{"id": "q3", "text": "Test bonus?"}]},
            ]
        }

    original = ai_mod._ai_chat_json
    ai_mod._ai_chat_json = fake_chat
    try:
        result = asyncio.get_event_loop().run_until_complete(
            ai_mod.generate_prep_questions("Test", "", [], [], [])
        )
    finally:
        ai_mod._ai_chat_json = original
    matches = _has_practice_impact(result["sections"])
    assert len(matches) == 1, "Fallback failed to inject practice_impact"
    assert matches[0]["label"] == "Impact on Practice"
    assert len(matches[0]["questions"]) == 1
    assert "difference" in matches[0]["questions"][0]["text"].lower()


# ─── HTTP-pipeline tests ───────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def auth_session():
    if not API:
        pytest.skip("REACT_APP_BACKEND_URL not set")
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=30)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text[:300]}"
    data = r.json()
    token = data.get("access_token") or data.get("token")
    if token:
        s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def test_http_get_prep_has_practice_impact(auth_session):
    """Fetch the existing prep record for the fixture meeting — must contain practice_impact."""
    r = auth_session.get(f"{API}/prep/{CONTEXT_MEETING_ID}", timeout=30)
    assert r.status_code == 200, f"GET /prep failed: {r.status_code} {r.text[:300]}"
    data = r.json()
    sections = data.get("sections", [])
    if not sections:
        pytest.skip("Meeting prep has no sections yet — trigger /generate first")
    ids = [s.get("section_id") for s in sections]
    assert "practice_impact" in ids, f"practice_impact missing from persisted prep. IDs: {ids}"
    pi = [s for s in sections if s["section_id"] == "practice_impact"][0]
    assert pi.get("label") == "Impact on Practice"
    assert len(pi.get("questions", [])) >= 1


def test_http_generate_and_persists_practice_impact(auth_session):
    """Kick /generate, poll until gen_status=done, verify practice_impact persisted."""
    r = auth_session.post(f"{API}/prep/{CONTEXT_MEETING_ID}/generate", json={}, timeout=30)
    assert r.status_code in (200, 202), f"POST /generate failed: {r.status_code} {r.text[:300]}"

    deadline = time.time() + 180
    last_status = None
    sections = []
    while time.time() < deadline:
        gr = auth_session.get(f"{API}/prep/{CONTEXT_MEETING_ID}", timeout=30)
        if gr.status_code == 200:
            data = gr.json()
            last_status = data.get("gen_status")
            sections = data.get("sections", []) or []
            if last_status == "done" and sections:
                break
        time.sleep(5)
    assert last_status == "done", f"Generation did not complete within timeout. last_status={last_status}"
    ids = [s.get("section_id") for s in sections]
    assert "practice_impact" in ids, f"practice_impact missing after fresh /generate. IDs: {ids}"
    assert "bonus" in ids, "bonus section missing"
    assert "aob" in ids, "aob section missing"
    # aob and practice_impact must be distinct
    assert len([s for s in sections if s["section_id"] == "practice_impact"]) == 1
    assert len([s for s in sections if s["section_id"] == "aob"]) == 1
