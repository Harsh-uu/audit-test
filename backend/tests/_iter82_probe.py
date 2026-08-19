"""iteration_82 probe: capture finish_reason + usage metadata for a full
analyze_meeting-sized Gemini call to diagnose truncated JSON responses."""
import asyncio, os, sys, json
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
import utils.ai as aimod
from tests.test_iter81_vertex_ai import TRANSCRIPT, CQC_STDS, CC_STDS

from google.genai import types


def probe(reasoning_effort):
    client = aimod._get_vertex_client()
    user = "Analyse this supervision transcript and return JSON with keys summary, actions, learning_needs, risks, cqc_mappings, care_cert_mappings.\n\n" + TRANSCRIPT
    resp = client.models.generate_content(
        model=aimod.GEMINI_MODEL,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=aimod.ANALYSIS_SYSTEM_PROMPT,
            temperature=0.3,
            max_output_tokens=65535,
            thinking_config=types.ThinkingConfig(
                thinking_budget=aimod._THINKING_BUDGETS.get(reasoning_effort, 0)),
        ),
    )
    c = resp.candidates[0]
    print(f"--- reasoning_effort={reasoning_effort}")
    print("finish_reason:", c.finish_reason)
    print("usage:", resp.usage_metadata)
    txt = resp.text or ""
    print("len(text):", len(txt))
    print("tail:", repr(txt[-120:]))
    try:
        aimod._extract_json(txt)
        print("PARSE: OK")
    except Exception as e:
        print("PARSE: FAIL", e)


for eff in ("high", None):
    try:
        probe(eff)
    except Exception as e:
        print("probe error", eff, type(e).__name__, e)
