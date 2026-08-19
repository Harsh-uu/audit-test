"""iteration_83 — hammer analyze_meeting() with repeated LIVE calls.

Goal: reproduce the iteration_82 ~8% intermittent 'Analysis could not be parsed'
dead-end and confirm the new _ai_chat_json() OpenAI retry prevents it.

Usage: python tests/_iter83_hammer.py [iterations] [concurrency]
"""
import asyncio
import json
import logging
import os
import sys
import time

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")

from utils import ai as aimod  # noqa: E402
from tests.test_iter81_vertex_ai import TRANSCRIPT, CQC_STDS, CC_STDS  # noqa: E402

ITER = int(sys.argv[1]) if len(sys.argv) > 1 else 20
CONC = int(sys.argv[2]) if len(sys.argv) > 2 else 4

logging.basicConfig(level=logging.INFO)

events = []


class Collector(logging.Handler):
    def emit(self, record):
        msg = record.getMessage()
        if ("[Vertex AI]" in msg or "failed JSON parse" in msg
                or "Failed to parse AI response" in msg):
            events.append((record.levelname, msg[:300]))


logging.getLogger("utils.ai").addHandler(Collector())

openai_calls = {"n": 0}
_orig_openai = aimod._openai_chat


async def spy_openai(*a, **k):
    openai_calls["n"] += 1
    print(f"  !! OpenAI called (count={openai_calls['n']})")
    return await _orig_openai(*a, **k)


aimod._openai_chat = spy_openai

results = {"ok": 0, "placeholder": 0, "error": 0}
details = []


async def one(i):
    t0 = time.time()
    try:
        res = await aimod.analyze_meeting(
            transcript_text=TRANSCRIPT, cqc_standards=CQC_STDS,
            care_cert_standards=CC_STDS, paused_periods=[])
        dur = time.time() - t0
        summary = res.get("summary", "")
        if "could not be parsed" in summary:
            results["placeholder"] += 1
            details.append((i, "PLACEHOLDER", round(dur, 1)))
            print(f"[{i}] PLACEHOLDER after {dur:.1f}s  <-- DEAD-END BUG")
        else:
            results["ok"] += 1
            details.append((i, "OK", round(dur, 1)))
            print(f"[{i}] OK {dur:.1f}s risks={len(res.get('risks', []))} "
                  f"cqc={len(res.get('cqc_mappings', []))} "
                  f"cc={len(res.get('care_cert_mappings', []))} "
                  f"summary_len={len(summary)}")
    except Exception as e:
        results["error"] += 1
        details.append((i, f"EXC:{type(e).__name__}:{e}"[:160], round(time.time() - t0, 1)))
        print(f"[{i}] EXCEPTION {type(e).__name__}: {e}")


async def main():
    sem = asyncio.Semaphore(CONC)

    async def guarded(i):
        async with sem:
            await one(i)

    await asyncio.gather(*[guarded(i) for i in range(1, ITER + 1)])


t = time.time()
asyncio.run(main())
print("\n=== iteration_83 hammer summary ===")
print(f"iterations={ITER} concurrency={CONC} elapsed={time.time() - t:.0f}s")
print(json.dumps(results))
print(f"openai_calls_total={openai_calls['n']}")
print("interesting log events:")
for lvl, msg in events:
    print(f"  {lvl}: {msg}")
with open("/tmp/iter83_hammer.json", "w") as f:
    json.dump({"results": results, "details": details,
               "openai_calls": openai_calls["n"], "events": events}, f, indent=2)
print("wrote /tmp/iter83_hammer.json")
