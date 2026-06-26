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
                response_format="json",
                language="en",
                prompt=CARE_TRANSCRIPTION_PROMPT,
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
