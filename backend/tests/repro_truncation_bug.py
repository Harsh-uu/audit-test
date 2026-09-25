"""Proves the 80,000-char truncation bug: pads a transcript past the OLD
cutoff so the photo-consent discussion sits beyond char 80,000, then runs it
through the (now-fixed) analyze_meeting to confirm the ending is no longer
silently dropped.
"""
import asyncio
import json
import sys
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv()

from utils import ai as ai_utils
from utils import standards_cache as sc

FILLER_TURN = (
    "Callum Reid: So talking through the medication round this week, how did that go for you generally, "
    "any issues with timings or double-checking with a colleague before administering? "
    "Farah Hussein: Yeah it went okay, I made sure I always double checked with whoever was on shift with me, "
    "and I signed the MAR chart straight after each round so there was no gap. "
)

TAIL = """
Callum Reid: Right, before we wrap up, is there anything else on your mind?

Farah Hussein: Yeah, okay, I'll raise that with the agency directly. So thank you for walking me through that, um, even though it felt like nothing at the time. So one small thing, Resident D's family have asked whether we can start sending photo updates occasionally because they're overseas and they don't get to visit often. I think they were thinking they would really appreciate that.

Callum Reid: Yeah, that's a nice idea actually. I don't see why we couldn't do that with the sort of, you know, usual consent and photo policy, etc. We need to figure out the sort of how we're going to do that because we're obviously not allowed our phones on shift. And obviously we don't want to be taking photos of the people we support on shift. So, you know, I guess we'd need like a, you know, a camera that we can connect to the office PC or something like that. I don't know.

Farah Hussein: Yeah, that makes sense.

Callum Reid: Okay, let's leave it there for today, thanks Farah.
"""

filler = (FILLER_TURN * 350)  # ~85K+ chars of padding, well past the old 80K cutoff
transcript = filler + TAIL
print(f"Total transcript length: {len(transcript)} chars (old cutoff was 80,000; tail starts at char {len(filler)})")


async def main():
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

    actions = result.get("actions", [])
    print("=== ACTIONS (total:", len(actions), ") ===")
    photo_action_found = False
    for a in actions:
        print("-", a.get("text"))
        if "photo" in a.get("text", "").lower() or "camera" in a.get("text", "").lower():
            photo_action_found = True
    print()
    print("PHOTO/CAMERA ACTION CAPTURED:", photo_action_found)


if __name__ == "__main__":
    asyncio.run(main())
