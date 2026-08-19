"""iteration_82 probe 2: run the real analyze_meeting() path N times, capturing the
full raw Gemini text so intermittent parse failures can be diagnosed."""
import asyncio, sys, json
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
import utils.ai as aimod
from tests.test_iter81_vertex_ai import TRANSCRIPT, CQC_STDS, CC_STDS

captured = []
_orig = aimod._gemini_chat


async def spy(system, user, reasoning_effort=None, timeout_secs=360):
    out = await _orig(system, user, reasoning_effort, timeout_secs)
    captured.append(out)
    return out


aimod._gemini_chat = spy


async def blocked(*a, **k):
    raise AssertionError("OPENAI FALLBACK USED")


aimod._openai_chat = blocked

RUNS = 8
fails = 0
for i in range(RUNS):
    captured.clear()
    try:
        res = asyncio.run(aimod.analyze_meeting(
            transcript_text=TRANSCRIPT, cqc_standards=CQC_STDS,
            care_cert_standards=CC_STDS, paused_periods=[]))
    except Exception as e:
        print(f"run {i}: EXCEPTION {type(e).__name__}: {e}")
        fails += 1
        continue
    bad = "could not be parsed" in res.get("summary", "")
    raw = captured[-1] if captured else ""
    print(f"run {i}: parse_ok={not bad} raw_len={len(raw)} fence_closed={raw.rstrip().endswith('```')} tail={raw[-80:]!r}")
    if bad:
        fails += 1
        open(f"/tmp/iter82_bad_{i}.txt", "w").write(raw)
        print("   saved raw to", f"/tmp/iter82_bad_{i}.txt")
print(f"FAILURES {fails}/{RUNS}")
