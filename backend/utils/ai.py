import os
import json
import logging
import uuid
import asyncio
import subprocess
import tempfile
from emergentintegrations.llm.chat import LlmChat, UserMessage
from emergentintegrations.llm.openai import OpenAISpeechToText
from deepgram import DeepgramClient

logger = logging.getLogger(__name__)

WHISPER_MAX_BYTES = 24 * 1024 * 1024  # 24 MB — 1 MB buffer below Whisper's 25 MB hard limit

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


def _compress_to_mp3(audio_data: bytes, input_suffix: str) -> bytes:
    """Compress audio to 16 kHz mono 32 kbps MP3 — optimal for voice/Whisper, ~7 MB per 30 min."""
    import imageio_ffmpeg
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.NamedTemporaryFile(suffix=input_suffix, delete=False) as f:
        f.write(audio_data)
        inp = f.name
    out = inp + ".mp3"
    try:
        result = subprocess.run(
            [
                ffmpeg_exe, "-i", inp,
                "-vn",                 # drop any video stream
                "-ar", "16000",        # 16 kHz — Whisper's native sample rate
                "-ac", "1",            # mono
                "-b:a", "32k",         # 32 kbps bitrate
                out, "-y", "-loglevel", "error",
            ],
            capture_output=True,
            timeout=180,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg compression failed: {result.stderr.decode()}")
        with open(out, "rb") as f:
            return f.read()
    finally:
        os.unlink(inp)
        if os.path.exists(out):
            os.unlink(out)

ANALYSIS_SYSTEM_PROMPT = """You are a compliance analysis specialist for UK adult social care providers.
Analyze meeting transcripts to identify evidence of compliance with CQC regulations, Care Certificate standards, and any additional custom standards provided.

Your output must be valid JSON only (no markdown, no extra text) in this exact structure:
{
  "summary": "Two opening sentences that set context and introduce the session (who, when, what type of meeting).\\n\\n- Key topic or discussion point one\\n- Key topic or discussion point two\\n- Key topic or discussion point three\\n- Key topic or discussion point four\\n- Key topic or discussion point five\\n\\nTwo closing sentences that frame the essential outcomes, any overall themes or next steps from the session.",
  "actions": [
    {"id": "unique_id", "text": "action description", "assigned_to": "person name or null", "due_date": "date mentioned or null"}
  ],
  "risks": [
    {"id": "unique_id", "text": "risk or concern description", "severity": "high|medium|low"}
  ],
  "cqc_mappings": [
    {
      "id": "unique_id",
      "regulation_ref": "Regulation 18",
      "regulation_name": "Staffing",
      "evidence_summary": "Brief description of evidence",
      "transcript_excerpt": "Exact quote from transcript",
      "confidence": "likely_evidence|needs_review|not_enough_evidence"
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
      "confidence": "likely_evidence|needs_review|not_enough_evidence"
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
      "confidence": "likely_evidence|needs_review|not_enough_evidence"
    }
  ]
}

Rules:
- Only map evidence EXPLICITLY mentioned in the transcript
- Do not infer or assume - map only what is directly discussed
- Use "likely_evidence" only when clearly demonstrated
- Use "needs_review" when partially demonstrated or unclear
- Use "not_enough_evidence" when barely touched on
- For Care Certificate mappings, ALWAYS map to the most specific sub-outcome ref (e.g. "2.1a", "2.2h", "13.9c"). Use the exact sub-outcome ref and its description as provided in the standards context below. One evidence item = one sub-outcome ref. Create separate mapping entries if evidence covers multiple sub-outcomes.
- For custom_mappings, only include entries if there are custom standards provided AND there is actual evidence. Use the document_id exactly as provided.
- If no custom standards are provided, return custom_mappings as an empty array []
- If the meeting had paused sections, note this in the summary
- Include transcript excerpts as exact quotes from the provided text
- Generate unique IDs for each item (e.g. "action_1", "risk_1", "cqc_1", "cc_1", "custom_1")
- Summary format MUST follow exactly: two intro sentences, then a blank line, then 4-6 bullet points each starting with "- ", then a blank line, then two closing sentences. Use \\n\\n to separate sections."""


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
- When there are 3 or more participants, give each person their own label — do NOT merge a third person into one of the other two
- Start each new speaker turn on a fresh line
- Preserve ALL original words exactly as transcribed — do not paraphrase, correct, or add any words
- If a turn cannot be confidently attributed to any named participant, use "Speaker:" as a fallback
- Output ONLY the formatted transcript — no preamble, explanation, commentary or markdown"""


# ── Deepgram speaker-number → real name mapping prompt ────────────────────
SPEAKER_MAPPING_SYSTEM_PROMPT = """You are a transcript editor for supervision meetings in UK adult social care.
The audio has already been diarized — speakers are labelled generically (e.g. Speaker A, Speaker B, Speaker 0, Speaker 1).
Your task is to replace those generic labels with the real participant names provided.

Rules:
- Identify which labelled speaker corresponds to which named participant by reading the conversation
- The manager/supervisor steers the agenda, asks questions about the worker's practice, and conducts the meeting
- The worker/supervisee reports on their own work and development
- Do NOT change any spoken words — only replace the speaker label at the start of each line
- If there are more labelled speakers than named participants (e.g. crosstalk artefacts), assign them to the closest matching participant
- Output ONLY the reformatted transcript — no preamble, explanation, or markdown"""


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
    config = aai.TranscriptionConfig(
        speaker_labels=True,
        speakers_expected=speakers_expected if speakers_expected and speakers_expected >= 2 else None,
        speech_models=["universal-3-pro"],  # AssemblyAI medical-capable model
        domain="medical-v1",               # Activates medical mode (care/clinical vocab)
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

    if transcript.utterances:
        unique_speakers = {u.speaker for u in transcript.utterances}
        logger.info(f"AssemblyAI found {len(unique_speakers)} speaker(s): {sorted(unique_speakers)}")

        if len(unique_speakers) > 1:
            lines = [f"Speaker {u.speaker}: {u.text}" for u in transcript.utterances]
            speaker_text = "\n".join(lines)
            logger.info("AssemblyAI diarization usable — GPT-4o will map names only")
            return plain_text, speaker_text

    logger.info("AssemblyAI found only 1 speaker — GPT-4o will diarise from text")
    return plain_text, None


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
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key or not numbered_speaker_text.strip():
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
        chat = LlmChat(
            api_key=api_key,
            session_id=f"mapspk_{uuid.uuid4()}",
            system_message=SPEAKER_MAPPING_SYSTEM_PROMPT,
        ).with_model("openai", "gpt-4o")

        full_response = ""
        async for event in chat.stream_message(UserMessage(text=user_prompt)):
            from emergentintegrations.llm.chat import TextDelta, StreamDone
            if isinstance(event, TextDelta):
                full_response += event.content
            elif isinstance(event, StreamDone):
                break

        result = full_response.strip()
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
    """Use GPT-4o to add speaker labels to a Whisper transcript. Returns None on failure."""
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key or not transcript_text.strip():
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
        chat = LlmChat(
            api_key=api_key,
            session_id=f"diarize_{uuid.uuid4()}",
            system_message=DIARIZATION_SYSTEM_PROMPT,
        ).with_model("openai", "gpt-4o")

        full_response = ""
        async for event in chat.stream_message(UserMessage(text=user_prompt)):
            from emergentintegrations.llm.chat import TextDelta, StreamDone
            if isinstance(event, TextDelta):
                full_response += event.content
            elif isinstance(event, StreamDone):
                break

        result = full_response.strip()
        return result if result else None
    except Exception as e:
        logger.error(f"Speaker diarization failed: {e}")
        return None


async def transcribe_audio(audio_data: bytes, filename: str = "audio.webm") -> str:
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise ValueError("EMERGENT_LLM_KEY not set")

    # Compress large files to avoid Whisper's 25 MB limit.
    # 30 min WebM ≈ 28 MB → 32 kbps mono MP3 ≈ 7 MB.
    if len(audio_data) > WHISPER_MAX_BYTES:
        suffix = os.path.splitext(filename)[1] or ".webm"
        logger.info(
            "Audio is %d MB — compressing to 16 kHz/32 kbps MP3 for Whisper",
            len(audio_data) // (1024 * 1024),
        )
        loop = asyncio.get_running_loop()
        audio_data = await loop.run_in_executor(None, _compress_to_mp3, audio_data, suffix)
        filename = "audio.mp3"
        logger.info("Compressed to %d MB", len(audio_data) // (1024 * 1024))

    suffix = os.path.splitext(filename)[1] or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_data)
        tmp_path = tmp.name

    try:
        stt = OpenAISpeechToText(api_key=api_key)
        with open(tmp_path, "rb") as audio_file:
            response = await stt.transcribe(
                file=audio_file,
                model="whisper-1",
                response_format="json",
                language="en",
                prompt=CARE_TRANSCRIPTION_PROMPT,
            )
        if hasattr(response, "text"):
            return response.text
        return str(response)
    finally:
        os.unlink(tmp_path)


async def extract_document_criteria(text: str, doc_name: str) -> dict:
    """Ask GPT-4o to extract a structured list of criteria from a document."""
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise ValueError("EMERGENT_LLM_KEY not set")

    truncated = text[:8000]  # Stay well within token budget
    user_prompt = f"Document name: {doc_name}\n\nDocument content:\n{truncated}"

    chat = LlmChat(
        api_key=api_key,
        session_id=f"docparse_{uuid.uuid4()}",
        system_message=CRITERIA_EXTRACTION_PROMPT,
    ).with_model("openai", "gpt-4o")

    full_response = ""
    async for event in chat.stream_message(UserMessage(text=user_prompt)):
        from emergentintegrations.llm.chat import TextDelta, StreamDone
        if isinstance(event, TextDelta):
            full_response += event.content
        elif isinstance(event, StreamDone):
            break

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
    """Light GPT-4o call: map evidence from transcript against a single document's criteria only."""
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        return []
    doc_id = str(doc.get("id", doc.get("_id", "")))
    doc_name = doc.get("label") or doc.get("filename", "Unknown")
    criteria = doc.get("extracted_criteria", [])
    if not criteria or not transcript_text.strip():
        return []

    criteria_ctx = "\n".join([f"  - {c['ref']}: {c['name']} — {c.get('description', '')}" for c in criteria])
    system = """Map evidence from a meeting transcript against provided criteria. Return valid JSON only:
{"mappings": [{"id": "custom_n", "document_id": "the document_id value", "document_name": "doc name", "criterion_ref": "ref", "criterion_name": "name", "evidence_summary": "brief description", "transcript_excerpt": "exact quote", "confidence": "likely_evidence|needs_review|not_enough_evidence"}]}
Only include criteria with actual evidence. Return empty mappings array if nothing found."""

    chat = LlmChat(api_key=api_key, session_id=f"rescan_{uuid.uuid4()}", system_message=system).with_model("openai", "o4-mini").with_params(reasoning_effort="high")
    full = ""
    async for event in chat.stream_message(UserMessage(text=f"Document: {doc_name} (document_id: {doc_id})\nCriteria:\n{criteria_ctx}\n\nTranscript:\n{transcript_text[:5000]}")):
        from emergentintegrations.llm.chat import TextDelta, StreamDone
        if isinstance(event, TextDelta):
            full += event.content
        elif isinstance(event, StreamDone):
            break
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
- Named colleagues referenced in sensitive context (incidents, complaints, disciplinary matters)
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
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if api_key and transcript_text.strip():
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

        user_prompt = (
            f"Scan this supervision transcript for third-party PII:{participant_note}\n\n"
            f"TRANSCRIPT:\n{transcript_text[:8000]}"
        )

        try:
            chat = LlmChat(
                api_key=api_key,
                session_id=f"pii_scan_{uuid.uuid4()}",
                system_message=PII_SCAN_SYSTEM_PROMPT,
            ).with_model("openai", "gpt-4o")

            full_response = ""
            async for event in chat.stream_message(UserMessage(text=user_prompt)):
                from emergentintegrations.llm.chat import TextDelta, StreamDone
                if isinstance(event, TextDelta):
                    full_response += event.content
                elif isinstance(event, StreamDone):
                    break

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
            logger.error(f"AI PII scan failed: {e}")
            # Return regex-only results on AI failure

    return flags


async def generate_meeting_summary(transcript_text: str) -> str:
    """Re-generate just the meeting summary in the new structured format."""
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise ValueError("EMERGENT_LLM_KEY not set")

    chat = LlmChat(
        api_key=api_key,
        session_id=f"summary_{uuid.uuid4()}",
        system_message=SUMMARY_ONLY_PROMPT,
    ).with_model("openai", "o4-mini").with_params(reasoning_effort="medium")

    user_prompt = f"Summarize this supervision meeting transcript:\n\n{transcript_text[:8000]}"

    full = ""
    async for event in chat.stream_message(UserMessage(text=user_prompt)):
        from emergentintegrations.llm.chat import TextDelta, StreamDone
        if isinstance(event, TextDelta):
            full += event.content
        elif isinstance(event, StreamDone):
            break

    return full.strip()


DOC_EVIDENCE_SYSTEM_PROMPT = """You are a compliance analysis specialist for UK adult social care providers.
Analyze this supervision document to identify evidence of compliance with CQC regulations, Care Certificate standards, and any additional custom standards provided.

Your output must be valid JSON only (no markdown, no extra text) in this exact structure:
{
  "cqc_mappings": [
    {
      "id": "cqc_1",
      "regulation_ref": "Regulation 18",
      "regulation_name": "Staffing",
      "evidence_summary": "Brief description of evidence found",
      "transcript_excerpt": "Exact quote from the document",
      "confidence": "likely_evidence|needs_review|not_enough_evidence"
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
      "confidence": "likely_evidence|needs_review|not_enough_evidence"
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
      "confidence": "likely_evidence|needs_review|not_enough_evidence"
    }
  ]
}

Rules:
- Only map evidence EXPLICITLY mentioned in the document
- Do not infer or assume — map only what is directly discussed
- Use "likely_evidence" only when clearly demonstrated
- Use "needs_review" when partially demonstrated or unclear
- Use "not_enough_evidence" when barely touched on
- For Care Certificate mappings, ALWAYS map to the most specific sub-outcome ref (e.g. "2.1a", "2.2h")
- For custom_mappings, only include entries if custom standards are provided AND there is actual evidence
- If no custom standards provided, return custom_mappings as an empty array []
- Generate unique IDs for each item (e.g. "cqc_1", "cc_1", "custom_1")"""


async def analyze_doc_for_evidence(
    text: str,
    cqc_standards: list,
    care_cert_standards: list,
    custom_standards: list = None,
) -> dict:
    """Map evidence from an uploaded supervision document to CQC/Care Cert/custom standards."""
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise ValueError("EMERGENT_LLM_KEY not set")

    cqc_context = "\n".join([
        f"- {s['reference']}: {s['name']}" +
        (f" [Key Questions: {', '.join(s.get('key_questions', []))}]" if s.get('key_questions') else "") +
        f" — {s.get('description', '')}"
        for s in cqc_standards[:60]
    ])

    cc_lines = []
    for s in care_cert_standards[:16]:
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

CQC REGULATIONS TO MAP AGAINST:
{cqc_context}

CARE CERTIFICATE STANDARDS TO MAP AGAINST:
{cc_context}{custom_context}

Provide your analysis as JSON only. Only map regulations/standards where there is actual evidence in the document."""

    chat = LlmChat(
        api_key=api_key,
        session_id=f"docevidence_{uuid.uuid4()}",
        system_message=DOC_EVIDENCE_SYSTEM_PROMPT,
    ).with_model("openai", "o4-mini").with_params(reasoning_effort="high")

    full_response = ""
    async for event in chat.stream_message(UserMessage(text=user_prompt)):
        from emergentintegrations.llm.chat import TextDelta, StreamDone
        if isinstance(event, TextDelta):
            full_response += event.content
        elif isinstance(event, StreamDone):
            break

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
) -> dict:
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise ValueError("EMERGENT_LLM_KEY not set")

    # Build standards context — CQC includes key questions; Care Cert includes outcomes
    cqc_context = "\n".join([
        f"- {s['reference']}: {s['name']}" +
        (f" [Key Questions: {', '.join(s.get('key_questions', []))}]" if s.get('key_questions') else "") +
        f" — {s.get('description', '')}"
        for s in cqc_standards[:60]
    ])

    # Care Certificate context — includes granular sub-outcomes for precise mapping
    cc_lines = []
    for s in care_cert_standards[:16]:
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

    user_prompt = f"""Analyze this meeting transcript and map evidence to the relevant standards.

TRANSCRIPT:{pause_note}
{transcript_text}

CQC REGULATIONS TO MAP AGAINST:
{cqc_context}

CARE CERTIFICATE STANDARDS TO MAP AGAINST:
{cc_context}{custom_context}{template_context}

Provide your analysis as JSON. Only map regulations/standards where there is actual evidence in the transcript."""

    chat = LlmChat(
        api_key=api_key,
        session_id=f"analysis_{uuid.uuid4()}",
        system_message=ANALYSIS_SYSTEM_PROMPT,
    ).with_model("openai", "o4-mini").with_params(reasoning_effort="high")

    full_response = ""
    async for event in chat.stream_message(UserMessage(text=user_prompt)):
        from emergentintegrations.llm.chat import TextDelta, StreamDone
        if isinstance(event, TextDelta):
            full_response += event.content
        elif isinstance(event, StreamDone):
            break

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
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise ValueError("EMERGENT_LLM_KEY not set")

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

    chat = LlmChat(
        api_key=api_key,
        session_id=f"prep_{uuid.uuid4().hex[:8]}",
        system_message=system_prompt,
    ).with_model("openai", "o4-mini").with_params(reasoning_effort="high")

    response = await chat.send_message(UserMessage(text=user_prompt))
    full_response = response.text.strip() if hasattr(response, "text") else str(response)

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
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        return {"results": {}, "checked_at": None}
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
        chat = LlmChat(
            api_key=api_key,
            session_id=f"cov_{uuid.uuid4().hex[:8]}",
            system_message=system_prompt,
        ).with_model("openai", "gpt-4o")

        response = await chat.send_message(UserMessage(text=user_prompt))
        full_response = response.text.strip() if hasattr(response, "text") else str(response)

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
