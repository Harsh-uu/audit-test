"""Generalization + false-positive check for the UNRESOLVED OPERATIONAL NEED
rule: (1) a different 'wooly' equipment/training need (generalizes?), (2) a
normal explicit task with a firm date/owner (regression — unaffected?),
(3) an unrelated hedge with NO underlying need/request (false positive?).
"""
import asyncio
import sys
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv()

from utils import ai as ai_utils
from utils import standards_cache as sc

CASE_A_TRAINING_NEED = """
Callum Reid: Anything else on your mind before we finish?

Farah Hussein: Actually yeah, a couple of the newer residents on Elm wing have really specific dietary needs, textured diets and things, and I don't feel like I've had proper training on that side of things.

Callum Reid: That's a fair point actually, I'm not sure what training we've currently got signed up to for that. We'd need to look into what IDDSI training options are out there and whether it's something we do in-house or externally. I don't know off the top of my head.

Farah Hussein: Yeah, that makes sense, it's not urgent but it'd be good to sort at some point.

Callum Reid: Okay, let's leave it there for today.
"""

CASE_B_CLEAR_TASK = """
Callum Reid: One thing before we wrap up, can you make sure you complete the fire warden refresher by the end of next month?

Farah Hussein: Yes, I'll get that booked in by the 30th.

Callum Reid: Perfect, thanks Farah, that's everything for today.
"""

CASE_C_UNRELATED_HEDGE = """
Callum Reid: How was your weekend?

Farah Hussein: It was alright, went to see my sister, traffic was a nightmare though, I don't know why people drive like that on a Sunday.

Callum Reid: Ha, fair enough. Let's get started then, how's the medication rounds been going?

Farah Hussein: All fine, no issues to report.

Callum Reid: Great, nothing else major this week?

Farah Hussein: No, pretty quiet week to be honest.

Callum Reid: Good, let's leave it there then, thanks Farah.
"""


async def run_case(name, transcript):
    cqc_standards = [dict(r) for r in sc.get_system("cqc")]
    care_cert_standards = [dict(r) for r in sc.get_system("care_cert")]
    result = await ai_utils.analyze_meeting(
        transcript_text=transcript,
        cqc_standards=cqc_standards,
        care_cert_standards=care_cert_standards,
        paused_periods=[],
        custom_standards=[],
        supervision_template=None,
        custom_prompt=None,
        jurisdiction="england",
        manager_name="Callum Reid",
        attendee_names=["Farah Hussein"],
        meeting_type="Supervision",
    )
    print(f"\n===== {name} =====")
    actions = result.get("actions", [])
    print(f"Action count: {len(actions)}")
    for a in actions:
        print("-", a.get("text"), "|", a.get("action_type"), "|", a.get("assigned_to"))


async def main():
    await run_case("CASE A — wooly training need (should generalize + capture)", CASE_A_TRAINING_NEED)
    await run_case("CASE B — clear explicit task (regression check — must still work)", CASE_B_CLEAR_TASK)
    await run_case("CASE C — unrelated hedge, no real need (should NOT spawn an action)", CASE_C_UNRELATED_HEDGE)


if __name__ == "__main__":
    asyncio.run(main())
