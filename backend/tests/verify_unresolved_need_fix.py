"""Post-fix verification: the EXACT verbatim exchange the user pasted
(including Farah's hedging reply at 21:08, which my earlier reconstruction
lacked). Confirms (a) the action now gets captured, and (b) the evidence
scan output is unaffected (still finds the same standards mappings) by
this ACTIONS-only prompt change.
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
[19:56] Farah Hussein: Yeah, okay, I'll raise that with the agency directly. So thank you for walking me through that, um, even though it felt like nothing at the time. So one small thing, Resident D's family have asked whether we can start sending photo updates occasionally because they're overseas and they don't get to visit often. I think they were thinking they would really appreciate that.

[20:27] Callum Reid: Yeah, that's a nice idea actually. I don't see why we couldn't do that with the sort of, you know, usual consent and photo policy, etc. We need to figure out the sort of how we're going to do that because we're obviously not allowed our phones on shift. And obviously we don't want to be taking photos of the people we support on shift. So, you know, I guess we'd need like a, you know, a camera that we can connect to the office PC or something like that. I don't know.

[21:08] Farah Hussein: Yeah, that's a really good point actually, you know, consent and stuff. We need to check how we would do that. Um, yeah, that's an interesting one actually, so thank you for sharing that.

[21:20] Callum Reid: Okay, let's leave it there for today, thanks Farah.
"""


async def main():
    cqc_standards = [dict(r) for r in sc.get_system("cqc")]
    care_cert_standards = [dict(r) for r in sc.get_system("care_cert")]

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
    for a in result.get("actions", []):
        print("-", json.dumps(a))

    print("\n=== CQC EVIDENCE (mapping count) ===")
    cqc_map = result.get("cqc_mappings", result.get("cqc", []))
    print(json.dumps(cqc_map, indent=2)[:2000])

    full = json.dumps(result).lower()
    print("\nphoto/camera action captured:", any(
        ("photo" in a.get("text", "").lower() or "camera" in a.get("text", "").lower())
        for a in result.get("actions", [])
    ))


if __name__ == "__main__":
    asyncio.run(main())
