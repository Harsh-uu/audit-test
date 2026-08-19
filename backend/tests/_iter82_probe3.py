"""iteration_82 probe 3: instrumented copy of _vertex_generate_sync capturing
finish_reason + usage on every analyze_meeting run, to pin down the intermittent
truncated-JSON failure."""
import asyncio, sys, json
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
import utils.ai as aimod
from tests.test_iter81_vertex_ai import TRANSCRIPT, CQC_STDS, CC_STDS
from google.genai import types

meta = []


def instrumented(system, user, reasoning_effort=None):
    client = aimod._get_vertex_client()
    safety = [types.SafetySetting(category=c, threshold="BLOCK_NONE")
              for c in ("HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_HARASSMENT",
                        "HARM_CATEGORY_DANGEROUS_CONTENT", "HARM_CATEGORY_SEXUALLY_EXPLICIT")]
    resp = client.models.generate_content(
        model=aimod.GEMINI_MODEL, contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system, temperature=0.3, max_output_tokens=65535,
            safety_settings=safety,
            thinking_config=types.ThinkingConfig(
                thinking_budget=aimod._THINKING_BUDGETS.get(reasoning_effort, 0)),
        ),
    )
    c = resp.candidates[0]
    u = resp.usage_metadata
    meta.append({
        "finish_reason": str(c.finish_reason),
        "cand_tokens": u.candidates_token_count,
        "thoughts": u.thoughts_token_count,
        "total": u.total_token_count,
    })
    return (resp.text or "").strip()


aimod._vertex_generate_sync = instrumented


async def blocked(*a, **k):
    raise AssertionError("OPENAI FALLBACK USED")


aimod._openai_chat = blocked

for i in range(7):
    meta.clear()
    res = asyncio.run(aimod.analyze_meeting(
        transcript_text=TRANSCRIPT, cqc_standards=CQC_STDS,
        care_cert_standards=CC_STDS, paused_periods=[]))
    ok = "could not be parsed" not in res.get("summary", "")
    print(f"run {i}: parse_ok={ok} meta={meta}")
