"""One-off repro script: does the AI correctly turn the 'photo updates for
family + consent + no-phones-on-shift' discussion into an action item?
Run: python tests/repro_photo_consent_action.py
"""
import asyncio
import json
import sys
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv()

from utils import ai as ai_utils
from utils import standards_cache as sc

TRANSCRIPT = """
Callum Reid: Right, before we wrap up, is there anything else on your mind?

Farah Hussein: Yeah, okay, I'll raise that with the agency directly. So thank you for walking me through that, um, even though it felt like nothing at the time. So one small thing, Resident D's family have asked whether we can start sending photo updates occasionally because they're overseas and they don't get to visit often. I think they were thinking they would really appreciate that.

Callum Reid: Yeah, that's a nice idea actually. I don't see why we couldn't do that with the sort of, you know, usual consent and photo policy, etc. We need to figure out the sort of how we're going to do that because we're obviously not allowed our phones on shift. And obviously we don't want to be taking photos of the people we support on shift. So, you know, I guess we'd need like a, you know, a camera that we can connect to the office PC or something like that. I don't know.

Farah Hussein: Yeah, that makes sense.

Callum Reid: Okay, let's leave it there for today, thanks Farah.
"""


async def main():
    cqc_rows = sc.get_system("cqc")
    care_cert_rows = sc.get_system("care_cert")

    def parse(r):
        return dict(r) if not isinstance(r, dict) else r

    cqc_standards = [parse(r) for r in cqc_rows]
    care_cert_standards = [parse(r) for r in care_cert_rows]

    result = await ai_utils.analyze_meeting(
        transcript_text=TRANSCRIPT,
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

    print("=== ACTIONS ===")
    print(json.dumps(result.get("actions", []), indent=2))
    print("=== RISKS (count) ===", len(result.get("risks", [])))
    for r in result.get("risks", []):
        print("-", r.get("label"), "|", r.get("text", "")[:150])
    print("=== SUMMARY ===")
    print(result.get("summary", "")[:600])


if __name__ == "__main__":
    asyncio.run(main())
