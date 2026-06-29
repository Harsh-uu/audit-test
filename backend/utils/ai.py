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
  "summary": "3-5 sentence meeting summary",
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
- Generate unique IDs for each item (e.g. "action_1", "risk_1", "cqc_1", "cc_1", "custom_1")"""


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
Deepgram has already identified distinct speakers as Speaker 0, Speaker 1, Speaker 2 etc. using audio fingerprinting.
Your task is to replace those generic labels with the real participant names provided.

Rules:
- Identify which numbered speaker corresponds to which named participant by reading the conversation
- The manager/supervisor steers the agenda, asks questions about the worker's practice, and conducts the meeting
- The worker/supervisee reports on their own work and development
- Do NOT change any spoken words — only replace the speaker label at the start of each line
- If there are more numbered speakers than named participants (e.g. crosstalk artefacts), assign them to the closest matching participant
- Output ONLY the reformatted transcript — no preamble, explanation, or markdown"""


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
        numbered_speaker_text = plain_text

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
        f"NUMBERED TRANSCRIPT (replace Speaker 0/1/2 with real names):\n{numbered_speaker_text[:14000]}"
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
    label_hint = " / ".join(f"{l}:" for l in all_labels)

    user_prompt = (
        f"Meeting type: {meeting_type}\n\n"
        f"PARTICIPANTS ({len(participants)} people):\n{participants_block}\n\n"
        f"RAW TRANSCRIPT:\n{transcript_text[:14000]}\n\n"
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

    chat = LlmChat(api_key=api_key, session_id=f"rescan_{uuid.uuid4()}", system_message=system).with_model("openai", "gpt-4o")
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
        for s in cqc_standards[:20]
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
    ).with_model("openai", "gpt-4o")

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
