"""Proper RCA repro: NOT a truncation test. Builds a realistic ~4000-word,
multi-topic, 30-min supervision transcript (matching the user's exact
conditions) with the photo/consent/no-phones discussion embedded in the
MIDDLE (~20 min mark), surrounded by other real topics competing for the
model's attention in the same single-pass JSON extraction — exactly like a
real meeting, not an isolated 5-line snippet. Confirms whether Gemini
(unforced, real code path) drops this specific action amid a denser
transcript even though it captures it fine in isolation.
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
Callum Reid: Morning Farah, thanks for making time for this one. How's this month been for you overall?

Farah Hussein: Yeah, pretty good actually. Busier than usual with the new admission on Elm wing but I think we've settled into a routine with her now.

Callum Reid: Good, glad to hear it. Let's start with the medication side of things since that's always worth checking in on. How have the rounds been going, any issues with timings or double-checking with a colleague before administering?

Farah Hussein: It's been fine. I always make sure I double check with whoever's on shift with me before I give anything, and I sign the MAR chart straight after each round so there's no gap between giving it and recording it.

Callum Reid: Perfect, that's exactly what we want. And have you had any near misses or anything you've had to log on the medication error form recently?

Farah Hussein: No, nothing this month, touch wood. Although actually, thinking about it, there was one time a couple of weeks ago where the pharmacy delivery was a day late and we were down to the last dose of Mrs Patterson's blood pressure tablets. I ended up ringing the on-call pharmacist myself to check whether it was okay to hold off for a day rather than skip doses altogether.

Callum Reid: Good thinking, and did you log that as a near miss even though nothing actually went wrong?

Farah Hussein: I did make a note in the daily log but I don't think I filled out a formal near-miss form for it.

Callum Reid: I'd like you to go back and complete a proper near-miss form for that one, even retrospectively, just so we've got a paper trail and can flag it to the pharmacy if it becomes a pattern.

Farah Hussein: Okay, I'll do that today.

Callum Reid: Thanks. Let's talk about the new resident on Elm wing then, how's the settling in period gone from your side?

Farah Hussein: It's gone okay. She was quite anxious the first week, kept asking for her daughter a lot, but we've been doing the reassurance approach we agreed with the family and it's calmed down a good bit now.

Callum Reid: That's really good to hear. Did you get a chance to update her care plan with any of those observations?

Farah Hussein: Yeah, I added a note about the anxiety pattern and what seems to help, so the next person on shift knows what's worked.

Callum Reid: Brilliant, thank you for doing that, that's exactly the kind of thing that helps continuity. How's the rest of the wing doing generally, anything with Mr Okafor or Resident C that I should know about?

Farah Hussein: Mr Okafor's been in good spirits actually, his son visited last weekend and brought his old records player in, he's been much brighter since. Resident C's been about the same, still needing a bit of encouragement at mealtimes but nothing new to flag there.

Callum Reid: Good, always nice to hear a positive one. Now, training-wise, I know you were meant to do the moving and handling refresher this month, how did that go?

Farah Hussein: I did it last week actually, it was fine, nothing new really but good to go through it again.

Callum Reid: Good stuff. Is there anything you feel like you need more training on at the moment, anything you're less confident with?

Farah Hussein: Honestly I think I could do with a refresher on the falls protocol, it's been a while since I've actually had to use it and I want to make sure I remember the full process properly.

Callum Reid: Noted, I'll get that booked in for you. While we're on training, how are you getting on with the new electronic care records system, has that bedded in okay for you?

Farah Hussein: Mostly fine, I'm still a bit slow logging the fluid charts on it compared to paper but I'm getting quicker.

Callum Reid: That's normal, it'll come with practice. Let's talk about the team for a minute, how do you think morale's been generally with the two staff off sick?

Farah Hussein: It's been a bit strained if I'm honest, everyone's picking up extra shifts and tempers have been a little shorter than usual, but nothing that's caused any actual problems between people.

Callum Reid: Okay, good to know, I'll keep an eye on that and see if agency cover can take some of the pressure off. Is there anything from this week you want to flag or that's been on your mind?

Farah Hussein: Actually yes, there was something on Tuesday. One of the visitors, I think it was Resident B's nephew, I saw him going through some of the drawers in her room while she was in the lounge. I didn't think too much of it at the time, I just assumed he was looking for something for her.

Callum Reid: Okay, did you say anything to him at the time or mention it to anyone afterwards?

Farah Hussein: No, I didn't really think it was my place to say anything, and I got pulled away to help with lunch so I just left it.

Callum Reid: Right, I need to flag that this is something we should treat seriously, even if it felt low-key at the time. Going through a resident's belongings without her present isn't something we can just let go unmentioned, regardless of intention. I'll need you to write up exactly what you saw and when, and we'll look into whether anything's missing and review the visiting arrangements.

Farah Hussein: Okay, sorry, I didn't realise it was that serious.

Callum Reid: It's alright, that's exactly why we talk about these things, it's better raised late than not at all. Let's take a step back, how are you finding the overall pace of the role at the moment, still enjoying it?

Farah Hussein: Yeah, I do genuinely enjoy it, I just think this month's been a bit of a grind with the staffing being what it is.

Callum Reid: That's fair, and honest, thank you. Let's flag your wellbeing check-in then properly, how are you finding the workload generally at the moment?

Farah Hussein: Honestly it's been a bit much the last couple of weeks with two people off sick, I've been picking up extra shifts and I'm pretty tired by the end of the week.

Callum Reid: I appreciate you saying that. Let's flag that for a workload review, and I'll check in with you again in a couple of weeks to see how it's settling once the rota's back to normal.

Farah Hussein: That'd be good, thank you.

Callum Reid: One more thing before we finish up on the operational side, did the fire drill happen on your shift last month, and did it go smoothly?

Farah Hussein: Yeah it did, took about eleven minutes to get everyone to the assembly point, which I think is within the target time, but Resident A took a bit of coaxing to get out of his room.

Callum Reid: That's useful to know, we might want to think about a specific plan for him given that pattern, but let's park that for now and I'll raise it with the wider team meeting instead. Right, before we wrap up, is there anything else on your mind?

Farah Hussein: Yeah, okay, I'll raise that with the agency directly about the nephew thing. So thank you for walking me through that, um, even though it felt like nothing at the time. So one small thing, Resident D's family have asked whether we can start sending photo updates occasionally because they're overseas and they don't get to visit often. I think they were thinking they would really appreciate that.

Callum Reid: Yeah, that's a nice idea actually. I don't see why we couldn't do that with the sort of, you know, usual consent and photo policy, etc. We need to figure out the sort of how we're going to do that because we're obviously not allowed our phones on shift. And obviously we don't want to be taking photos of the people we support on shift. So, you know, I guess we'd need like a, you know, a camera that we can connect to the office PC or something like that. I don't know.

Farah Hussein: Yeah, that makes sense.

Callum Reid: Okay, let's leave it there for today, thanks Farah, that was a good session.
"""

print(f"Transcript length: {len(TRANSCRIPT)} chars, ~{len(TRANSCRIPT.split())} words")


async def main():
    cqc_standards = [dict(r) for r in sc.get_system("cqc")]
    care_cert_standards = [dict(r) for r in sc.get_system("care_cert")]

    tracker = {}
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

    print("\n=== ACTIONS ===")
    for a in result.get("actions", []):
        print("-", a.get("text"))
    print("\n=== RISKS ===")
    for r in result.get("risks", []):
        print("-", r.get("label"), "|", r.get("text", "")[:200])
    print("\n=== LEARNING NEEDS ===")
    for ln in result.get("learning_needs", []):
        print("-", ln.get("text"))
    print("\n=== ACHIEVEMENTS ===")
    for ac in result.get("achievements", []):
        print("-", ac.get("text") if isinstance(ac, dict) else ac)

    full_text = json.dumps(result).lower()
    print("\nMentions 'photo':", "photo" in full_text)
    print("Mentions 'camera':", "camera" in full_text)
    print("Mentions 'consent' (re: photo):", "consent" in full_text)


if __name__ == "__main__":
    asyncio.run(main())
