import os
import json
import logging
import uuid
import asyncio
import subprocess
import tempfile
from openai import AsyncOpenAI
from deepgram import DeepgramClient

logger = logging.getLogger(__name__)


async def _openai_chat(model: str, system: str, user: str, reasoning_effort: str = None, timeout_secs: int = 360) -> str:
    """Single-shot OpenAI chat completion — direct to OpenAI, no proxy."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    import httpx
    client = AsyncOpenAI(api_key=api_key, timeout=httpx.Timeout(timeout_secs, connect=10.0))
    messages: list = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    kwargs: dict = {"model": model, "messages": messages}
    if reasoning_effort and model.startswith("o"):
        kwargs["reasoning_effort"] = reasoning_effort
    else:
        kwargs["temperature"] = 0.3
    response = await client.chat.completions.create(**kwargs)
    return (response.choices[0].message.content or "").strip()

# UK adult social care terminology — fed to Deepgram nova-3-medical keyterm prompting
# to reduce misrecognitions on domain-specific language (up to 100 terms supported)
CARE_KEYTERMS = [
    "CQC", "Care Quality Commission", "Care Certificate", "safeguarding",
    "Mental Capacity Act", "MCA", "deprivation of liberty", "DoLS",
    "Liberty Protection Safeguards", "LPS", "Lasting Power of Attorney", "LPA",
    "duty of candour", "Regulation 9", "Regulation 12", "Regulation 17",
    "Regulation 18", "Regulation 20", "Person-centred care", "best interests",
    "risk assessment", "care plan", "pressure ulcer", "tissue viability",
    "dysphagia", "DNACPR", "advance care plan", "catheter", "stoma",
    "moving and handling", "manual handling", "medication management",
    "controlled drugs", "MUST score", "malnutrition", "nutrition and hydration",
    "fluid balance", "falls prevention", "dementia", "learning disability",
    "autism", "positive behaviour support", "restrictive practice",
    "least restrictive", "safeguarding adult review", "SAR", "whistleblowing",
    "registered manager", "nominated individual", "quality assurance",
    "mock inspection", "provider information return", "statement of purpose",
    "supervision", "appraisal", "competency", "mandatory training",
    "Skills for Care", "CPD", "NVQ", "QCF diploma", "reablement",
    "domiciliary care", "supported living", "extra care", "palliative care",
    "end of life", "SBAR", "incident report", "near miss", "RIDDOR",
    "keyworker", "named worker", "social worker", "occupational therapist",
    "district nurse", "integrated care board", "continuing healthcare",
]


def _ms_to_mmss(ms: int) -> str:
    """Convert milliseconds to MM:SS display string."""
    s = int(ms) // 1000
    return f"{s // 60:02d}:{s % 60:02d}"


def _compress_to_mp3(audio_data: bytes, input_suffix: str) -> bytes:
    """Compress audio to 16 kHz mono 32 kbps MP3 — optimal for voice, ~7 MB per 30 min.

    Also trims leading and trailing silence (>=1 s at -50 dBFS) to prevent
    AssemblyAI hallucinations during dead air at the start/end of a recording.
    Internal silence gaps are NEVER removed so AssemblyAI timestamps stay accurate.
    """
    import imageio_ffmpeg
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.NamedTemporaryFile(suffix=input_suffix, delete=False) as f:
        f.write(audio_data)
        inp = f.name
    out = inp + ".mp3"
    # Silence-trim filter: remove leading silence, then reverse+trim+reverse to remove
    # trailing silence. start_periods=1 (no start_duration) stops trimming the instant
    # the first non-silent sample is found — internal gaps are never touched.
    silence_filter = (
        "silenceremove=start_periods=1:start_threshold=-40dB,"
        "areverse,"
        "silenceremove=start_periods=1:start_threshold=-40dB,"
        "areverse"
    )
    try:
        result = subprocess.run(
            [
                ffmpeg_exe, "-i", inp,
                "-vn",                  # drop any video stream
                "-af", silence_filter,  # trim leading/trailing silence only
                "-ar", "16000",         # 16 kHz — optimal for speech recognition
                "-ac", "1",             # mono
                "-b:a", "32k",          # 32 kbps bitrate
                out, "-y", "-loglevel", "error",
            ],
            capture_output=True,
            timeout=180,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg compression failed: {result.stderr.decode()}")
        with open(out, "rb") as f:
            compressed = f.read()
        logger.info(
            "Audio compressed: %.1f KB → %.1f KB (silence trimmed from start/end)",
            len(audio_data) / 1024,
            len(compressed) / 1024,
        )
        return compressed
    finally:
        os.unlink(inp)
        if os.path.exists(out):
            os.unlink(out)

ANALYSIS_SYSTEM_PROMPT = """You are a compliance evidence specialist for UK adult social care providers.
Your task is to analyse supervision meeting transcripts and identify evidence of worker competency and organisational compliance with CQC regulations, Care Certificate standards, and any additional custom standards provided.

EVIDENCE FRAMEWORK — apply this reasoning before mapping anything:
Workers and managers rarely cite regulations by name. Evidence is present when participants:
  1. DESCRIBE PRACTICE — narrate what they do or did in a real situation: "I always check the care plan first", "When that happened I spoke to the family straightaway". This is direct competency evidence — treat it as such.
  2. EXPLAIN REASONING — justify their actions or decisions: "I asked her first because she can make that decision for herself" demonstrates Mental Capacity Act / best-interests understanding even without naming the Act.
  3. CONFIRM OBSERVATION — a manager verifies what they have seen: "I've noticed you always...", "You handled that situation really well" — this is third-party verification of practice.
  4. IDENTIFY A LEARNING NEED — a gap or development area is named: "I'm not confident about X yet" evidences self-awareness and ongoing professional development (maps to Care Certificate Standard 2).
Do NOT require speakers to name a regulation or standard. Map based on what they describe, demonstrate, or understand.
Care Certificate standards describe competencies workers should DEMONSTRATE in practice. A worker narrating a real practice example is the strongest possible evidence — map it generously but accurately to the most specific sub-outcome ref.

Your output must be valid JSON only (no markdown, no extra text) in this exact structure:
{
  "summary": "Two opening sentences that set context and introduce the session (who, when, what type of meeting).\\n\\n- Key topic or discussion point one\\n- Key topic or discussion point two\\n- Key topic or discussion point three\\n- Key topic or discussion point four\\n- Key topic or discussion point five\\n\\nTwo closing sentences that frame the essential outcomes, any overall themes or next steps from the session.",
  "achievements": [
    {"id": "ach_1", "description": "Brief description of a specific thing done well, demonstrated, or grown in (max 25 words)"}
  ],
  "actions": [
    {"id": "unique_id", "text": "action description — a concrete task or follow-up to be completed before the next session (do NOT include identified learning needs here)", "assigned_to": "person name or null", "due_date": "date mentioned or null"}
  ],
  "learning_needs": [
    {"id": "ln_1", "text": "specific knowledge or skill gap identified in this session that needs to be addressed through learning, training or development", "assigned_to": "person name or null", "due_date": "date mentioned or null"}
  ],
  "risks": [
    {
      "id": "unique_id",
      "text": "concise risk or concern description (max 20 words)",
      "severity": "high|medium|low",
      "transcript_excerpt": "exact short quote from the transcript that evidences this risk (max 60 words)",
      "suggested_resolutions": [
        "specific actionable suggestion one",
        "specific actionable suggestion two"
      ]
    }
  ],
  "cqc_mappings": [
    {
      "id": "cqc_1",
      "regulation_ref": "Regulation 18",
      "regulation_name": "Staffing",
      "evidence_summary": "Brief description of evidence",
      "transcript_excerpt": "Exact quote from transcript",
      "confidence": "likely_evidence|possible_evidence"
    },
    {
      "id": "cqc_2",
      "regulation_ref": "QS Caring 1",
      "regulation_name": "Kindness, compassion and dignity",
      "evidence_summary": "Brief description of evidence",
      "transcript_excerpt": "Exact quote from transcript",
      "confidence": "likely_evidence|possible_evidence"
    }
  ],
  "care_cert_mappings": [
    {
      "id": "unique_id",
      "standard_ref": "Standard 2",
      "standard_name": "Your personal development",
      "outcome_ref": "2.1a",
      "outcome_name": "Describe the processes for identifying own learning needs",
      "evidence_summary": "Brief description of evidence",
      "transcript_excerpt": "Exact quote from transcript",
      "confidence": "likely_evidence|possible_evidence"
    }
  ],
  "custom_mappings": [
    {
      "id": "unique_id",
      "document_id": "the document_id provided",
      "document_name": "Company Values Policy",
      "criterion_ref": "CV-1",
      "criterion_name": "Compassion",
      "evidence_summary": "Brief description of evidence",
      "transcript_excerpt": "Exact quote from transcript",
      "confidence": "likely_evidence|possible_evidence"
    }
  ]
}

Rules:
- Map evidence that is described, demonstrated, or shown through practice narration, explained reasoning, or confirmed observation. Do NOT require speakers to name the regulation or standard — map what they describe doing or understanding.
- For CQC mappings, use `regulation_ref` for BOTH Regulations (e.g. "Regulation 18") AND Quality Statements (e.g. "QS Caring 1", "QS Safe 3", "QS Well-led 2"). Quality Statements are first-class evidence items — map to them whenever the described behaviour matches, even if no Regulation is also applicable. Do not restrict mappings to Regulations only.
- EVIDENCE CONFIDENCE — the MANDATORY DEFAULT for every mapping is "possible_evidence". Use "likely_evidence" ONLY when the evidence is rich, specific, and could stand alone in front of a regulator without further context. Do NOT use "possible_evidence" — it no longer exists. The ONLY valid output values are: likely_evidence, possible_evidence. YOUR ROLE IS TO SURFACE, NOT TO DECIDE: if there is any plausible connection to a standard, create the mapping as "possible_evidence" and let the manager decide. A missed piece of compliance evidence is worse than one a manager clicks reject on.
  ALWAYS use "possible_evidence" when ANY of the following are true (this covers the majority of mappings):
  - The worker agrees with or confirms something the manager says, rather than describing their own action
  - The worker describes general awareness of a policy, procedure, or value without showing specific application
  - The worker says what they "usually" or "normally" do — not what they actually did in a named situation
  - The worker describes a situation but is vague, incomplete, or passive about what action they personally took
  - The manager gives general praise without describing specific observed behaviour
  - Any minimising, hedging, or uncertain language is present: "probably", "I think", "I suppose", "I'm not sure if", "I thought about it", "maybe I should have"
  - One key piece of detail is missing that would confirm full competency
  - The evidence is relevant and interesting but requires a follow-up question to confirm
  Use "likely_evidence" ONLY when ALL FIVE of these are simultaneously true — and be strict:
  (a) The worker narrates a specific, real situation that already occurred — named, concrete, not hypothetical
  (b) The worker explicitly states what THEY personally did or decided in that situation
  (c) Their described action is clearly consistent with best practice — specific, purposeful, complete, not passive
  (d) The excerpt could be presented to a CQC inspector as standalone evidence with no further questioning
  (e) There is no minimising, hedging, or qualifying language anywhere in the relevant passage
  When in doubt: possible_evidence. Err heavily toward possible_evidence. It is far better to surface something for the manager to review than to silently discard it.
  IMPORTANT: Agreeing with the manager, describing awareness of a policy, or saying what they would normally do does NOT pass condition (a). These must always be "possible_evidence".
  IMPORTANT: If the worker uses minimising or dismissive language when describing the situation or their response (e.g. "it was probably nothing", "I didn't think I needed to", "I suppose I should have"), the evidence CANNOT be "likely_evidence" — use "possible_evidence" regardless of other content.
- For Care Certificate mappings, ALWAYS map to the most specific sub-outcome ref (e.g. "2.1a", "2.2h", "13.9c"). Use the exact sub-outcome ref and its description as provided in the standards context below. One evidence item = one sub-outcome ref. Create separate mapping entries if evidence covers multiple sub-outcomes.
- For custom_mappings, only include entries if there are custom standards provided AND there is actual evidence. Use the document_id exactly as provided.
- If no custom standards are provided, return custom_mappings as an empty array []
- If the meeting had paused sections, note this in the summary
- For ACHIEVEMENTS: Extract 1–5 specific moments of genuinely good practice, personal or professional growth, positive skill demonstration, or care quality from the transcript. These surface what went well — not general praise. Include: manager compliments on a specific skill or action, worker self-reflection on something they handled well, described best practice narrated by the worker, or improvement since a previous session explicitly noted. Do NOT fabricate or infer achievements not grounded in specific statements. Use "id" values like "ach_1", "ach_2". If nothing specific and genuine is present, return an empty array [].
- For LEARNING NEEDS: Extract specific knowledge or skill gaps that were explicitly identified in this session as needing to be addressed through learning, development or training. Include: areas where the worker expressed uncertainty or lack of confidence about a topic or procedure; gaps in understanding identified by the manager; development areas the worker acknowledged they need to work on; topics or procedures the worker hasn't yet learned or needs to refresh. Do NOT include: training already completed or confirmed as done, general tasks or follow-ups (those go in actions), risks or safeguarding concerns. Do NOT place learning needs in the actions array — they belong here only. Use "id" values like "ln_1", "ln_2". If nothing specific is identified, return an empty array [].
- For ACTIONS: list only concrete tasks, follow-ups, or agreed next steps to be completed before the next session. Do NOT include identified learning needs here — those belong in learning_needs only.
- If the transcript contains [MM:SS] timestamps, include the timestamp at the start of transcript_excerpt values (e.g. "[14:32] I always check the care plan before..."). This helps locate evidence within the session.
- Include transcript excerpts as exact quotes from the provided text
- Generate unique IDs for each item (e.g. "action_1", "risk_1", "cqc_1", "cc_1", "custom_1")
- Summary format MUST follow exactly: two intro sentences, then a blank line, then 4-6 bullet points each starting with "- ", then a blank line, then two closing sentences. Use \\n\\n to separate sections.
- For RISKS: when a worker describes noticing a concern but failing to escalate, record, or act on it appropriately, the risk text must capture the ACTION GAP — not just the underlying concern. Frame it as what was missed or what requires follow-up (e.g. "Possible welfare indicator noted but not escalated or recorded — requires investigation" rather than "potential self-harm risk"). The suggested_resolutions must include both the immediate escalation action AND a training implication for the worker who missed it.
- For RISKS: detect MINIMISING OR DISMISSIVE LANGUAGE — when the supervisee uses language that downplays, dismisses, hedges about, or normalises a concern, incident, or their own actions, even when they do not present it as a problem. This pattern is significant in supervision because it may indicate: a safeguarding or practice concern being rationalised away; a worker not recognising the seriousness of something they witnessed or failed to act on; suppressed welfare need disguised as reassurance; or a decision not to escalate that the worker is now softening in retrospect. Specific patterns to flag:
  (a) Minimising a concern or incident: "it was nothing", "it seemed minor", "probably not that important", "I didn't think it was a big deal", "it was just a small thing", "I don't think it really counts as..."
  (b) Hedging about their own response or decision not to act: "I probably should have...", "I suppose I could have...", "I wasn't sure if I needed to...", "I thought about it but...", "it might have been worth reporting"
  (c) Rationalised inaction — describing a decision not to report, escalate, or record something, accompanied by language that minimises or explains away the significance of that decision
  (d) Dismissing their own welfare when context suggests otherwise: "I'm fine really", "I can manage", "it's not that bad" — especially if repeated or contradicted by other signals in the session
  Generate a risk at medium severity with label "Minimising language — further investigation needed". The risk text should name what was being minimised or dismissed (e.g. "Supervisee used minimising language when describing [the incident / their decision not to report / their wellbeing] — it is not yet clear whether the full significance of this was recognised. The manager should probe further before closing this point."). Suggested resolutions: follow-up questions at next supervision or sooner, consider whether a formal record or incident report is required, flag pattern to safeguarding lead if a safeguarding matter was involved. Flag these as risks regardless of whether an action was already agreed in the meeting. Specific patterns to watch for: expressing tiredness, exhaustion, or fatigue (especially if mentioned more than once — repetition is itself a signal of severity); describing feeling overwhelmed, stressed, or unable to cope; expressing general emotional distress or low mood about their work. IMPORTANT DISTINCTION: a worker saying "I felt bad for not doing X" or "I should have reported that" is NOT a wellbeing signal — that is guilt about a specific action gap and belongs in the action gap risks category. A wellbeing signal is about the person's general personal state (e.g. "I'm really tired", "I've been struggling lately", "I don't feel myself"), NOT about remorse over a specific professional incident. When multiple genuine wellbeing signals appear across the same meeting, generate a single consolidated risk describing the overall pattern rather than individual entries per mention. Use severity "high" if the worker appears distressed or repeats the concern three or more times; "medium" for one or two mentions. Risk text example: "Worker expressed repeated tiredness across the session — potential welfare concern requiring pastoral follow-up." Suggested resolutions should include: pastoral follow-up before next supervision, EAP signposting if not already offered, workload review, and a manager note to monitor.
- For ACTIONS: additionally, when a risk arises from a worker's insufficient response (missed escalation, not recording a concern, not following a protocol), always generate a paired training action item assigned to the supervisor — not just an action on the concern itself. This ensures supervision gaps are captured, not just clinical risks.
|- For RISKS — CONCERNING COMMUNICATION PATTERNS: Beyond explicit content risks, also detect the following patterns in HOW the worker communicates. These are clinically significant even when no explicit concern is raised — they indicate the supervisory relationship may not be functioning as a genuine safe-disclosure space, or that something is being managed rather than surfaced. Flag each as a separate risk entry. Use the prefix "Communication pattern — " in the risk text. Default severity: medium (upgrade to high if the pattern repeats or clusters with others in the same session).

  NORMALISATION: The worker describes a situation that is objectively concerning — a near-miss, a safeguarding indicator, a care quality failure — but frames it as routine, unremarkable, or expected. Signals: "that’s just how he is", "it happens a lot in care", "that’s pretty normal for this setting", "most places are like that", "I don’t think it’s unusual". Risk text: "Communication pattern — normalisation: worker described [X] as routine when it warrants scrutiny. This may indicate cultural drift where a concerning practice has become invisible." Suggested resolutions: explore whether this is accepted team practice or individual rationalisation; consider whether a practice review or audit is needed; discuss with the worker what a well-run service would expect as the norm in this situation.

  PREMATURE CLOSURE: The worker claims a situation or concern is resolved ("sorted it", "dealt with it", "all fine now", "she’s settled", "I spoke to them") without describing what was specifically done, by whom, what the outcome was, or how it will be monitored. The resolution is declared, not described. Risk text: "Communication pattern — premature closure: [situation] was described as resolved without a clear account of what was done, by whom, or how it is being monitored." Suggested resolutions: ask the worker to describe exactly what happened next; establish what follow-up is in place; if a concern was involved, confirm it has been formally recorded.

  OVER-CONFIDENCE: The worker expresses categorical certainty in areas that require ongoing vigilance, professional judgement, or situational assessment. Signals: "I always know what to do", "I’ve never had a problem with that", "I don’t need to check — I know", "I’m always careful", "that’s never been an issue for me", or dismissing the need for guidance in a complex situation. Particularly significant for medication, safeguarding recognition, capacity assessment, and clinical observation. Over-confidence suppresses escalation and learning. Risk text: "Communication pattern — over-confidence: worker expressed unqualified certainty about [area], which warrants ongoing professional judgement and oversight." Suggested resolutions: explore the basis for the confidence (training, experience, recent practice); test with a specific recent example; ensure the worker understands the limits of their competence in this area and the expectation to seek guidance.

  DEFLECTION: The manager poses a direct question or raises a specific concern — and the worker responds with something tangential, pivots to another topic, introduces unrelated context, or never directly addresses what was asked. The absence of a direct answer is itself the evidence. This may indicate the worker doesn’t know and doesn’t want to admit it, is uncomfortable with the topic, or is avoiding accountability for a specific event. Risk text: "Communication pattern — deflection: manager raised [topic/question] and the worker did not respond directly; this concern may not have been fully explored." Suggested resolutions: return to the unanswered question directly at next supervision or sooner; explore whether the worker understood what was being asked; consider whether this avoidance is consistent across topics.

  GLOSSING OVER: A worker gives a response that is disproportionately brief or superficial relative to the significance of the topic — a one-sentence reply to a safeguarding concern, "yeah, fine" after being asked about a difficult incident, or a brief positive gloss ("it all worked out") after describing something that should prompt detailed discussion. The signal is not just what was said — it is the mismatch between the gravity of the subject and the depth of the response. Risk text: "Communication pattern — insufficient engagement: worker gave a brief or surface-level response to [significant topic]; it is not yet clear whether this was adequately explored." Suggested resolutions: return to this topic with a direct open question; consider whether brevity reflects discomfort, uncertainty, or a desire to close it down; probe with "tell me more about what happened" or "what was going through your mind at that point".

  BEATING AROUND THE BUSH / INDIRECT DISCLOSURE: The worker circles a topic repeatedly without directly naming it — uses vague references, hypotheticals, or third-party framing to approach something they appear reluctant to say directly. Signals: "there’s kind of a situation with someone", "I don’t know if this is relevant but…", "not that I’m saying it’s a big deal, but…", describing something hypothetically that sounds like a real event. This pattern often precedes an indirect disclosure of a concern the worker does not feel safe to raise openly. Risk text: "Communication pattern — indirect or tentative disclosure: worker may be approaching a concern indirectly; direct follow-up is needed to establish whether something specific occurred." Suggested resolutions: explicitly invite direct disclosure ("it sounds like there might be something specific you want to raise — is there?"); reassure about the purpose and confidentiality of supervision; follow up privately if the transcript suggests the worker did not feel safe to disclose in the moment.

  FALSE RESOLUTION / OVER-REASSURANCE: Distinct from premature closure — this is where the worker describes addressing a situation through a verbal-only or social intervention, presented as if it constitutes full resolution. Signals: "I had a chat with her about it", "I made it clear", "I told them not to do that again", "they know now" — particularly when the situation involved a safeguarding concern, a care quality issue, or a policy breach. A conversation is not a formal record. Acknowledgement is not a change in practice. Risk text: "Communication pattern — informal resolution: worker described addressing [concern] through a conversation only; it is not clear whether a formal record, escalation, or care plan update was needed." Suggested resolutions: clarify whether a formal record was made; establish whether the matter required escalation (incident report, safeguarding referral, care plan update); explore whether the worker understands the difference between informal and formal resolution.

  PATTERN CLUSTERING: When two or more of these communication patterns appear within the same supervision session, add a note to one of the risk entries: "Multiple communication patterns identified in this session (specify which). Pattern clustering is itself a significant signal — it may indicate the supervisory relationship is not functioning as a safe-disclosure space, or that the worker is managing something they are not ready or willing to name. The manager should review the session as a whole before closing it."
"""


CRITERIA_EXTRACTION_PROMPT = """You are reviewing a standards/policy document from a UK adult social care provider. Extract a structured list of criteria, standards, or competencies from this document.

Return valid JSON only (no markdown) in this exact structure:
{
  "document_summary": "One concise sentence describing what this document covers",
  "criteria": [
    {"ref": "1", "name": "Short criterion name (3-8 words)", "description": "What this criterion expects — one to two sentences"}
  ]
}

Rules:
- Extract between 3 and 20 criteria maximum
- Each criterion should be a distinct, assessable standard or expectation
- Use sequential numbering for refs (1, 2, 3...)
- If the document is a job description, extract key competencies and responsibilities
- If it is a values/policy document, extract each named value or principle
- If it is a competency framework, extract each competency domain
- Be concise and practical — these will be used to assess evidence in supervision meetings"""


CARE_TRANSCRIPTION_PROMPT = (
    "CQC, Care Quality Commission, safeguarding, mental capacity, Mental Capacity Act, "
    "DoLS, Deprivation of Liberty Safeguards, person-centred care, risk assessment, "
    "care plan, supervision, competency, clinical governance, NICE guidelines, "
    "medication management, manual handling, infection control, safeguarding adults, "
    "SOVA, MAPPA, MARAC, whistleblowing, duty of care, Disclosure and Barring Service, "
    "DBS, NMC, RCN, well-led, safe, effective, caring, responsive, KLOE, "
    "personal development plan, PDP, capacity assessment, best interest decision, "
    "consent, dignity, MCA, deprivation of liberty, restrictive practice, "
    "mental health, dementia, learning disability, autism, care worker, key worker"
)

DIARIZATION_SYSTEM_PROMPT = """You are a transcript formatter for supervision meetings in UK adult social care.
Your task is to add speaker labels to a raw speech-to-text transcript.

Format each speaker turn on its own line as:
SPEAKER_LABEL: spoken words

Rules:
- Use ONLY the exact names/labels supplied in the participant list
- Match speakers using all available contextual clues:
    * Who asks supervisory questions vs who discusses their own practice
    * Direct address (e.g. "So, Sarah, how has your week been?")
    * Name mentions and self-references
    * Topic ownership — the supervisor steers the agenda; supervisees report on their work
    * Changes in register, formality or topic signal a speaker change
    * Turn length — the supervisor typically asks shorter questions or prompts; the worker typically speaks for longer when describing their practice or experiences
- When there are 3 or more participants, give each person their own label — do NOT merge a third person into one of the other two
- Start each new speaker turn on a fresh line
- Preserve ALL original words exactly as transcribed — do not paraphrase, correct, or add any words
- If a turn cannot be confidently attributed to any named participant, use "Speaker:" as a fallback
- Output ONLY the formatted transcript — no preamble, explanation, commentary or markdown"""


# ── Deepgram speaker-number → real name mapping prompt ────────────────────
SPEAKER_MAPPING_SYSTEM_PROMPT = """You are a transcript editor for supervision meetings in UK adult social care.
The audio has already been diarized — speakers are labelled generically (e.g. Speaker A, Speaker B, Speaker 0, Speaker 1).
Each turn is prefixed with a [MM:SS] timestamp. Your task is to replace the generic labels with real participant names.

Rules:
- Identify which labelled speaker corresponds to which named participant by reading the conversation
- The manager/supervisor steers the agenda, asks questions about the worker's practice, and conducts the meeting
- The worker/supervisee reports on their own work and development
- Use turn duration as a signal: short turns (under 15 seconds apart) are typically manager questions or prompts; longer turns are typically the worker explaining their practice
- PRESERVE the [MM:SS] timestamp at the start of each line exactly as-is — only replace the speaker label: [MM:SS] Speaker A: text → [MM:SS] RealName: text
- Do NOT change any spoken words — only replace the speaker label
- If there are more labelled speakers than named participants (e.g. crosstalk artefacts), assign them to the closest matching participant
- Output ONLY the reformatted transcript — no preamble, explanation, or markdown"""


def _check_transcript_safety(plain_text: str, transcript) -> list[str]:
    """
    Returns a list of warning strings if the transcript contains
    repetition hallucination patterns (looping phrases — classic ASR failure).
    AssemblyAI content_safety is disabled; we rely only on hallucination detection.
    """
    import re
    warnings = []

    # --- Repetition / hallucination detector ---
    # Split into sentences and check for excessive repetition
    if plain_text:
        sentences = [s.strip() for s in re.split(r'[.!?]', plain_text) if len(s.strip()) > 5]
        if len(sentences) >= 4:
            from collections import Counter
            counts = Counter(s.lower() for s in sentences)
            most_common_text, most_common_count = counts.most_common(1)[0]
            # If any single sentence appears 3+ times in a row it's very likely a hallucination
            if most_common_count >= 3:
                warnings.append(
                    f"Possible hallucination detected: the phrase \"{most_common_text[:80]}\" "
                    f"appears {most_common_count} times — please review before sharing."
                )

        # Check for consecutive repeated short phrases (tighter looping pattern)
        words = plain_text.lower().split()
        if len(words) >= 10:
            chunk_size = 6
            chunks = [" ".join(words[i:i+chunk_size]) for i in range(0, len(words) - chunk_size, chunk_size)]
            for i in range(len(chunks) - 2):
                if chunks[i] == chunks[i+1] == chunks[i+2]:
                    warnings.append(
                        f"Looping repetition detected near: \"{chunks[i][:80]}\" — likely an AI hallucination."
                    )
                    break

    return warnings


async def transcribe_with_assemblyai(audio_data: bytes, speakers_expected: int = None) -> tuple:
    """
    Transcribe + diarise with AssemblyAI (Universal model, speaker_labels=True).
    Works reliably on mono audio from browser MediaRecorder.
    Returns (plain_text, speaker_labeled_text_or_none).
    speaker_labeled_text uses "Speaker A:", "Speaker B:" labels.
    Falls back to None if only 1 speaker found (GPT-4o will diarise from text).
    Pass speakers_expected (from meeting attendee count) to improve diarization accuracy.
    """
    import io
    import assemblyai as aai

    api_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not api_key:
        raise ValueError("ASSEMBLYAI_API_KEY not configured")

    aai.settings.api_key = api_key
    aai.settings.base_url = "https://api.eu.assemblyai.com"  # EU data residency (Dublin)

    config = aai.TranscriptionConfig(
        speaker_labels=True,
        speakers_expected=speakers_expected if speakers_expected and speakers_expected >= 2 else None,
        speech_models=["universal-3-5-pro", "universal-2"],  # Latest EU-available models
        language_detection=True,
        content_safety=False,              # Disabled — over-flags benign care sector discussions
        word_boost=[                        # Reinforce UK adult social care terminology
            "CQC", "safeguarding", "MCA", "DoLS", "LPS", "Care Certificate",
            "duty of candour", "deprivation of liberty", "best interests",
            "risk assessment", "care plan", "pressure ulcer", "dysphagia",
            "DNACPR", "mental capacity", "lasting power of attorney",
            "medication management", "moving and handling", "tissue viability",
            "registered manager", "nominated individual", "Skills for Care",
            "mandatory training", "supervision", "appraisal", "competency",
            "safeguarding lead", "whistleblowing", "quality assurance",
        ],
    )
    transcriber = aai.Transcriber()

    loop = asyncio.get_event_loop()
    hint_msg = f", speakers_expected={speakers_expected}" if speakers_expected else ""
    logger.info(f"Sending {len(audio_data) / 1024:.1f} KB to AssemblyAI (speaker_labels=True{hint_msg})")

    transcript = await loop.run_in_executor(
        None,
        lambda: transcriber.transcribe(io.BytesIO(audio_data), config=config),
    )

    if transcript.status == aai.TranscriptStatus.error:
        raise ValueError(f"AssemblyAI transcription failed: {transcript.error}")

    plain_text = transcript.text or ""
    logger.info(f"AssemblyAI transcription complete: {len(plain_text)} chars")

    # --- Content safety & hallucination checks ---
    warnings = _check_transcript_safety(plain_text, transcript)
    if warnings:
        logger.warning(f"Transcript safety flags for this recording: {warnings}")

    if transcript.utterances:
        unique_speakers = {u.speaker for u in transcript.utterances}
        logger.info(f"AssemblyAI found {len(unique_speakers)} speaker(s): {sorted(unique_speakers)}")

        if len(unique_speakers) > 1:
            lines = [f"[{_ms_to_mmss(u.start)}] Speaker {u.speaker}: {u.text}" for u in transcript.utterances]
            speaker_text = "\n".join(lines)
            # Build a timestamped version of the plain text for analysis (no speaker labels — diarization runs in parallel)
            ts_lines = [f"[{_ms_to_mmss(u.start)}] {u.text}" for u in transcript.utterances]
            timestamped_plain = "\n".join(ts_lines)
            logger.info("AssemblyAI diarization usable — GPT-4o will map names only")
            return plain_text, speaker_text, timestamped_plain, warnings

    logger.info("AssemblyAI found only 1 speaker — GPT-4o will diarise from text")
    return plain_text, None, plain_text, warnings


async def transcribe_with_deepgram(audio_data: bytes) -> tuple:
    """
    Transcribe with Deepgram nova-3-medical + diarization attempt.
    Returns (plain_text, numbered_speaker_text_or_none).

    Hybrid strategy:
    - Deepgram acoustic diarization is requested for every call.
    - If Deepgram finds > 1 unique speaker, numbered_speaker_text is returned
      (e.g. "Speaker 0: ...\nSpeaker 1: ...") and GPT-4o only maps names.
    - If Deepgram collapses to 1 speaker (common on mono/browser MediaRecorder
      audio), numbered_speaker_text is None and GPT-4o does full text diarization.
    """
    api_key = os.environ.get("DEEPGRAM_API_KEY")
    if not api_key:
        raise ValueError("DEEPGRAM_API_KEY not configured")

    client = DeepgramClient(api_key=api_key)
    loop = asyncio.get_event_loop()

    logger.info(f"Sending {len(audio_data) / 1024:.1f} KB to Deepgram nova-3-medical (diarize=True)")

    response = await loop.run_in_executor(
        None,
        lambda: client.listen.v1.media.transcribe_file(
            request=audio_data,
            model="nova-3-medical",
            smart_format=True,
            punctuate=True,
            diarize=True,
            utterances=True,
            keyterm=CARE_KEYTERMS,
        ),
    )

    if not response or not response.results:
        raise ValueError("Deepgram returned empty results")

    plain_text = (
        response.results.channels[0].alternatives[0].transcript
        if response.results.channels else ""
    )

    # Check whether Deepgram acoustically found multiple speakers
    utterances = getattr(response.results, "utterances", None) or []
    if utterances:
        unique_speakers = {u.speaker for u in utterances}
        speaker_count = len(unique_speakers)
        logger.info(f"Deepgram found {speaker_count} speaker(s) across {len(utterances)} utterances")

        if speaker_count > 1:
            lines = [f"Speaker {u.speaker}: {u.transcript}" for u in utterances]
            numbered_speaker_text = "\n".join(lines)
            logger.info("Deepgram diarization usable — GPT-4o will map names only")
        else:
            numbered_speaker_text = None
            logger.info("Deepgram found only 1 speaker (likely mono audio) — GPT-4o will diarise from text")
    else:
        numbered_speaker_text = None
        logger.info("Deepgram returned no utterances — GPT-4o will diarise from text")

    return plain_text, numbered_speaker_text


# Keep the old combined function for potential future use (e.g. multi-channel audio)
async def transcribe_and_diarize_deepgram(audio_data: bytes) -> tuple:
    """
    Transcribe audio with Deepgram Nova-3 + built-in speaker diarisation.
    Returns (plain_transcript_text, numbered_speaker_text) or raises on failure.
    numbered_speaker_text uses "Speaker 0:", "Speaker 1:" labels.
    """
    api_key = os.environ.get("DEEPGRAM_API_KEY")
    if not api_key:
        raise ValueError("DEEPGRAM_API_KEY not configured")

    client = DeepgramClient(api_key=api_key)
    loop = asyncio.get_event_loop()

    logger.info(f"Sending {len(audio_data) / 1024:.1f} KB to Deepgram Nova-3 with diarization")

    response = await loop.run_in_executor(
        None,
        lambda: client.listen.v1.media.transcribe_file(
            request=audio_data,
            model="nova-3",
            diarize=True,
            utterances=True,
            smart_format=True,
            punctuate=True,
        ),
    )

    if not response or not response.results:
        raise ValueError("Deepgram returned empty results")

    # Plain transcript (for analysis)
    plain_text = response.results.channels[0].alternatives[0].transcript if response.results.channels else ""

    # Numbered speaker text (from utterances)
    if response.results.utterances:
        lines = [f"Speaker {u.speaker}: {u.transcript}" for u in response.results.utterances]
        numbered_speaker_text = "\n".join(lines)
        speaker_count = len({u.speaker for u in response.results.utterances})
        logger.info(f"Deepgram identified {speaker_count} speaker(s), {len(response.results.utterances)} utterances")
    else:
        # No utterances — return None so the caller falls back to GPT-4o text diarization
        logger.warning("Deepgram returned no utterances; will fall back to GPT-4o diarization")
        numbered_speaker_text = None

    return plain_text, numbered_speaker_text


async def map_speaker_numbers_to_names(
    numbered_speaker_text: str,
    manager_name: str = "Manager",
    attendee_names: list = None,
    meeting_type: str = "Supervision",
) -> str:
    """Use GPT-4o to replace 'Speaker 0/1/2' labels with real participant names."""
    if not numbered_speaker_text.strip():
        return numbered_speaker_text

    participants = []
    manager_label = manager_name or "Manager"
    participants.append(f"- {manager_label} (Manager/Supervisor — conducts the meeting, asks questions)")
    if attendee_names:
        for name in attendee_names:
            if name and name.lower() != manager_label.lower():
                participants.append(f"- {name} (Worker/Attendee)")
    else:
        participants.append("- Worker (Worker/Attendee)")

    participants_block = "\n".join(participants)

    user_prompt = (
        f"Meeting type: {meeting_type}\n\n"
        f"PARTICIPANTS:\n{participants_block}\n\n"
        f"NUMBERED TRANSCRIPT (replace generic labels with real names):\n{numbered_speaker_text}"
    )

    try:
        result = await _openai_chat("gpt-4o", SPEAKER_MAPPING_SYSTEM_PROMPT, user_prompt)
        return result if result else numbered_speaker_text
    except Exception as e:
        logger.error(f"Speaker name mapping failed: {e}")
        return numbered_speaker_text  # Fall back to numbered labels


async def diarize_transcript(
    transcript_text: str,
    manager_name: str = "Manager",
    attendee_names: list = None,
    meeting_type: str = "Supervision",
) -> str:
    """Use GPT-4o to add speaker labels to an AssemblyAI transcript. Returns None on failure."""
    if not transcript_text.strip():
        return None

    # Build a named participant list for the prompt
    participants = []
    manager_label = manager_name or "Manager"
    participants.append(f"- {manager_label} (Manager/Supervisor — conducts the meeting, asks questions, steers the agenda)")

    if attendee_names:
        for name in attendee_names:
            if name and name.lower() != manager_label.lower():
                participants.append(f"- {name} (Attendee/Worker — discusses their own practice and development)")
    else:
        participants.append("- Worker (Attendee/Worker — discusses their own practice and development)")

    participants_block = "\n".join(participants)

    # Build comma-separated label hint for the instruction line
    all_labels = [manager_label] + [n for n in (attendee_names or []) if n and n.lower() != manager_label.lower()]
    label_hint = " / ".join(f"{lbl}:" for lbl in all_labels)

    user_prompt = (
        f"Meeting type: {meeting_type}\n\n"
        f"PARTICIPANTS ({len(participants)} people):\n{participants_block}\n\n"
        f"RAW TRANSCRIPT:\n{transcript_text}\n\n"
        f"Reformat the transcript above, labelling every turn with the correct speaker "
        f"({label_hint} or Speaker: if unsure). "
        f"There are {len(participants)} distinct participants — assign turns to all of them as appropriate."
    )

    try:
        result = await _openai_chat("gpt-4o", DIARIZATION_SYSTEM_PROMPT, user_prompt)
        return result if result else None
    except Exception as e:
        logger.error(f"Speaker diarization failed: {e}")
        return None


async def extract_document_criteria(text: str, doc_name: str) -> dict:
    """Ask GPT-4o to extract a structured list of criteria from a document."""
    truncated = text[:8000]  # Stay well within token budget
    user_prompt = f"Document name: {doc_name}\n\nDocument content:\n{truncated}"

    full_response = await _openai_chat("gpt-4o", CRITERIA_EXTRACTION_PROMPT, user_prompt)

    try:
        text_resp = full_response.strip()
        if text_resp.startswith("```"):
            lines = text_resp.split("\n")
            text_resp = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
        return json.loads(text_resp)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse criteria extraction response: {e}")
        return {"document_summary": doc_name, "criteria": []}


async def analyze_custom_only(transcript_text: str, doc: dict) -> list:
    """Light o4-mini call: map evidence from transcript against a single document's criteria only."""
    doc_id = str(doc.get("id", doc.get("_id", "")))
    doc_name = doc.get("label") or doc.get("filename", "Unknown")
    criteria = doc.get("extracted_criteria", [])
    if not criteria or not transcript_text.strip():
        return []

    criteria_ctx = "\n".join([f"  - {c['ref']}: {c['name']} — {c.get('description', '')}" for c in criteria])
    system = """Map evidence from a meeting transcript against provided criteria.
Evidence includes described practice ("I always do X"), explained reasoning ("I did it because..."), manager-confirmed observations, and identified learning needs. You do NOT require the criterion to be named explicitly — map based on what participants describe doing or understanding.
Return valid JSON only:
{"mappings": [{"id": "custom_n", "document_id": "the document_id value", "document_name": "doc name", "criterion_ref": "ref", "criterion_name": "name", "evidence_summary": "brief description", "transcript_excerpt": "exact quote", "confidence": "likely_evidence|possible_evidence"}]}
Only include criteria with actual evidence. Return empty mappings array if nothing found."""

    chat = await _openai_chat("o4-mini", system, f"Document: {doc_name} (document_id: {doc_id})\nCriteria:\n{criteria_ctx}\n\nTranscript:\n{transcript_text[:5000]}", reasoning_effort="high")
    full = chat
    try:
        txt = full.strip()
        if txt.startswith("```"):
            txt = "\n".join(txt.split("\n")[1:-1])
        result = json.loads(txt)
        mappings = result.get("mappings", [])
        for m in mappings:
            m.setdefault("status", "pending")
        return mappings
    except Exception as e:
        logger.error(f"analyze_custom_only parse error: {e}")
        return []


SUMMARY_ONLY_PROMPT = """You are a meeting summarizer for UK adult social care supervision sessions.
Generate a structured meeting summary in EXACTLY this format — three sections separated by blank lines:

Section 1: Two sentences that introduce the session (who was involved, what type of meeting, its main purpose or context).

Section 2: 4 to 6 bullet points covering the key topics and discussion points, each starting with "- ".

Section 3: Two sentences that frame the essential outcomes, overall themes, or agreed next steps from the session.

Output plain text only. Use a blank line (\\n\\n) to separate each of the three sections. Do not use any markdown headers or JSON."""


PII_SCAN_SYSTEM_PROMPT = """You are a PII detection specialist for UK adult social care supervision meeting transcripts.

Identify references to THIRD PARTIES — people NOT present in this meeting — whose identity could be determined from the transcript.

In UK adult social care settings, flag:
- Named service users, residents, or clients (people being cared for)
- Named family members, next-of-kin, carers or friends of service users
- Named colleagues not present in this meeting who are mentioned by name (other staff members, co-workers, team members — regardless of context)
- Any full name combined with sensitive health, financial, or personal details

DO NOT flag:
- The meeting participants (their names are listed below)
- Generic roles without specific names ("the doctor", "a colleague", "the manager")
- Generic references without identifying detail ("a resident", "the service user")
- Organisation names, care home names, or place names alone

Return valid JSON array only — no markdown, no text outside JSON:
[{"original": "exact phrase as it appears in the transcript", "type": "third_party_name|sensitive_personal_detail|contact_detail|address", "replacement": "safe replacement e.g. [Service User], [Family Member], [Colleague], [Resident]", "reason": "one sentence explanation"}]

Return [] if no third-party PII is found.
If the same person appears multiple times, return one entry for their most complete name/reference."""


async def scan_pii_in_transcript(transcript_text: str, attendees: list = None, manager_name: str = "") -> list:
    """Scan transcript for PII using regex (UK patterns) + GPT-4o (third-party names).
    Returns a merged, deduplicated list of flag dicts."""
    import re as _re

    flags = []
    seen_originals: set = set()

    # ── 1. Regex patterns for structured UK PII ──────────────────────────
    regex_patterns = [
        # UK phone numbers (07xxx, 01xxx, 02xxx, +44)
        (r'\b(?:0(?:7\d{9}|[123]\d{8,9})|\+44[\s\-]?\d{2,5}[\s\-]?\d{3,8})\b',
         'contact_detail', '[Phone Number]'),
        # Email addresses
        (r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b',
         'contact_detail', '[Email Address]'),
        # UK postcodes
        (r'\b[A-Z]{1,2}[0-9][0-9A-Z]?\s?[0-9][A-Z]{2}\b',
         'address', '[Postcode]'),
        # National Insurance numbers
        (r'\b[A-CEGHJ-PR-TW-Z]{1}[A-CEGHJ-NPR-TW-Z]{1}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b',
         'sensitive_personal_detail', '[NI Number]'),
        # NHS numbers (10-digit, formatted as 3-3-4 or unformatted)
        (r'\b\d{3}\s\d{3}\s\d{4}\b',
         'sensitive_personal_detail', '[NHS Number]'),
    ]

    for pattern, pii_type, replacement in regex_patterns:
        for match in _re.finditer(pattern, transcript_text, _re.IGNORECASE):
            original = match.group().strip()
            if original and original not in seen_originals:
                seen_originals.add(original)
                flags.append({
                    "id": str(uuid.uuid4())[:8],
                    "original": original,
                    "type": pii_type,
                    "replacement": replacement,
                    "reason": f"Detected {pii_type.replace('_', ' ')} pattern",
                    "source": "regex",
                })

    # ── 2. AI scan for names and sensitive context ────────────────────────
    # Scans the FULL transcript. GPT-4o supports 128K tokens (~500K chars),
    # so even a 3-hour meeting fits in a single call. For extreme outliers
    # we chunk at 40,000 chars and merge results.
    _AI_CHUNK = 40_000   # chars per chunk — covers ~50 min of speech
    _AI_OVERLAP = 300    # overlap to catch names near a boundary

    if transcript_text.strip():
        participant_names: list = []
        if manager_name:
            participant_names.append(manager_name)
        if attendees:
            for a in (attendees or []):
                if isinstance(a, dict) and a.get("name"):
                    participant_names.append(a["name"])

        participant_note = ""
        if participant_names:
            participant_note = f"\n\nMEETING PARTICIPANTS (do NOT flag these): {', '.join(participant_names)}"

        # Build list of chunks (single chunk for most meetings)
        if len(transcript_text) <= _AI_CHUNK:
            chunks = [transcript_text]
        else:
            chunks = []
            start = 0
            while start < len(transcript_text):
                end = min(start + _AI_CHUNK, len(transcript_text))
                # Break at a word boundary so we don't split mid-name
                if end < len(transcript_text):
                    wb = transcript_text.rfind(" ", start + _AI_CHUNK // 2, end)
                    if wb > 0:
                        end = wb
                chunks.append(transcript_text[start:end])
                start = max(start + 1, end - _AI_OVERLAP)

        total_chunks = len(chunks)

        for chunk_idx, chunk_text in enumerate(chunks):
            chunk_label = f" (part {chunk_idx + 1} of {total_chunks})" if total_chunks > 1 else ""
            user_prompt = (
                f"Scan this supervision transcript for third-party PII:{participant_note}\n\n"
                f"TRANSCRIPT{chunk_label}:\n{chunk_text}"
            )

            try:
                full_response = await _openai_chat("gpt-4o", PII_SCAN_SYSTEM_PROMPT, user_prompt)
                text_resp = full_response.strip()
                if text_resp.startswith("```"):
                    lines = text_resp.split("\n")
                    text_resp = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

                ai_flags = json.loads(text_resp)
                if isinstance(ai_flags, list):
                    for flag in ai_flags:
                        original = flag.get("original", "").strip()
                        if original and original not in seen_originals:
                            seen_originals.add(original)
                            flag["id"] = str(uuid.uuid4())[:8]
                            flag["source"] = "ai"
                            flags.append(flag)
            except Exception as e:
                logger.error(f"AI PII scan failed (chunk {chunk_idx + 1}/{total_chunks}): {e}")
                # Continue to next chunk — regex results still returned

    return flags


async def generate_meeting_summary(transcript_text: str) -> str:
    """Re-generate just the meeting summary in the new structured format."""
    user_prompt = f"Summarize this supervision meeting transcript:\n\n{transcript_text[:8000]}"
    return await _openai_chat("o4-mini", SUMMARY_ONLY_PROMPT, user_prompt, reasoning_effort="medium")


DOC_EVIDENCE_SYSTEM_PROMPT = """You are a compliance evidence specialist for UK adult social care providers.
Analyse this supervision document to identify evidence of worker competency and organisational compliance with CQC regulations, Care Certificate standards, and any additional custom standards provided.

Evidence is present when the document contains descriptions of practice, explained reasoning, manager observations, or identified learning needs — not only when standards are cited by name. A written record stating a worker "demonstrates safe medication management" or "explained her approach to consent" is direct competency evidence.

Your output must be valid JSON only (no markdown, no extra text) in this exact structure:
{
  "cqc_mappings": [
    {
      "id": "cqc_1",
      "regulation_ref": "Regulation 18",
      "regulation_name": "Staffing",
      "evidence_summary": "Brief description of evidence found",
      "transcript_excerpt": "Exact quote from the document",
      "confidence": "likely_evidence|possible_evidence"
    },
    {
      "id": "cqc_2",
      "regulation_ref": "QS Safe 3",
      "regulation_name": "Safeguarding",
      "evidence_summary": "Brief description of evidence found",
      "transcript_excerpt": "Exact quote from the document",
      "confidence": "likely_evidence|possible_evidence"
    }
  ],
  "care_cert_mappings": [
    {
      "id": "cc_1",
      "standard_ref": "Standard 2",
      "standard_name": "Your personal development",
      "outcome_ref": "2.1a",
      "outcome_name": "Describe the processes for identifying own learning needs",
      "evidence_summary": "Brief description of evidence found",
      "transcript_excerpt": "Exact quote from the document",
      "confidence": "likely_evidence|possible_evidence"
    }
  ],
  "custom_mappings": [
    {
      "id": "custom_1",
      "document_id": "the document_id provided",
      "document_name": "Company Values Policy",
      "criterion_ref": "CV-1",
      "criterion_name": "Compassion",
      "evidence_summary": "Brief description of evidence found",
      "transcript_excerpt": "Exact quote from the document",
      "confidence": "likely_evidence|possible_evidence"
    }
  ]
}

Rules:
- Map evidence that is described, demonstrated, or recorded in the document — including described practice, noted observations, identified learning needs, or explained reasoning. Do not require the standard or regulation to be named.
- EVIDENCE CONFIDENCE — the MANDATORY DEFAULT for every mapping is "possible_evidence". Use "likely_evidence" ONLY when the evidence is rich, specific, and could stand alone in front of a regulator without further context. Do NOT use "possible_evidence" — it no longer exists. The ONLY valid output values are: likely_evidence, possible_evidence. YOUR ROLE IS TO SURFACE, NOT TO DECIDE: if there is any plausible connection to a standard, create the mapping as "possible_evidence" and let the manager decide. A missed piece of compliance evidence is worse than one a manager clicks reject on.
  ALWAYS use "possible_evidence" when ANY of the following are true (this covers the majority of mappings):
  - The worker agrees with or confirms something the manager says, rather than describing their own action
  - The worker describes general awareness of a policy, procedure, or value without showing specific application
  - The worker says what they "usually" or "normally" do — not what they actually did in a named situation
  - The worker describes a situation but is vague, incomplete, or passive about what action they personally took
  - The manager gives general praise without describing specific observed behaviour
  - Any minimising, hedging, or uncertain language is present: "probably", "I think", "I suppose", "I'm not sure if", "I thought about it", "maybe I should have"
  - One key piece of detail is missing that would confirm full competency
  - The evidence is relevant and interesting but requires a follow-up question to confirm
  Use "likely_evidence" ONLY when ALL FIVE of these are simultaneously true — and be strict:
  (a) The worker narrates a specific, real situation that already occurred — named, concrete, not hypothetical
  (b) The worker explicitly states what THEY personally did or decided in that situation
  (c) Their described action is clearly consistent with best practice — specific, purposeful, complete, not passive
  (d) The excerpt could be presented to a CQC inspector as standalone evidence with no further questioning
  (e) There is no minimising, hedging, or qualifying language anywhere in the relevant passage
  When in doubt: possible_evidence. Err heavily toward possible_evidence. It is far better to surface something for the manager to review than to silently discard it.
  IMPORTANT: Agreeing with the manager, describing awareness of a policy, or saying what they would normally do does NOT pass condition (a). These must always be "possible_evidence".
  IMPORTANT: If the worker uses minimising or dismissive language when describing the situation or their response (e.g. "it was probably nothing", "I didn't think I needed to", "I suppose I should have"), the evidence CANNOT be "likely_evidence" — use "possible_evidence" regardless of other content.
- For Care Certificate mappings, ALWAYS map to the most specific sub-outcome ref (e.g. "2.1a", "2.2h")
- For custom_mappings, only include entries if custom standards are provided AND there is actual evidence
- If no custom standards provided, return custom_mappings as an empty array []
- Generate unique IDs for each item (e.g. "cqc_1", "cc_1", "custom_1")
- For RISKS: also detect MINIMISING OR DISMISSIVE LANGUAGE — when the supervisee downplays, dismisses, or hedges about a concern, incident, or their own actions. Flag patterns such as: "it was nothing / probably not important / I didn't think it was a big deal / I suppose I should have / I probably should have reported it". This may indicate rationalised inaction, a concern being normalised, or a safeguarding matter not being recognised as significant. Generate a medium severity risk: "Minimising language — further investigation needed", describing what was minimised. Suggested resolutions: follow-up questions, consider whether formal recording or escalation is required.
- For RISKS: also detect SUPERVISEE WELLBEING SIGNALS — expressions from the person being supervised that suggest they may be struggling with their own health, wellbeing, or self-perception. Flag tiredness (especially if repeated), stress, feeling overwhelmed, or inability to cope as medium/high risks. IMPORTANT DISTINCTION: "I felt bad for not doing X" is guilt about an action gap, NOT a wellbeing signal — keep those separate. A wellbeing signal is about the worker's general personal state, not remorse about a specific incident. When multiple genuine wellbeing signals appear across the session, generate a single consolidated risk describing the overall pattern. Suggested resolutions should include pastoral follow-up, EAP signposting, workload review, and a note to monitor."""


async def analyze_doc_for_evidence(
    text: str,
    cqc_standards: list,
    care_cert_standards: list,
    custom_standards: list = None,
    jurisdiction: str = "england",
) -> dict:
    """Map evidence from an uploaded supervision document to standards (jurisdiction-aware)."""
    if jurisdiction == "wales":
        reg_label = "CIW REGULATIONS (Care Inspectorate Wales — RISCA 2016)"
        cert_label = "AWIF / SCW STANDARDS (All Wales Induction Framework & Social Care Wales Code)"
    elif jurisdiction == "scotland":
        reg_label = "CARE INSPECTORATE SCOTLAND QUALITY INDICATORS"
        cert_label = "SSSC CODE OF PRACTICE (Scottish Social Services Council — Worker's Code 2024)"
    elif jurisdiction == "northern_ireland_domiciliary":
        reg_label = "RQIA DOMICILIARY MINIMUM STANDARDS (Northern Ireland — DHSSPS 2021)"
        cert_label = "NISCC CODE OF PRACTICE & INDUCTION PROGRAMME (Northern Ireland Social Care Council)"
    elif jurisdiction == "northern_ireland_residential":
        reg_label = "RQIA RESIDENTIAL CARE HOME REGULATIONS (Northern Ireland — 2005)"
        cert_label = "NISCC CODE OF PRACTICE & INDUCTION PROGRAMME (Northern Ireland Social Care Council)"
    else:
        reg_label = "CQC REGULATIONS"
        cert_label = "CARE CERTIFICATE STANDARDS"

    cqc_context = "\n".join([
        f"- {s['reference']}: {s['name']}" +
        (f" [Key Questions: {', '.join(s.get('key_questions', []))}]" if s.get('key_questions') else "") +
        f" — {s.get('description', '')}"
        for s in cqc_standards[:60]
    ])

    cc_lines = []
    # NI has up to 19 NISCC standards; cap generously at 30 to fit all jurisdictions
    for s in care_cert_standards[:30]:
        line = f"- {s['reference']}: {s['name']}"
        sub_outcomes = s.get("sub_outcomes", [])
        if sub_outcomes:
            so_list = "\n    ".join([f"{so['ref']}: {so['desc']}" for so in sub_outcomes])
            line += f"\n    Sub-outcomes (map to these):\n    {so_list}"
        cc_lines.append(line)
    cc_context = "\n".join(cc_lines)

    custom_context = ""
    if custom_standards:
        custom_lines = []
        for doc in custom_standards:
            doc_id = doc.get("id", "")
            doc_name = doc.get("label") or doc.get("filename", "Unknown Document")
            criteria = doc.get("extracted_criteria", [])
            if criteria:
                custom_lines.append(f"\nDocument: {doc_name} (document_id: {doc_id})")
                for c in criteria:
                    custom_lines.append(f"  - {c['ref']}: {c['name']} — {c.get('description', '')}")
        if custom_lines:
            custom_context = "\n\nCUSTOM / ORGANISATIONAL STANDARDS TO MAP AGAINST:\n" + "\n".join(custom_lines)

    user_prompt = f"""Analyze this supervision document and map evidence to the relevant standards.

DOCUMENT CONTENT:
{text[:12000]}

{reg_label} TO MAP AGAINST:
{cqc_context}

{cert_label} TO MAP AGAINST:
{cc_context}{custom_context}

Provide your analysis as JSON only. Only map regulations/standards where there is actual evidence in the document."""

    full_response = await _openai_chat("o4-mini", DOC_EVIDENCE_SYSTEM_PROMPT, user_prompt, reasoning_effort="high")

    try:
        text_resp = full_response.strip()
        if text_resp.startswith("```"):
            lines = text_resp.split("\n")
            text_resp = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
        result = json.loads(text_resp)
        result.setdefault("cqc_mappings", [])
        result.setdefault("care_cert_mappings", [])
        result.setdefault("custom_mappings", [])
        return result
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse doc evidence response: %s\nResponse: %s", exc, full_response[:500])
        return {"cqc_mappings": [], "care_cert_mappings": [], "custom_mappings": []}


async def analyze_meeting(
    transcript_text: str,
    cqc_standards: list,
    care_cert_standards: list,
    paused_periods: list,
    custom_standards: list = None,
    supervision_template: dict = None,
    custom_prompt: str = None,
    jurisdiction: str = "england",
) -> dict:
    # Build jurisdiction-aware labels for prompts
    if jurisdiction == "wales":
        reg_label = "CIW REGULATIONS (Care Inspectorate Wales — RISCA 2016)"
        cert_label = "AWIF / SCW STANDARDS (All Wales Induction Framework & Social Care Wales Code)"
    elif jurisdiction == "scotland":
        reg_label = "CARE INSPECTORATE SCOTLAND QUALITY INDICATORS"
        cert_label = "SSSC CODE OF PRACTICE (Scottish Social Services Council — Worker's Code 2024)"
    elif jurisdiction == "northern_ireland_domiciliary":
        reg_label = "RQIA DOMICILIARY MINIMUM STANDARDS (Northern Ireland — DHSSPS 2021)"
        cert_label = "NISCC CODE OF PRACTICE & INDUCTION PROGRAMME (Northern Ireland Social Care Council)"
    elif jurisdiction == "northern_ireland_residential":
        reg_label = "RQIA RESIDENTIAL CARE HOME REGULATIONS (Northern Ireland — 2005)"
        cert_label = "NISCC CODE OF PRACTICE & INDUCTION PROGRAMME (Northern Ireland Social Care Council)"
    else:
        reg_label = "CQC REGULATIONS"
        cert_label = "CARE CERTIFICATE STANDARDS"

    # Build standards context — CQC/CIW includes key questions; Care Cert/AWIF includes outcomes
    cqc_context = "\n".join([
        f"- {s['reference']}: {s['name']}" +
        (f" [Key Questions: {', '.join(s.get('key_questions', []))}]" if s.get('key_questions') else "") +
        f" — {s.get('description', '')}"
        for s in cqc_standards[:60]
    ])

    # Care Certificate / NISCC context — includes granular sub-outcomes for precise mapping
    # Cap at 30: England=16, Wales AWIF/SCW=13, Scotland SSSC=6, NI NISCC=19
    cc_lines = []
    for s in care_cert_standards[:30]:
        line = f"- {s['reference']}: {s['name']}"
        sub_outcomes = s.get("sub_outcomes", [])
        outcomes = s.get("outcomes", [])
        if sub_outcomes:
            # Use granular sub-outcomes
            so_list = "\n    ".join([f"{so['ref']}: {so['desc']}" for so in sub_outcomes])
            line += f"\n    Sub-outcomes (map to these specific refs):\n    {so_list}"
        elif outcomes:
            # Fallback to top-level outcomes if no sub-outcomes available
            outcome_list = " | ".join([f"Outcome {o['ref']}: {o['name']}" for o in outcomes])
            line += f"\n    Outcomes: {outcome_list}"
        cc_lines.append(line)
    cc_context = "\n".join(cc_lines)

    # Custom/library document standards
    custom_context = ""
    if custom_standards:
        custom_lines = []
        for doc in custom_standards:
            doc_id = doc.get("id", "")
            doc_name = doc.get("label") or doc.get("filename", "Unknown Document")
            criteria = doc.get("extracted_criteria", [])
            if criteria:
                custom_lines.append(f"\nDocument: {doc_name} (document_id: {doc_id})")
                for c in criteria:
                    custom_lines.append(f"  - {c['ref']}: {c['name']} — {c.get('description', '')}")
        if custom_lines:
            custom_context = "\n\nCUSTOM / ORGANISATIONAL STANDARDS TO MAP AGAINST:\n" + "\n".join(custom_lines)

    # Supervision template context
    template_context = ""
    if supervision_template and supervision_template.get("steps"):
        steps = supervision_template["steps"]
        step_lines = "\n".join([f"  {s.get('order', i+1)}. {s['title']}" + (f" — {s['description']}" if s.get('description') else "") for i, s in enumerate(steps)])
        template_context = f"\n\nORGANISATION SUPERVISION TEMPLATE (topics this session was designed to cover):\n{step_lines}\nUse these headings to contextualise your summary and action items."

    pause_note = ""
    if paused_periods:
        pause_note = f"\n\nNOTE: The recording was paused {len(paused_periods)} time(s) during this meeting. Paused sections are not included in the transcript."

    custom_prompt_note = ""
    if custom_prompt and custom_prompt.strip():
        custom_prompt_note = f"\n\nADDITIONAL FOCUS FROM MANAGER — in addition to your full analysis above, please also specifically look for further evidence relating to: {custom_prompt.strip()}\nIMPORTANT: Do NOT reduce coverage of other standards. This is additive — find everything you can across all standards, then make sure you have given extra attention to the area mentioned here."

    # Jurisdiction-specific domain detection guide — tells the AI what supervision
    # conversation patterns map to each domain/theme, without requiring the speaker
    # to name a standard. Keeps CQC references out of non-CQC prompts.
    if jurisdiction == "england":
        domain_guide = """
EVIDENCE DETECTION GUIDE — read this before mapping any standard:
Your task is not to match phrases — it is to understand what each person is DOING and THINKING, then identify which standard governs that behaviour. Workers rarely use compliance language. Reason from the human behaviour described in the transcript to the standard that captures it.

── SAFE ──────────────────────────────────────────────────────────────────────

QS Safe 1 — Learning from safety events
This standard is about a worker or organisation that notices when something went wrong or nearly went wrong, reflects on it, and uses it to inform what happens next. Map it whenever any event — however minor — is described, reported, reflected on, or used to justify a change in approach. Does not require the word "incident": "there was a situation", "something happened", "I wasn't sure what to do", "we changed how we do it after that" are all evidence of this standard.

QS Safe 2 — Safe systems, pathways and transitions
This standard is about ensuring nothing is lost or missed when care moves between people, shifts, or settings. Map it whenever a worker describes how they ensured continuity — what they recorded, who they handed over to, what they checked before taking someone to an appointment, or how they made sure the next carer knew what was needed. Written notes, verbal handovers, following up on referrals, or checking what a previous carer had done are all evidence.

QS Safe 3 — Safeguarding (also Reg 13)
This standard is about recognising that a person may be at risk and acting on that concern. Map it whenever a worker describes noticing something concerning about a person's welfare, reporting a concern, following safeguarding procedures, or demonstrating awareness of their duty to protect. This includes situations involving potential abuse, neglect, financial exploitation, or self-harm — and also includes a worker simply expressing that they were worried about someone and did something about it.

QS Safe 4 — Involving people in safety decisions
This standard is about working WITH a person to understand and manage risk — not assessing risk and restricting them without their involvement. Map it whenever a worker describes discussing a risk WITH a service user, explaining why something is a concern, or supporting someone to take a risk they have chosen. The key signal: the person's own voice was part of the risk conversation.

QS Safe 5 — Safe environments
This standard is about maintaining a physically safe care environment. Map it whenever a worker mentions checking, repairing, reporting, or questioning the safety of equipment, premises, or the care environment.

QS Safe 6 — Safe and effective staffing (also Reg 18)
This standard is about whether staff are competent, supported and appropriately deployed. The supervision meeting itself is direct evidence — it demonstrates the organisation invests in staff support and oversight. Beyond that, map it whenever training is discussed, workload or capability concerns are raised, support from a manager is described, or the worker talks about whether they feel equipped to do their job. Also map it when the supervisee expresses personal welfare concerns — fatigue, tiredness, stress, feeling overwhelmed, or self-doubt about their own performance — because these signals directly engage the employer's Regulation 18 duty to ensure staff are fit and supported to carry out their role safely.

QS Safe 7 — Infection prevention and control
This standard is about hygiene and preventing the spread of infection. Map it whenever any IPC-related practice is mentioned, however routine — handwashing, wearing gloves or PPE, cleaning procedures, managing an infectious situation, or following isolation protocols.

QS Safe 8 — Medicines optimisation (also Reg 12)
This standard is about safe handling, administration and recording of medications. Map it whenever medication is mentioned in any context — routine administration, a medication error, uncertainty about a dose, checking a MAR chart, administering controlled drugs, or a medication-related concern. Any engagement with medicines in the transcript is evidence of this standard.

── EFFECTIVE ─────────────────────────────────────────────────────────────────

QS Effective 1 — Assessing needs and planning care (also Reg 9)
This standard is about understanding what a person actually needs and ensuring care reflects that. Map it whenever a worker or manager describes reviewing or updating an assessment, noticing that someone's needs have changed, or questioning whether the current care plan still fits. Does not require formal assessment language: "I noticed she was struggling more" or "the plan doesn't really reflect where she is now" are both evidence of this standard.

QS Effective 2 — Best practice and evidence-based care
This standard is about delivering care in line with established knowledge, training, and professional guidance. Map it whenever a worker describes following a care plan, a procedure, or a training-informed approach. Any reference to "the way we're supposed to do it", a technique learned in training, or a protocol being followed is evidence.

QS Effective 3 — Multi-disciplinary and inter-agency working
This standard is about working across professional boundaries to coordinate care. Map it whenever a worker mentions any contact with a professional from another service — GP, district nurse, social worker, hospital team, occupational therapist, or any other agency or service. The contact does not need to be described in detail; mentioning it happened is sufficient evidence.

QS Effective 4 — Supporting independence and health promotion
This standard is about actively enabling a person to do things for themselves rather than just doing everything for them. Map it whenever a worker describes encouraging a person to maintain or develop a capability, supporting healthy choices, or taking a reablement approach. The key signal: the worker is working toward the person being MORE able, not just caring for them.

QS Effective 5 — Monitoring outcomes and improving
This standard is about checking whether care is working and whether the person's situation is changing. Map it whenever a worker describes noticing a change in someone's condition, reporting that something is getting better or worse, or escalating because an approach is not working.

QS Effective 6 — Consent, capacity and best interests (also Reg 11)
This standard is about ensuring people give genuine consent to their care, and managing situations where the ability to consent is uncertain. Map it whenever a worker describes asking permission, explaining what they are about to do, checking someone understood, or navigating a situation where a person's decision-making capacity was a factor. "I always ask first" is consent evidence. "She said yes so I went ahead" is consent evidence. "We had to think about what was best for her" is capacity and best-interests evidence.

── CARING ────────────────────────────────────────────────────────────────────

QS Caring 1 — Kindness, compassion and dignity
This is the most commonly under-evidenced standard because the evidence is not in compliance language — it is in the texture of how a worker talks about their work. This standard is evidenced whenever a worker demonstrates they noticed, cared about, or responded to the emotional state, preferences, or humanity of a person — not just completed a task. A worker who mentions staying a bit longer because someone seemed unsettled, adjusting their pace because someone was having a hard day, taking time to have a proper conversation, or noticing that a person seemed different is demonstrating this standard. Map it whenever the worker shows they were present with the person, not just executing tasks. Do not require the word "caring" or "compassionate".

QS Caring 2 — Treating people as individuals
This standard is about recognising and responding to a person as unique — with their own history, preferences, personality, culture and identity. Map it whenever a worker describes doing something specifically because of who this particular person is. "She likes it done a certain way" is evidence. "He doesn't like being called by his first name" is evidence. "I know she's religious so that matters to how we do things" is evidence.

QS Caring 3 — Independence, choice and control
This standard is about supporting a person to exercise agency over their own life. Map it whenever a worker describes offering a genuine choice, respecting a decision even when they had reservations about it, or actively supporting someone to do something for themselves. "It was her choice" is evidence. "I gave her options" is evidence. "He didn't want to and I respected that" is evidence.

QS Caring 4 — Responding to people's immediate needs
This standard is about being attentive and responsive in the moment — adjusting to what a person needs right now rather than following a fixed task list. Map it whenever a worker describes noticing something in the moment and adapting accordingly: pausing a task because someone was distressed, staying longer because it was needed, or responding to something unexpected that happened during a visit.

QS Caring 5 — Supporting workforce wellbeing and development
This standard is about the organisation and manager actively caring for and investing in the worker. The supervision meeting itself is strong evidence of this standard — the manager is spending dedicated time on the worker's wellbeing and development. Further evidence includes: the manager checking how the worker is doing, discussing workload, following up on a previous commitment, offering support for a difficult situation, or the worker describing feeling valued, heard, or supported. Also map this standard when the supervisee expresses that they are tired, struggling, not coping, or doubting their performance — these are welfare signals that confirm wellbeing is being surfaced in supervision, even if not yet fully resolved.

Reg 10 — Dignity and respect
This regulation is about maintaining every person's dignity and treating them with respect in every interaction — physical dignity during personal care, psychological dignity in how they are spoken about, and social dignity in being treated as a capable adult. Map it whenever a worker describes how they approach personal care, how they speak about service users, or how they handled a sensitive moment. Knocking before entering, explaining what you are doing before you do it, maintaining privacy, not discussing a person in front of others — all are Reg 10 evidence. This is frequently missed because workers describe these behaviours as routine rather than highlighting them as significant.

── RESPONSIVE ────────────────────────────────────────────────────────────────

QS Responsive 1 — Personalised care and support (also Reg 9)
This standard is about care that is shaped around what this individual person wants and needs — co-produced with them and flexible to their changing circumstances. Map it whenever care is described as having been adjusted, updated, or personalised in response to what the person has expressed. "We changed it because she wanted it different" is evidence. "The plan doesn't reflect what he wants now" is evidence.

QS Responsive 2 — Flexible and coordinated care
This standard is about the service adapting to what a person needs across settings and over time. Map it whenever care is described as having been flexed — different timing, different approach, adapted when circumstances changed — or when the worker describes coordination with other services around a single person.

QS Responsive 3 — Information and communication
This standard is about ensuring people receive information in a way they can understand and use. Map it whenever a worker describes explaining something to a service user or family member, checking they understood, adapting how they communicated to suit the person, or ensuring someone was kept informed. "I made sure she knew what was happening" is evidence. "I explained it in plain language" is evidence.

QS Responsive 4 — Feedback, concerns and complaints (also Reg 16)
This standard is about taking feedback and concerns seriously and acting on them. Map it whenever a worker or service user raised a concern, gave feedback, made a complaint, or where the worker describes escalating something on a person's behalf. "She wasn't happy so I passed it on" is evidence. "I raised it because I didn't think it was right" is evidence.

QS Responsive 5 — Equitable access to care and treatment
This standard is about ensuring people can access the care and support they are entitled to. Map it whenever a worker describes helping someone access a service, facilitating a referral, or flagging that someone was not getting what they needed.

QS Responsive 6 — Equality, diversity and protected characteristics
This standard is about recognising that different backgrounds and identities create different needs, and adapting care accordingly. Map it whenever a worker describes adapting their approach because of a person's language, culture, religion, disability, gender, sexuality, or any protected characteristic.

QS Responsive 7 — Advance care planning and end-of-life care
This standard is about planning ahead for future care needs, particularly around a person's wishes for end of life. Map it whenever advance directives, DNACPR, palliative care, end-of-life preferences, or conversations about what a person would want in the future are mentioned.

── WELL-LED ──────────────────────────────────────────────────────────────────

QS Well-led 1 — Shared vision, values and culture
This standard is about the organisation's values being genuinely understood and embedded in how staff work — not just posted on a wall. Map it whenever a worker or manager connects their actions or decisions to what the organisation stands for, references expectations about how things should be done, or describes a cultural norm in how the team operates.

QS Well-led 2 — Inclusive and compassionate leadership
The supervision meeting itself is direct evidence of this standard — a manager engaging in dedicated, attentive one-to-one supervision is inclusive, compassionate leadership in practice. Additionally map it whenever: the manager follows up on previous commitments, the worker describes feeling heard or supported, the manager adapts their approach to the worker's needs, or the quality of the supervisory relationship visible in this transcript demonstrates active investment in the worker.

QS Well-led 3 — Freedom to speak up, psychological safety
This standard is about whether staff feel safe to raise concerns, challenge things they disagree with, or ask questions without fear. Map it whenever a worker describes having raised a concern, feels able to speak honestly, or when the manager actively creates space for challenge or honest feedback in this transcript.

QS Well-led 4 — Workforce equality, diversity and inclusion
This standard is about the organisation ensuring fair treatment and full inclusion for all staff. Map it whenever equality, diversity or inclusion in the workforce is discussed — the worker's own experience of inclusion, training on equality, or the manager discussing equitable treatment of staff.

QS Well-led 5 — Governance, management and accountability (also Reg 17)
This standard is about whether systematic processes are in place to ensure safe, well-managed care. Map it whenever a worker describes following a formal procedure, referencing a policy, participating in an audit, understanding the governance structure, or knowing what the process is when something goes wrong.

QS Well-led 6 — Partnerships and external working
This standard is about the organisation working constructively with external partners — commissioners, local authorities, other services, regulators. Map it when a worker or manager references a formal relationship with an external body or describes work done in partnership at an organisational level (distinct from individual MDT contacts, which map to QS Effective 3).

QS Well-led 7 — Learning, innovation and improvement
This standard is about a culture of continuous improvement — reflecting on practice, learning from experience, and actively seeking to do things better. Map it whenever a worker or manager describes what they learned from an experience, how something changed for the better, or what they want to develop. "I've been thinking about how to do that differently" is evidence. Post-supervision reflection on the quality of the session itself is evidence.

── STANDALONE REGULATIONS ────────────────────────────────────────────────────

Reg 14 — Nutrition and hydration
This regulation is about ensuring people receive adequate food and drink that meets their needs. Map it whenever a worker mentions meals, dietary needs, monitoring food or fluid intake, nutrition concerns, weight changes, or MUST scoring. Any engagement with eating, drinking, or nutrition in the transcript maps here.

Reg 20 — Duty of candour
This regulation is about being open and transparent when things go wrong — informing and apologising to people affected. Map it whenever a worker or manager describes communicating openly about an error or adverse event, apologising to a service user or family, or demonstrating that the organisation expects honesty about mistakes."""

    elif jurisdiction == "wales":
        domain_guide = """
EVIDENCE DETECTION GUIDE — read this before mapping any standard:
Your task is not to match phrases — it is to understand what each person is DOING and THINKING, then identify which Welsh standard governs that behaviour. Workers in Wales rarely name a regulation number. Reason from the described behaviour to the standard that captures its intent.

── QUALITY OF CARE AND SUPPORT ──────────────────────────────────────────────

Reg 15 — Personal plan
This regulation is about whether care is planned around what a specific individual actually needs, co-produced with them, and kept current as circumstances change. Map it whenever a worker describes reviewing, updating, or questioning whether a care plan still fits a person. Does not require formal language: "I checked with her before we changed it", "the plan doesn't really capture what he needs now", "we went through it together and she said she wanted it different" are all Reg 15 evidence. Any moment where documented planning, goal-setting or reviewing personal outcomes is mentioned connects here.

Reg 14 — Suitability
This regulation is about ensuring the service is genuinely able to meet a person's needs before agreeing to provide care. Map it whenever a worker describes an initial assessment, questions whether a new referral is appropriate, or recognises that a person's needs have changed to the point where the current service may no longer be adequate.

Reg 21 — Standards of care and support (overarching)
This is the broadest quality-of-care standard — it governs the general delivery of care in accordance with the personal plan. Map it whenever a worker describes day-to-day care that addresses a person's physical, emotional, cultural or social needs and cannot be mapped more precisely to a specific regulation. Any description of doing the job attentively and in accordance with the agreed plan is Reg 21 evidence.

Reg 22 — Continuity of care
This regulation is about a person receiving consistent, predictable care from familiar people. Map it whenever a worker or manager discusses staffing continuity — whether someone always has the same carer, how changes in staff are handled, what happens when a replacement visits. "She knows me now, so it's easier" is Reg 22 evidence. "They don't always send the same person and she finds it unsettling" is Reg 22 evidence.

Reg 23 / Reg 24 — Information and communication
These regulations are about the person having information they need in a format they can actually use. Reg 23 covers the content — decisions, care choices, what is happening. Reg 24 covers the format — language, Welsh, communication aids. Map Reg 23 whenever a worker describes explaining something to a service user, checking understanding, or ensuring someone was kept informed. Map Reg 24 whenever language or communication method is discussed — adapting vocabulary, using a picture board, offering Welsh, or noting that someone communicates differently. "I always check she's understood before I leave" is Reg 23. "He uses Makaton so I sign when I can" is Reg 24. These are frequently missed because workers describe these behaviours as routine rather than significant.

Reg 25 — Respect and sensitivity
This regulation is about maintaining a person's dignity, privacy and autonomy in every interaction. Map it whenever a worker describes how they approach personal or intimate care, how they knock before entering, how they speak about someone, or how they handle a culturally sensitive situation. "I always explain what I'm doing before I start" is Reg 25. "I make sure the curtains are closed" is Reg 25. This is one of the most commonly under-evidenced regulations because workers describe this behaviour as routine rather than noting it as significant.

── SAFEGUARDING ───────────────────────────────────────────────────────────────

Reg 26 / Reg 27 — Safeguarding
These regulations are about recognising that a person may be at risk and taking action. Map whenever a worker describes noticing something concerning about a person's welfare, raising or reporting a safeguarding concern, following or questioning safeguarding procedures, or demonstrating awareness of categories of harm. Does not require the word "safeguarding": "I was worried about what she told me so I reported it", "something didn't seem right so I raised it", "I wasn't sure so I flagged it" are all safeguarding evidence. Reg 26 is the overarching duty; Reg 27 covers specific policies and procedures for responding to allegations.

Reg 28 — Supporting individuals to manage their money
Map it whenever money is discussed in the context of a service user — handling cash, accompanying someone to a bank, receiving gifts, holding someone's money, or any concern that someone is being financially taken advantage of.

Reg 29 / Reg 31 — Restraint and deprivation of liberty
Map Reg 29 whenever physical control, restraint techniques, or any restrictive intervention is mentioned — even a brief reference. Map Reg 31 whenever mental capacity, Deprivation of Liberty Safeguards (DoLS), best interests decisions, or situations where a person's liberty is restricted for their own safety are discussed.

── STAFFING ───────────────────────────────────────────────────────────────────

Reg 34 — Staffing levels
Map whenever workload, staffing levels, skill mix, or deployment decisions are discussed — the team being short-staffed, matching worker skills to care complexity, or capacity concerns.

Reg 35 — Fitness of staff
Map whenever recruitment processes, DBS checks, Social Care Wales registration, references, or fitness to work are mentioned.

Reg 36 — Supporting and developing staff
The supervision meeting itself is direct evidence of Reg 36 — it requires regular supervision (at least quarterly), annual appraisal, AWIF induction completion, and ongoing training. Map it whenever training is discussed, a training need is identified, AWIF or SCW registration is mentioned, or any form of professional development arises. The manager following up on a previous commitment, asking how the worker is doing, or identifying a learning need is all Reg 36 evidence. This is the most frequently evidenced regulation in supervision.

Reg 38 — Information for staff
Map whenever a worker describes knowing or not knowing the policies and information they need to do their job — references to the code of conduct, lone working arrangements, what to do in an emergency, or how to escalate concerns.

Reg 39 — Disciplinary procedures
Map when any disciplinary matter, misconduct concern, formal process, or safeguarding allegation that might trigger an employment process is discussed.

── LEADERSHIP AND MANAGEMENT ────────────────────────────────────────────────

Reg 80 — Quality of care review
Map whenever a worker or manager references any form of quality audit, monitoring system, six-monthly review, governance report, or organisational quality assurance process. "We had a review of the service last month" is Reg 80 evidence.

Reg 64 — Complaints
Map whenever a complaint, a concern raised by a service user or family, or the handling of feedback is discussed. The worker does not need to use the word "complaint" — "she was unhappy about how it was handled", "I escalated the family's concern to my manager", or "we had a difficult situation with a family member" are all Reg 64 territory.

Reg 65 — Whistleblowing
Map whenever a worker describes raising a concern about the organisation or a colleague — not a safeguarding concern about a service user (that is Reg 26), but a concern about how the service is being run, a colleague's conduct, or a systemic practice that seems wrong.

Reg 59 — Records
Map whenever documentation, record-keeping, completing care notes, accuracy of records, or access to individual records is mentioned in any context.

── AWIF — INDUCTION FRAMEWORK ──────────────────────────────────────────────

AWIF standards map to specific knowledge domains a worker should develop during and after induction. Map them when the content of what the worker knows or is learning fits the workbook's scope.

AWIF 1 / AWIF 2 — Principles and values (adults / children)
Map when a worker discusses the underlying values that shape their approach — person-centred practice, the SSWB Act, equality and diversity, positive risk-taking, professional boundaries, or Welsh language. Reflects the worker's value base rather than a specific task.

AWIF 3 / AWIF 4 — Health and well-being (adults / children)
Map when a worker discusses anything related to a person's physical or mental health care needs — medication, nutrition, personal care, dementia, mental health, palliative care, pressure area care, or falls prevention.

AWIF 5 — Professional practice
Map when a worker reflects on their own professional responsibilities, CPD, teamwork, information handling, GDPR, data protection, or SCW registration. Any discussion of professional development, continuing learning or accountability maps here.

AWIF 6 — Safeguarding
Map when a worker demonstrates personal awareness of safeguarding responsibilities or describes how they responded to a concern. This overlaps with CIW Reg 26/27 — map both when a safeguarding conversation reflects both the regulatory requirement and the worker's own knowledge and skill.

AWIF 7 — Health and safety
Map when health and safety is discussed in any form — risk assessments, manual handling, infection control, PPE, lone working, fire safety, or stress management.

── SCW WORKER'S CODE ─────────────────────────────────────────────────────────

The SCW Code describes the expected conduct and professional values of the worker themselves. Map alongside CIW regulations when the worker reflects on their own behaviour, values or professional identity.

SCW 1 — Rights and interests
Map when a worker describes promoting a service user's rights, supporting their voice and choices, treating someone as an individual, or maintaining dignity and privacy in care.

SCW 2 — Trust and honesty
Map when a worker describes reliability, maintaining confidentiality, professional boundaries, or being honest with a service user or family in a difficult situation.

SCW 3 — Wellbeing and safety
Map when a worker balances a person's right to make their own choices with the responsibility to keep them safe — including escalating safeguarding concerns, following safety procedures, or being open when something went wrong.

SCW 4 — Managing risk
Map when a worker describes actively supporting a person to take an informed risk, co-producing a risk assessment, or navigating a situation where autonomy and safety are in tension.

SCW 5 — Accountability
Map when a worker describes taking responsibility for their own practice, understanding their accountability, raising concerns about poor practice, or upholding professional standards.

SCW 6 — Professional development
Map when a worker describes maintaining or improving their own knowledge and skills, engaging with training, or reflecting on their development needs and what they want to learn."""

    elif jurisdiction == "scotland":
        domain_guide = """
EVIDENCE DETECTION GUIDE — read this before mapping any standard:
Your task is not to match phrases — it is to understand what each person is DOING and THINKING, then identify which Scottish standard governs that behaviour. Workers in Scotland rarely name a quality indicator. Reason from the described behaviour to the standard that captures its intent.

── QUALITY OF EXPERIENCE (CI 1.x) ──────────────────────────────────────────

CI 1.1 — Relationships and interactions
This indicator is about how a worker actually shows up with the people they care for — with warmth, compassion, presence and humanity. Map it whenever a worker describes the texture of their relationship with a service user: noticing how someone was feeling, responding with kindness, adjusting their pace or approach to the person's mood. "She seemed low so I sat with her for a bit" is CI 1.1. "He always likes to have a proper chat before we start" is CI 1.1. "I stayed a bit longer because she was unsettled" is CI 1.1. This is frequently missed because workers describe these moments as informal or unremarkable rather than recognising them as evidence of quality practice.

CI 1.2 — Quality of life and engagement
This indicator is about whether a person is able to engage with life in ways that are meaningful to them — activities, interests, social connection, a sense of purpose. Map it whenever a worker describes supporting someone to do something that matters to them personally, enabling participation in activities, or helping someone stay connected to the things they enjoy. "She loves the garden so I make sure she gets out there" is CI 1.2. "He wanted to try the community café so we planned it together" is CI 1.2.

CI 1.3 — Health and wellbeing
This indicator is about how care actively contributes to a person's physical and mental health. Map it whenever a worker describes monitoring a person's condition, responding to changes in health or behaviour, supporting nutrition, mobility or clinical needs, or noticing that someone's wellbeing has changed in a way that needed attention.

CI 1.4 — A responsive, trusted service
This indicator is about care that responds to what a person actually needs in the moment — attentive, flexible, led by the person. Map it whenever a worker describes pausing or adapting what they were doing because of how the person was feeling, responding to something unexpected that arose during a visit, or demonstrating that the person's immediate state shaped what happened rather than a fixed task list.

CI 1.5 — Infection prevention and control
Map whenever any IPC-related practice is mentioned — handwashing, wearing PPE, cleaning procedures, managing an infectious illness or outbreak, or following isolation protocols. Entirely routine mentions count as evidence of this indicator.

── LEADERSHIP AND MANAGEMENT (CI 2.x) ─────────────────────────────────────

CI 2.1 — Vision, values and culture
This indicator is about whether the organisation's values are genuinely embedded in how staff work — not just written on a wall. Map it whenever a worker or manager connects their actions or decisions to what the organisation stands for, references shared expectations about how things should be done, or describes a cultural norm in how the team operates. "That's just how we do things here" said with pride is CI 2.1 evidence. A manager modelling openness and care in how they conduct this supervision session is CI 2.1 evidence.

CI 2.2 — Quality assurance and improvement
Map whenever a worker or manager describes any formal quality process — audits, monitoring systems, self-evaluation, governance reviews, significant incident reviews, or systematically identifying areas for improvement.

CI 2.3 — Partnership working
Map whenever a worker mentions contact or collaboration with any professional from another service — community nurse, GP, social worker, occupational therapist, housing support, or any other external agency or body. The contact does not need to be described in detail; mentioning it happened is sufficient evidence.

CI 2.4 — Staff are led well
The supervision meeting itself is direct evidence of this indicator — a manager investing in structured, supportive one-to-one time with a worker is CI 2.4 in action. Additionally map it whenever: the worker describes feeling valued or supported, the manager follows up on a commitment from a previous session, the manager adapts to the worker's needs in this conversation, or the quality of the supervisory relationship visible in this transcript demonstrates active investment in the worker. Also map it when a worker expresses welfare concerns — fatigue, stress, feeling overwhelmed, or doubting their performance — because these signals confirm supervision is fulfilling its CI 2.4 function of surfacing and addressing staff wellbeing.

── STAFF TEAM (CI 3.x) ─────────────────────────────────────────────────────

CI 3.1 — Staff recruited well
Map whenever recruitment processes, PVG (Protection of Vulnerable Groups) Scheme checks, Disclosure Scotland, SSSC registration at the point of hiring, references, or pre-employment vetting are discussed.

CI 3.2 — Knowledge, competence and development
This is the most evidence-rich staffing indicator for a supervision session. Map it whenever training is discussed, a development need is identified, qualifications or CPD are mentioned, the National Induction Framework (NIF) is referenced, SSSC registration requirements are discussed, or a worker reflects on what they have learned or what they want to learn. "I wasn't sure how to handle that so I asked my manager" is CI 3.2 evidence — it demonstrates reflective practice and seeking support. "I've been doing much better with that since the training" is CI 3.2 evidence. Any SVQ or mandatory training discussion maps here.

CI 3.3 — Staffing arrangements
Map whenever staffing levels, shift patterns, team composition, handovers, continuity of care, or deployment decisions are discussed — including concerns about the team being short-staffed, or questions about skill mix.

── SETTING (CI 4.x) ────────────────────────────────────────────────────────

CI 4.1 — Quality facilities and environment
Map whenever the physical care environment is discussed — maintenance, safety checks, equipment condition, cleanliness, health and safety risks, fire safety, or the accessibility of the building or space.

CI 4.2 — Independence-promoting environment
Map when a worker describes how the physical space, layout, or assistive technology enables someone to do things for themselves — adapting the environment to promote mobility, independence, or autonomy.

CI 4.3 — Connected to community
Map when a worker describes supporting a person to maintain community connections, access local amenities, take part in activities outside the service, or sustain relationships beyond the care setting.

── PERSONAL PLANNING (CI 5.x) ──────────────────────────────────────────────

CI 5.1 — Assessment and personal planning
This indicator is about whether care planning is genuinely person-centred and co-produced with the individual. Map it whenever a worker describes reviewing or updating a personal plan, noticing that someone's needs or wishes have changed, co-producing a plan with a person, or questioning whether the current approach is working for this person. "I noticed she'd changed her mind about that so we updated it" is CI 5.1. "The plan doesn't really reflect where he is now" is CI 5.1. Any reference to plans being reviewed or revised is evidence here.

CI 5.2 — Involving carers and family
Map when family members, carers, or people important to the service user are mentioned in relation to care planning or reviews — including when a worker describes including a carer's expertise or a family member's knowledge of the person.

── SSSC CODE OF PRACTICE ────────────────────────────────────────────────────

The SSSC Code describes the expected conduct and professional values of the worker themselves. Map alongside CI quality indicators when the worker reflects on their own values, professional behaviour, honesty, risk approach, accountability or development.

SSSC 1 — Rights and interests
Map when a worker describes treating a person with kindness, compassion and respect, supporting their right to make their own decisions, maintaining dignity and privacy, or adapting to their individual preferences and identity. Does not require the word "rights" — "I always make sure she knows she's got a choice" is SSSC 1 evidence. "He has his own way of wanting things done and I follow his lead" is SSSC 1 evidence.

SSSC 2 — Trust and confidence
Map when a worker describes honesty with a service user or family member, reliability, respecting confidentiality, maintaining professional boundaries, or handling a situation where trust was at stake. "I told her the truth even though it was hard to say" is SSSC 2 evidence.

SSSC 3 — Wellbeing and protection
Map when a worker describes raising a concern about a colleague or a systemic practice, following safety procedures, or taking action to prevent harm. Also map when a worker describes being open about something that went wrong — the duty of candour dimension of SSSC 3.

SSSC 4 — Right to take risks
Map when a worker describes supporting a person to take an informed risk they have chosen, working with someone to understand and manage a risk, co-producing a risk assessment, or navigating a situation where autonomy and safety are in tension.

SSSC 5 — Accountability for quality
Map when a worker describes taking responsibility for the quality of their own work, maintaining records, seeking support when uncertain, preparing for and engaging in supervision, or committing to their own continuous professional learning (CPL). The act of engaging meaningfully in this supervision session is itself SSSC 5 evidence.

SSSC 6 — Uphold public trust
Map when professional conduct — inside or outside work — is discussed, including anything that could affect SSSC registration, social media behaviour, relationship boundaries with service users, or anything that affects the public's trust in social care."""

    else:  # northern_ireland (dom or res)
        domain_guide = """
EVIDENCE DETECTION GUIDE — read this before mapping any standard:
Your task is not to match phrases — it is to understand what each person is DOING and THINKING, then identify which Northern Ireland standard governs that behaviour. Workers rarely use standard numbers or formal language. Reason from the described behaviour to the standard that captures its intent.

Note on service type: Dom Std numbers apply to domiciliary services; Reg numbers used alone refer to RQIA Residential Care Home Regulations 2005. NISCC standards apply to workers in both service types.

── PERSON-CENTRED CARE ─────────────────────────────────────────────────────

Dom Std 1 / Reg 13 — Involvement and person-centred care
This standard is about whether the service user actively shapes their own care. Map it whenever a worker describes checking with a person before doing something, involving them in deciding how care is delivered, or respecting their preference for how things are done. "I always ask her how she wants it done" is Dom Std 1. "He has his own way of doing things and I follow his lead" is Dom Std 1. The supervision session itself — if the worker is being asked for their view and involved in decisions — is also a model of this standard in the staffing relationship. This is frequently missed because workers describe involving people as just part of doing the job.

Dom Std 2 / Reg 5 — Information
Map whenever a worker describes giving a service user or their family information about their care, explaining something in a way they can understand, ensuring someone knows their rights, or giving them information about the complaints procedure or how to access RQIA. The format of information matters too — offering it in the person's language or in an accessible format maps here.

Dom Std 4 / Reg 16 — Care plans and personal outcomes
This standard is about whether care is planned to achieve outcomes that are meaningful to this individual — and whether those plans are kept current. Map it whenever a worker describes reviewing a care plan, updating it when needs change, working toward a specific personal goal, or contributing to a planning review. "We reviewed it together last week and adjusted it" is Dom Std 4. "His goals have changed so we need to update the plan" is Dom Std 4. Any engagement with planning, reviewing, or assessing needs is evidence here.

Dom Std 6 — Contributing to service user reviews
Map when a worker describes participating in a review meeting, communicating with other professionals or the placing authority, or contributing their observations about a person's changing needs to a formal review process.

Dom Std 7 / Reg 14 — Medicines management
Map whenever medication is mentioned in any context — routine administration, a medication error or near-miss, checking a MAR chart, uncertainty about a dose, controlled drugs, self-administration, medication disposal, or a medication-related concern. Any engagement with medicines in the transcript maps here.

Dom Std 5 / Dom Std 10 / Reg 20 — Recording and documentation
Map whenever a worker describes completing care records, documenting what they did during a visit, reporting an incident, or maintaining accurate documentation about a service user. "I always write it up before I leave" is evidence. Any concern about inaccurate records maps here too.

Dom Std 9 / Reg 12 — Health, safety and risk
Map when health and safety is discussed — risk assessments in the care environment, lone working, manual handling, infection control, PPE provision, home environment hazards, or anything about keeping workers and service users safe in domiciliary settings. Reg 12 applies to the residential context.

── SAFEGUARDING ────────────────────────────────────────────────────────────

Dom Std 14 / Reg 17 — Safeguarding
This standard is about recognising when a person may be at risk of harm and acting on that concern. Map it whenever a worker describes noticing something concerning about a person's welfare, raising or reporting a safeguarding concern, following or questioning safeguarding procedures, or demonstrating awareness of categories of harm. Does not require the word "safeguarding": "I was worried about what she told me and I raised it", "something didn't seem right so I flagged it to my manager", or "I reported it to the designated person" are all evidence. Dom Std 14 applies in domiciliary services; Reg 17 in residential care.

NISCC Conduct 3 / NISCC Conduct 4 — Autonomy and risk
Map NISCC Conduct 3 when a worker promotes independence, challenges an unnecessary restriction on a person's choices, reports a concern about how the service is operating, or describes the duty to keep people safe. Map NISCC Conduct 4 when a worker describes supporting a person to take a risk they have chosen, co-producing a risk assessment, or navigating a situation where autonomy and safety are in tension.

── STAFFING AND DEVELOPMENT ─────────────────────────────────────────────────

Dom Std 13 / Reg 19 — Staff supervision and appraisal
The supervision meeting itself is direct evidence of Dom Std 13 — demonstrating that the organisation provides regular, documented supervision to support staff development. Map it whenever the purpose of supervision is discussed, previous supervision commitments are followed up, the worker's development needs are identified, or the manager demonstrates active investment in the worker's growth. The manager checking on the worker's wellbeing — asking how they are, noticing if they seem stressed — is Dom Std 13 evidence. A worker expressing tiredness, feeling overwhelmed, or doubting their ability maps here because it confirms the supervision is fulfilling its function.

Dom Std 12 / Reg 19 — Training and development
Map whenever training is discussed, a training need is identified, NISCC induction completion is mentioned, mandatory training is referenced (safeguarding, manual handling, medicines, infection control), or a worker describes any form of professional development or skills development. "I need more training on that" is evidence. "I completed my induction modules" is evidence. Any CPD discussion maps here.

Dom Std 11 / Reg 24 — Recruitment
Map when recruitment processes, AccessNI checks, NISCC registration, pre-employment vetting, references, or the fitness of a colleague to work with service users is mentioned.

Dom Std 16 / Reg 29 — Safe working practices
Map when health and safety is discussed from the worker's perspective — risk assessments, lone working arrangements, PPE, manual handling, infection control, staff wellbeing, COSHH, or anything about the safety of the worker in carrying out their role.

── MANAGEMENT AND GOVERNANCE ───────────────────────────────────────────────

Dom Std 8 / Reg 26 — Quality assurance and governance
Map whenever any reference is made to organisational monitoring, quality reviews, governance arrangements, service audits, or the overall management of care quality — including when a manager describes oversight processes or systems for checking that care is being delivered well.

Dom Std 15 / Reg 22 — Complaints and concerns
Map whenever a complaint, a concern raised by a service user or their family, or any formal feedback process is discussed. The worker does not need to use the word "complaint" — "she was unhappy and I escalated it", "I passed it to my manager because I thought it needed to go further", or "the family raised a concern" are all evidence.

── NISCC CODE OF PRACTICE ──────────────────────────────────────────────────

The NISCC Code describes the expected conduct and professional values of the worker themselves. Map alongside RQIA standards when the worker reflects on their own approach, behaviour, honesty, accountability or development.

NISCC Conduct 1 — Rights and interests
Map when a worker describes treating a service user with respect and compassion, supporting their right to make informed choices, maintaining dignity and privacy, or adapting to their individual needs and identity. This is frequently missed because workers describe these behaviours as just doing their job rather than recognising their professional significance. "I always ask her first" is NISCC Conduct 1. "I make sure I knock and wait" is NISCC Conduct 1.

NISCC Conduct 2 — Trust and honesty
Map when a worker describes maintaining confidentiality, being honest about something that happened, keeping professional boundaries, or demonstrating reliability with a service user or their family.

NISCC Conduct 5 — Professional conduct and public trust
Map when professional behaviour, conduct standards, NISCC registration, social media use, or suitability to work in social care is discussed — particularly anything that could affect how the public trusts the profession.

NISCC Conduct 6 — Accountability and development
Map when a worker describes taking responsibility for the quality of their own work, maintaining records, being open about mistakes, seeking help when uncertain, co-operating with investigations, or committing to ongoing training and professional learning. The act of engaging seriously in this supervision session is itself NISCC Conduct 6 evidence.

── NISCC PRACTICE STANDARDS ────────────────────────────────────────────────

These standards describe the foundational practice competencies expected of workers in Northern Ireland. Map them when a worker demonstrates specific knowledge or skill areas in their account of their practice.

NISCC Practice 1 — Role and responsibilities
Map when a worker demonstrates understanding of their role, duties, policies and procedures, or duty of care — including how they manage competing priorities, use agreed ways of working, or escalate concerns through the right channels.

NISCC Practice 2 — Communication
Map when a worker describes adapting how they communicate with a service user or family member, overcoming a communication barrier, or sharing relevant information with colleagues in a timely and appropriate way.

NISCC Practice 3 — Person-centred and safe care
Map when a worker describes delivering care that is specifically tailored to this individual person's needs and preferences — involving them in decisions, supporting their independence, or reflecting their stated wishes in how care is provided.

NISCC Practice 4 — Safeguarding
Map when a worker demonstrates their personal safeguarding awareness and applied knowledge — describing what they did when they had a concern, how they recognised a risk, or how they followed safeguarding procedures in practice.

NISCC Practice 5 / NISCC Practice 6 — Professional growth
Map when a worker reflects on their own learning, describes seeking to improve their skills, engages with supervision as a development tool, or demonstrates awareness of their own competence and development needs."""

    user_prompt = f"""Analyze this meeting transcript and map evidence to the relevant standards.

TRANSCRIPT:{pause_note}
{transcript_text[:80000]}{"[TRANSCRIPT TRUNCATED — analyse the above portion only]" if len(transcript_text) > 80000 else ""}

{reg_label} TO MAP AGAINST:
{cqc_context}

{cert_label} TO MAP AGAINST:
{cc_context}{custom_context}{template_context}
{domain_guide}{custom_prompt_note}

Provide your analysis as JSON. Only map regulations/standards where there is actual evidence in the transcript."""

    full_response = await _openai_chat("o4-mini", ANALYSIS_SYSTEM_PROMPT, user_prompt, reasoning_effort="high")

    # Parse JSON from response
    try:
        text = full_response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
        result = json.loads(text)
        if "custom_mappings" not in result:
            result["custom_mappings"] = []
        return result
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI response: {e}\nResponse: {full_response[:500]}")
        return {
            "summary": "Analysis could not be parsed. Please review the transcript manually.",
            "actions": [],
            "learning_needs": [],
            "risks": [],
            "cqc_mappings": [],
            "care_cert_mappings": [],
            "custom_mappings": [],
        }



PREP_SECTIONS = [
    {"id": "wellbeing",            "label": "Wellbeing"},
    {"id": "working_well",         "label": "What's Working Well"},
    {"id": "needs_attention",      "label": "What Needs Attention"},
    {"id": "learning_development", "label": "Learning & Development"},
    {"id": "achievements",         "label": "Achievements"},
    {"id": "aob",                  "label": "Any Other Business"},
]


async def generate_prep_questions(
    supervisee_name: str,
    focus_topic: str,
    previous_meeting_summaries: list,      # list of {"title", "date", "summary", "actions"}
    uploaded_docs: list,                    # list of {"label", "doc_type", "content_snippet"}
    org_values_snippets: list,              # list of {"name", "snippet"}
) -> dict:
    """Generate open-ended, behavioural supervision prep questions for each section.

    Questions must be:
    - Open-ended (never yes/no)
    - Behavioural: phrased as 'Walk me through...', 'Give me an example of...', 'Tell me about a time when...'
    - Grounded in the provided context (previous meetings, JD, values, focus topic)
    Returns: {"sections": [...], "gen_status": "done"}
    """
    # Build context blocks
    prev_context = ""
    if previous_meeting_summaries:
        parts = []
        for m in previous_meeting_summaries[:3]:
            part = f"Meeting '{m.get('title', '?')}' ({m.get('date', '?')}):\n  Summary: {m.get('summary', '')[:600]}"
            actions = m.get("actions", [])
            if actions:
                incomplete = [a.get("text", a.get("action", "")) for a in actions if not a.get("completed")]
                if incomplete:
                    part += f"\n  Outstanding actions: {'; '.join(incomplete[:5])}"
            parts.append(part)
        prev_context = "PREVIOUS SUPERVISION MEETINGS:\n" + "\n\n".join(parts)

    docs_context = ""
    if uploaded_docs:
        parts = []
        for d in uploaded_docs[:6]:
            content = d.get('content_snippet', '').strip()
            if content:
                parts.append(
                    f"[{d.get('doc_type','Document').replace('_',' ').title()}] \"{d.get('label','')}\"\n{content[:2500]}"
                )
        if parts:
            docs_context = "UPLOADED DOCUMENTS (read carefully — questions MUST reference specific content from these):\n\n" + "\n\n---\n\n".join(parts)

    values_context = ""
    if org_values_snippets:
        parts = [f"- {v.get('name','')}: {v.get('snippet','')[:400]}" for v in org_values_snippets[:4]]
        values_context = "ORGANISATIONAL VALUES / STANDARDS:\n" + "\n".join(parts)

    focus_line = f"THIS SESSION'S FOCUS TOPIC: {focus_topic}" if focus_topic else ""

    has_docs = bool(uploaded_docs and any(d.get("content_snippet", "").strip() for d in uploaded_docs))
    has_prev = bool(previous_meeting_summaries)

    sections_spec = "\n".join([f'  "{s["id"]}": "{s["label"]}"' for s in PREP_SECTIONS])

    system_prompt = f"""You are an expert UK adult social care supervision facilitator.
Your task is to generate HIGHLY PERSONALISED, open-ended supervision preparation questions for a manager 
to use in a one-to-one supervision session with {supervisee_name}.

MANDATORY RULES — VIOLATION OF ANY RULE MAKES THE OUTPUT USELESS:

1. NEVER write a question that can be answered with yes or no.

2. USE BEHAVIOURAL/REFLECTIVE PHRASING ONLY:
   - "Walk me through a time when..."
   - "Give me a specific example of how you..."
   - "Tell me about a situation where..."
   - "Describe how you approached..."
   - "What did you do when..."

3. CONCISENESS — every question must be under 25 words. Cut all filler phrases like "I'd like to understand...", "Could you help me explore...", "In the context of your role...". Start directly with the behavioural prompt. One sentence only.

3. {"EVERY question MUST reference specific content from the uploaded documents. Follow these rules by document type:" if has_docs else "Use the focus topic and context to make questions as specific as possible."}
{"   - JOB DESCRIPTION: Read every listed responsibility, competency and required skill. Write questions that probe whether the supervisee is actively fulfilling each one. Name the specific responsibility in the question. Example: if the JD says 'ensure accurate medication records', ask 'Walk me through how you ensure medication records are completed accurately after each administration.' Do not write generic competency questions." if has_docs else ""}
{"   - SUPERVISION RECORD / PREVIOUS MEETING: Follow up directly on named incidents, actions, concerns or themes. Reference them explicitly. Example: 'Last time we discussed the staffing shortage on night shifts — describe how you have managed that since then.'" if has_docs else ""}
{"   - OTHER DOCUMENTS: Extract key themes, requirements and named processes. Ask questions only answerable by someone familiar with that specific content." if has_docs else ""}
{"   Any question that could apply to ANY care worker without reading the documents is REJECTED." if has_docs else ""}

4. {"Follow up on every outstanding action from previous supervision notes." if has_prev else "Use the focus topic to frame questions."}

5. AOB SECTION — THIS IS NOT A FILLER. Rules:
   - Do NOT write "Is there anything else you'd like to discuss?" or any variation of it.
   - Look at the context and identify: an unresolved concern, an upcoming challenge, a recurring theme, or something the supervisee has been working toward.
   - Write one closing question that directly names that thing and invites reflection or forward planning.
   - Good example: "Given the handover issues raised last session, describe what you are planning to put in place before the next shift changeover."
   - If no specific context: ask about a goal they want to set or something they want to develop in the next period.

6. Make questions feel like a natural, caring conversation — not a performance review interrogation.

7. Generate exactly 2 questions per section, except AOB (exactly 1 question).

8. BONUS INSIGHT — After all standard sections, add one extra section with section_id "bonus":
   - Reason deeply through ALL context: documents, previous meetings, outstanding actions, focus topic.
   - Find ONE question that does NOT fit neatly into any standard section but is genuinely valuable — something a less attentive manager would miss entirely.
   - This could be: a pattern across multiple documents, a risk hiding in plain sight, a development opportunity the supervisee hasn't named, a pastoral concern suggested by the tone of previous notes, or an unexpected connection between pieces of context.
   - Label this section exactly: "We thought you might also want to ask this"
   - Generate exactly 1 question. It should be the most insightful, surprising, or revealing question on the page.
   - If you genuinely find nothing from context, still include the section with a thoughtful forward-looking question.

SECTIONS TO POPULATE (standard sections only — bonus is always appended separately):
{sections_spec}

Return ONLY valid JSON — no commentary, no markdown fences:
{{
  "sections": [
    {{
      "section_id": "<section_id>",
      "label": "<section label>",
      "questions": [
        {{"id": "q1", "text": "<question text>", "generated": true}}
      ]
    }},
    {{
      "section_id": "bonus",
      "label": "We thought you might also want to ask this",
      "questions": [
        {{"id": "bonus_q1", "text": "<the insightful discovery question>", "generated": true}}
      ]
    }}
  ]
}}"""

    user_prompt = f"""Generate supervision preparation questions for: {supervisee_name}

{focus_line}

{prev_context}

{docs_context}

{values_context}

FINAL CHECKS BEFORE GENERATING:
{"- Re-read every document above. Name specific responsibilities, incidents and skills from them in your questions." if has_docs else "- Make questions specific to the focus topic and any context provided."}
- The AOB question MUST be grounded in a real theme or concern from the context — identify it now before writing.
- All questions must be open-ended and behavioural. Generate them now."""

    full_response = await _openai_chat("o4-mini", system_prompt, user_prompt, reasoning_effort="high")

    # Strip markdown fences
    if "```" in full_response:
        import re as _re
        m = _re.search(r"```(?:json)?\s*([\s\S]*?)```", full_response)
        if m:
            full_response = m.group(1).strip()

    try:
        data = json.loads(full_response)
        # Validate / fill IDs
        seen_ids: set = set()
        for section in data.get("sections", []):
            for q in section.get("questions", []):
                if not q.get("id") or q["id"] in seen_ids:
                    q["id"] = uuid.uuid4().hex[:8]
                q.setdefault("generated", True)
                q.setdefault("included", True)
                seen_ids.add(q["id"])
        return {"sections": data.get("sections", []), "gen_status": "done"}
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error(f"Failed to parse prep questions response: {exc}\nResponse: {full_response[:500]}")
        # Return empty sections so the UI can still add manual questions
        return {
            "sections": [{"section_id": s["id"], "label": s["label"], "questions": []} for s in PREP_SECTIONS],
            "gen_status": "failed",
        }


async def check_prep_coverage(transcript_text: str, questions: list) -> dict:
    """After transcription, classify each prep question as covered / partial / missed.

    questions: list of {"id": str, "text": str}
    Returns: {"results": {question_id: {"status": "covered"|"partial"|"missed", "evidence": str}}, "checked_at": str}
    """
    if not questions or not transcript_text:
        return {"results": {}, "checked_at": None}

    questions_list = "\n".join([f'  Q{i+1} (id={q["id"]}): {q["text"]}' for i, q in enumerate(questions[:20])])

    system_prompt = """You are an expert supervision quality assessor. 
You will be given a supervision meeting transcript and a list of preparation questions.
For each question, assess how thoroughly it was discussed:
- "covered": clearly and substantively discussed
- "partial": mentioned but not fully explored
- "missed": not discussed at all

Return ONLY valid JSON in this format:
{
  "results": {
    "<question_id>": {"status": "covered"|"partial"|"missed", "evidence": "<short quote or phrase from transcript, or empty string if missed>"}
  }
}"""

    user_prompt = f"""PREP QUESTIONS:
{questions_list}

TRANSCRIPT (first 6000 chars):
{transcript_text[:6000]}

Assess each question's coverage in the transcript. Return JSON only."""

    try:
        full_response = await _openai_chat("gpt-4o", system_prompt, user_prompt)

        if "```" in full_response:
            import re as _re
            m = _re.search(r"```(?:json)?\s*([\s\S]*?)```", full_response)
            if m:
                full_response = m.group(1).strip()

        data = json.loads(full_response)
        return {
            "results": data.get("results", {}),
            "checked_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error(f"Coverage check failed: {exc}")
        return {"results": {}, "checked_at": None}


async def generate_risk_suggestions(risk_text: str, severity: str, transcript_text: str) -> dict:
    """Generate a transcript excerpt and resolution suggestions for an existing risk."""
    system_prompt = """You are an expert UK adult social care safeguarding and risk management advisor.
Given a risk or concern identified in a supervision meeting, your job is to:
1. Find the most relevant short excerpt from the transcript that evidences this risk (max 60 words, exact quote)
2. Provide 2-3 specific, actionable resolution suggestions tailored to adult social care

Return ONLY valid JSON:
{
  "transcript_excerpt": "exact quote from transcript (or empty string if not locatable)",
  "suggested_resolutions": [
    "specific actionable suggestion one",
    "specific actionable suggestion two"
  ]
}"""

    user_prompt = f"""Risk/Concern ({severity.upper()} severity): {risk_text}

Transcript:
{transcript_text}

Find the transcript excerpt evidencing this risk and provide resolution suggestions."""

    try:
        full_response = await _openai_chat("gpt-4o", system_prompt, user_prompt)
        if "```" in full_response:
            import re as _re
            m = _re.search(r"```(?:json)?\s*([\s\S]*?)```", full_response)
            if m:
                full_response = m.group(1).strip()
        data = json.loads(full_response)
        return {
            "transcript_excerpt": data.get("transcript_excerpt", ""),
            "suggested_resolutions": data.get("suggested_resolutions", []),
        }
    except Exception as exc:
        logger.error(f"Risk suggestions failed: {exc}")
        return {"transcript_excerpt": "", "suggested_resolutions": []}
