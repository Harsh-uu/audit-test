import os
import json
import logging
import uuid
from emergentintegrations.llm.chat import LlmChat, UserMessage
from emergentintegrations.llm.openai import OpenAISpeechToText

logger = logging.getLogger(__name__)

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
      "outcome_ref": "2.1",
      "outcome_name": "Agree a personal development plan",
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
- For Care Certificate mappings, ALWAYS include the specific outcome_ref and outcome_name (e.g. "2.1" and "Agree a personal development plan"). Choose the single most relevant outcome for the evidence found.
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


async def transcribe_audio(audio_data: bytes, filename: str = "audio.webm") -> str:
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise ValueError("EMERGENT_LLM_KEY not set")

    import tempfile
    import os as _os
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
        tmp.write(audio_data)
        tmp_path = tmp.name

    try:
        stt = OpenAISpeechToText(api_key=api_key)
        with open(tmp_path, "rb") as audio_file:
            response = await stt.transcribe(
                file=audio_file,
                model="whisper-1",
                response_format="verbose_json",
                language="en",
                timestamp_granularities=["segment"],
            )
        if hasattr(response, "text"):
            return response.text
        return str(response)
    finally:
        _os.unlink(tmp_path)


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


async def analyze_meeting(
    transcript_text: str,
    cqc_standards: list,
    care_cert_standards: list,
    paused_periods: list,
    custom_standards: list = None,
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

    # Care Certificate context includes outcomes for precise outcome-level mapping
    cc_lines = []
    for s in care_cert_standards[:16]:
        line = f"- {s['reference']}: {s['name']}"
        outcomes = s.get("outcomes", [])
        if outcomes:
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

    pause_note = ""
    if paused_periods:
        pause_note = f"\n\nNOTE: The recording was paused {len(paused_periods)} time(s) during this meeting. Paused sections are not included in the transcript."

    user_prompt = f"""Analyze this meeting transcript and map evidence to the relevant standards.

TRANSCRIPT:{pause_note}
{transcript_text}

CQC REGULATIONS TO MAP AGAINST:
{cqc_context}

CARE CERTIFICATE STANDARDS TO MAP AGAINST:
{cc_context}{custom_context}

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

    pause_note = ""
    if paused_periods:
        pause_note = f"\n\nNOTE: The recording was paused {len(paused_periods)} time(s) during this meeting. Paused sections are not included in the transcript."

    user_prompt = f"""Analyze this meeting transcript and map evidence to the relevant standards.

TRANSCRIPT:{pause_note}
{transcript_text}

CQC REGULATIONS TO MAP AGAINST:
{cqc_context}

CARE CERTIFICATE STANDARDS TO MAP AGAINST:
{cc_context}

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
        # Clean up if wrapped in code blocks
        text = full_response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
        result = json.loads(text)
        return result
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI response: {e}\nResponse: {full_response[:500]}")
        return {
            "summary": "Analysis could not be parsed. Please review the transcript manually.",
            "actions": [],
            "risks": [],
            "cqc_mappings": [],
            "care_cert_mappings": [],
        }
