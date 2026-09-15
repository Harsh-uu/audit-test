"""Background pipeline: transcribe an uploaded recording then run AI compliance analysis.

Lives in utils/ (not routers/processing.py) so utils/job_worker.py can import it at
module load time without creating a routers.processing <-> utils.job_worker circular
import (processing.py imports enqueue_job from job_worker; job_worker previously had
to lazily import this function back from processing.py to avoid that cycle).
"""
from datetime import datetime, timezone
import asyncio
import json
import logging
import os
import uuid
from utils.supabase_storage import get_audio
from utils.ai import analyze_meeting, diarize_transcript, transcribe_with_assemblyai, map_speaker_numbers_to_names, generate_meeting_summary
import database
from routers.admin import _stats_cache as _admin_stats_cache

logger = logging.getLogger(__name__)


def _jlist(val):
    """Parse a JSONB value that asyncpg may return as a raw string when RLS role is active."""
    if isinstance(val, list): return val
    if isinstance(val, str):
        try: return json.loads(val)
        except Exception: return []
    return val or []


def _jdict(val):
    """Parse a JSONB value that asyncpg may return as a raw string; returns a dict."""
    if isinstance(val, dict): return val
    if isinstance(val, str):
        try: return json.loads(val)
        except Exception: return {}
    return val or {}


def _parse_std_row(r) -> dict:
    """Normalize standards_entries JSONB columns (sub_outcomes, key_questions, keywords)."""
    s = dict(r)
    for f in ("sub_outcomes", "key_questions", "keywords"):
        s[f] = _jlist(s.get(f))
    return s


def _match_attendee_user_id(name: str, attendees: list) -> str:
    """Best-effort match of an AI-extracted assignee name to a real attendee's user_id.

    The AI extracts the assignee straight from the transcript, so it's usually just a
    first name (e.g. "Priya"), not the attendee's full stored name ("Priya Sharma") —
    exact-equality alone would almost never match. Try exact full-name match first,
    then fall back to a first-name-token match, but only when it resolves to exactly
    one attendee (an ambiguous match is treated as no match).
    """
    if not name:
        return None
    name_lower = name.strip().lower()
    for a in attendees:
        if a.get("user_id") and a.get("name", "").strip().lower() == name_lower:
            return a["user_id"]
    token_matches = {
        a["user_id"] for a in attendees
        if a.get("user_id") and a.get("name", "").strip().lower().split(" ")[0] == name_lower
    }
    if len(token_matches) == 1:
        return token_matches.pop()
    return None


async def _get_rolled_actions(conn, attendees: list, current_meeting_id: str, manager_id: str = None) -> list:
    """Return incomplete actions from previous meetings relevant to these supervisees.

    A "supervisee" here is any attendee whose account role is NOT manager/admin
    (checked via the role stored on the attendee record itself), in addition to
    excluding whoever is set as this meeting's sign_off_manager_id. Relying on
    sign_off_manager_id alone is not enough — it's an optional field and, if left
    unset, a manager who is a genuine co-attendee of two different supervisees'
    meetings would incorrectly look like a "shared supervisee" linking the two,
    dragging one supervisee's outstanding actions into the other's meeting.
    """
    supervisee_ids = [
        a.get("user_id") for a in attendees
        if a.get("user_id") and a.get("role") not in ("manager", "admin") and a.get("user_id") != manager_id
    ]
    if not supervisee_ids:
        return []

    new_attendee_names_lower = {a.get("name", "").lower() for a in attendees if a.get("name")}
    new_supervisee_ids = set(supervisee_ids)
    rolled = []
    seen_sources = set()

    prev_rows = await conn.fetch(
        """SELECT id, attendees, analysis_id, title, sign_off_manager_id
           FROM meetings
           WHERE analysis_id IS NOT NULL
             AND id != $1
             AND EXISTS (
                 SELECT 1 FROM jsonb_array_elements(
                     CASE WHEN jsonb_typeof(COALESCE(attendees,'[]'::jsonb)) = 'array'
                          THEN COALESCE(attendees,'[]'::jsonb) ELSE '[]'::jsonb END
                 ) elem
                 WHERE elem->>'user_id' = ANY($2::text[])
             )
           LIMIT 50""",
        current_meeting_id, supervisee_ids,
    )

    # PERF-003: filter matching previous meetings first, then fetch every
    # matching meeting's analysis actions in one query, instead of one
    # SELECT per previous meeting.
    matching_prevs = []
    supervisee_ids_set = set(supervisee_ids)
    for prev in prev_rows:
        prev = dict(prev)
        source_manager_id = prev.get("sign_off_manager_id")
        source_supervisee_ids = {
            a.get("user_id")
            for a in _jlist(prev.get("attendees"))
            if a.get("user_id") and a.get("role") not in ("manager", "admin") and a.get("user_id") != source_manager_id
        }
        if not source_supervisee_ids.intersection(supervisee_ids_set):
            continue
        matching_prevs.append(prev)

    analysis_ids = [p["analysis_id"] for p in matching_prevs if p.get("analysis_id")]
    actions_by_analysis_id = {}
    if analysis_ids:
        a_rows = await conn.fetch(
            "SELECT id, actions FROM analyses WHERE id = ANY($1::uuid[])",
            analysis_ids,
        )
        actions_by_analysis_id = {r["id"]: r["actions"] for r in a_rows}

    for prev in matching_prevs:
        analysis_actions = actions_by_analysis_id.get(prev.get("analysis_id"))
        if analysis_actions is None:
            continue

        for action in _jlist(analysis_actions):
            if action.get("completed") or action.get("is_rolled_over"):
                continue
            key = (prev["id"], action.get("id", ""))
            if key in seen_sources:
                continue

            assigned_uid = action.get("assigned_to_user_id")
            if assigned_uid:
                # Strict match — a linked assignee must be a supervisee on this new meeting too.
                if assigned_uid not in new_supervisee_ids:
                    continue
            else:
                # Legacy/unlinked action — fall back to fuzzy name matching.
                assigned = (action.get("assigned_to") or "").strip().lower()
                if assigned and new_attendee_names_lower and assigned not in new_attendee_names_lower:
                    continue

            seen_sources.add(key)
            rolled.append({
                **action,
                "id": f"rolled_{prev['id'][:6]}_{action.get('id', uuid.uuid4().hex[:6])}",
                "is_rolled_over": True,
                "completed": False,
                "completed_at": None,
                "source_meeting_id": prev["id"],
                "source_meeting_title": prev.get("title", "Previous Meeting"),
                "source_action_id": action.get("id"),
            })
    return rolled


async def run_transcription_and_analysis(meeting_id: str, audio_path: str):
    """Background task: transcribe audio then run AI analysis."""
    try:
        async with database.with_admin() as conn:
            await conn.execute(
                "UPDATE meetings SET status='transcribing', updated_at=$1 WHERE id=$2",
                datetime.now(timezone.utc).isoformat(), meeting_id,
            )
            meeting_row = await conn.fetchrow(
                "SELECT attendees, org_id, sign_off_manager_name, created_by_name, sign_off_manager_id, "
                "meeting_type, paused_periods FROM meetings WHERE id = $1", meeting_id
            )

        meeting = dict(meeting_row) if meeting_row else {}
        attendee_count = len(_jlist(meeting.get("attendees"))) or None
        meeting_org_id = meeting.get("org_id")

        audio_data, _ = await get_audio(audio_path)

        logger.info(f"Starting transcription for meeting {meeting_id}")
        assemblyai_key = os.environ.get("ASSEMBLYAI_API_KEY")
        numbered_speaker_text = None
        transcript_warnings = []

        if assemblyai_key:
            try:
                transcript_text, numbered_speaker_text, timestamped_plain, transcript_warnings = await transcribe_with_assemblyai(
                    audio_data, speakers_expected=attendee_count
                )
            except Exception as aai_err:
                logger.error(f"AssemblyAI transcription failed for meeting {meeting_id}: {aai_err}")
                raise
        else:
            raise ValueError("ASSEMBLYAI_API_KEY not configured — transcription requires AssemblyAI")

        logger.info(f"Transcription complete for meeting {meeting_id}: {len(transcript_text)} chars")

        now = datetime.now(timezone.utc).isoformat()
        transcript_id = str(uuid.uuid4())

        async with database.with_admin() as conn:
            await conn.execute(
                """INSERT INTO transcripts (id, meeting_id, org_id, text, safety_warnings, created_at)
                   VALUES ($1,$2,$3,$4,$5::jsonb,$6)""",
                transcript_id, meeting_id, meeting_org_id,
                transcript_text, transcript_warnings, now,
            )
            await conn.execute(
                """UPDATE meetings SET transcript_id=$1, status='analyzing', updated_at=$2,
                   transcript_has_warnings=$3 WHERE id=$4""",
                transcript_id, now, len(transcript_warnings) > 0, meeting_id,
            )

        # Load org jurisdiction — from cache (no DB hit if already seen)
        from utils import standards_cache as sc
        cached_org = sc.get_org_info(meeting_org_id)
        if cached_org:
            org_jurisdiction = cached_org["jurisdiction"]
            org_service_type = cached_org["service_type"]
        else:
            async with database.with_admin() as conn:
                org_row = await conn.fetchrow(
                    "SELECT jurisdiction, service_type FROM organisations WHERE id=$1", meeting_org_id
                )
            org_jurisdiction = (org_row["jurisdiction"] if org_row else None) or "england"
            org_service_type = (org_row["service_type"] if org_row else None) or ""
            sc.set_org_info(meeting_org_id, org_jurisdiction, org_service_type)

        # Load standards from in-process cache — zero DB hits after first warm
        if org_jurisdiction == "wales":
            cqc_rows    = sc.get_system("ciw", "wales")
            care_cert_rows = sc.get_system("awif", "wales") + sc.get_system("scw", "wales")
        elif org_jurisdiction == "scotland":
            cqc_rows    = sc.get_system("ci", "scotland")
            care_cert_rows = sc.get_system("sssc", "scotland")
        elif org_jurisdiction == "northern_ireland":
            rqia_type = "rqia_dom" if org_service_type == "domiciliary" else "rqia_res"
            cqc_rows    = sc.get_system(rqia_type, "northern_ireland")
            care_cert_rows = (sc.get_system("niscc_code", "northern_ireland") +
                              sc.get_system("niscc_induction", "northern_ireland"))
        else:  # england
            cqc_rows    = sc.get_system("cqc")
            care_cert_rows = sc.get_system("care_cert")
        cqc_standards = [_parse_std_row(r) for r in cqc_rows]
        care_cert_standards = [_parse_std_row(r) for r in care_cert_rows]

        if meeting_org_id:
            custom_standards = sc.get_custom_docs(meeting_org_id)
            if custom_standards is None:
                async with database.with_org(meeting_org_id) as conn:
                    custom_rows = await conn.fetch(
                        "SELECT id, label, filename, extracted_criteria FROM standards_documents "
                        "WHERE org_id=$1 AND is_active=TRUE AND parse_status='parsed'",
                        meeting_org_id,
                    )
                custom_standards = [dict(r) for r in custom_rows]
                sc.set_custom_docs(meeting_org_id, custom_standards)
        else:
            custom_standards = []

        # Load supervision template
        supervision_template = None
        async with database.with_admin() as conn:
            tmpl_row = await conn.fetchrow(
                "SELECT data FROM settings WHERE id=$1",
                f"supervision_template:{meeting_org_id}",
            ) if meeting_org_id else None
            if not tmpl_row:
                tmpl_row = await conn.fetchrow(
                    "SELECT data FROM settings WHERE id='supervision_template'"
                )
        if tmpl_row and _jdict(tmpl_row["data"]).get("steps"):
            supervision_template = _jdict(tmpl_row["data"])

        # Fetch rolled-over actions
        attendees = _jlist(meeting.get("attendees"))
        manager_name = meeting.get("sign_off_manager_name") or meeting.get("created_by_name") or "Manager"
        manager_id = meeting.get("sign_off_manager_id")

        async with database.with_admin() as conn:
            rolled_actions = await _get_rolled_actions(
                conn, attendees, meeting_id, manager_id=manager_id
            )

        meeting_type = (meeting.get("meeting_type") or "supervision").replace("_", " ").title()
        supervisee_names = [a.get("name") for a in attendees if a.get("name")]

        if numbered_speaker_text:
            diarize_coro = map_speaker_numbers_to_names(numbered_speaker_text, manager_name, supervisee_names, meeting_type)
        else:
            diarize_coro = diarize_transcript(transcript_text, manager_name, supervisee_names, meeting_type)

        paused_periods = meeting.get("paused_periods") or []
        # Build effective jurisdiction string (NI needs service_type suffix for AI prompt routing)
        effective_jurisdiction = org_jurisdiction
        if org_jurisdiction == "northern_ireland":
            effective_jurisdiction = f"northern_ireland_{org_service_type or 'domiciliary'}"

        results = await asyncio.gather(
            analyze_meeting(
                timestamped_plain, cqc_standards, care_cert_standards, paused_periods, custom_standards,
                supervision_template, jurisdiction=effective_jurisdiction,
                manager_name=manager_name, attendee_names=supervisee_names, meeting_type=meeting_type,
            ),
            diarize_coro,
            generate_meeting_summary(timestamped_plain, manager_name=manager_name, attendee_names=supervisee_names),   # runs concurrently — zero added latency
            return_exceptions=True,
        )
        analysis_result = results[0]
        speaker_text = results[1]
        dedicated_summary = results[2]

        if isinstance(analysis_result, Exception):
            raise analysis_result
        if isinstance(speaker_text, Exception) or not speaker_text:
            logger.warning(f"Diarization non-fatal failure for meeting {meeting_id}: {speaker_text}")
            speaker_text = None
        else:
            async with database.with_admin() as conn:
                await conn.execute(
                    "UPDATE transcripts SET speaker_text=$1 WHERE id=$2",
                    speaker_text, transcript_id,
                )

        # Replace the compliance analyst's summary (produced as a side-effect of evidence
        # extraction) with the dedicated summariser's output, which focuses entirely on
        # writing a clear, specific, human narrative. Falls back to the original if the
        # dedicated call fails.
        if dedicated_summary and not isinstance(dedicated_summary, Exception) and str(dedicated_summary).strip():
            analysis_result["summary"] = str(dedicated_summary).strip()

        cqc_kq_map = {s["reference"]: s.get("key_questions") or [] for s in cqc_standards}
        for item in analysis_result.get("cqc_mappings", []):
            item.setdefault("status", "pending")
            item.setdefault("edited_evidence_summary", None)
            item.setdefault("notes", "")
            if not item.get("key_questions"):
                item["key_questions"] = cqc_kq_map.get(item.get("regulation_ref", ""), [])
        for item in analysis_result.get("care_cert_mappings", []):
            item.setdefault("status", "pending")
            item.setdefault("edited_evidence_summary", None)
            item.setdefault("notes", "")
        for item in analysis_result.get("custom_mappings", []):
            item.setdefault("status", "pending")
            item.setdefault("edited_evidence_summary", None)
            item.setdefault("notes", "")

        for item in analysis_result.get("actions", []):
            if not item.get("id"):
                item["id"] = f"action_{uuid.uuid4().hex[:12]}"
            item.setdefault("completed", False)
            item.setdefault("completed_at", None)
            item.setdefault("is_rolled_over", False)
            item["assigned_to_user_id"] = _match_attendee_user_id(item.get("assigned_to"), attendees)
        for item in analysis_result.get("learning_needs", []):
            if not item.get("id"):
                item["id"] = f"ln_{uuid.uuid4().hex[:12]}"
            item.setdefault("completed", False)
            item["assigned_to_user_id"] = _match_attendee_user_id(item.get("assigned_to"), attendees)
        analysis_result["actions"] = rolled_actions + analysis_result.get("actions", [])

        analysis_id = str(uuid.uuid4())
        async with database.with_admin() as conn:
            # Core INSERT — only columns guaranteed to exist in any schema version
            await conn.execute(
                """INSERT INTO analyses
                   (id, meeting_id, org_id, summary, actions, risks,
                    cqc_mappings, care_cert_mappings, created_at)
                   VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7::jsonb,$8::jsonb,$9)""",
                analysis_id, meeting_id, meeting_org_id,
                analysis_result.get("summary", ""),
                analysis_result.get("actions", []),
                analysis_result.get("risks", []),
                analysis_result.get("cqc_mappings", []),
                analysis_result.get("care_cert_mappings", []),
                now,
            )
            # Optional UPDATE for columns added after initial schema — safe to fail
            try:
                await conn.execute(
                    "UPDATE analyses SET custom_mappings=$1::jsonb WHERE id=$2",
                    analysis_result.get("custom_mappings", []), analysis_id,
                )
            except Exception as _col_err:
                logger.warning(f"custom_mappings update skipped (column may not exist yet): {_col_err}")
            try:
                await conn.execute(
                    "UPDATE analyses SET achievements=$1::jsonb WHERE id=$2",
                    analysis_result.get("achievements", []), analysis_id,
                )
            except Exception as _col_err:
                logger.warning(f"achievements update skipped (column may not exist yet): {_col_err}")
            try:
                await conn.execute(
                    "UPDATE analyses SET learning_needs=$1::jsonb WHERE id=$2",
                    analysis_result.get("learning_needs", []), analysis_id,
                )
            except Exception as _col_err:
                logger.warning(f"learning_needs update skipped (column may not exist yet): {_col_err}")
            await conn.execute(
                "UPDATE meetings SET analysis_id=$1, status='in_review', processing_error=NULL, updated_at=$2 WHERE id=$3",
                analysis_id, datetime.now(timezone.utc).isoformat(), meeting_id,
            )
            # Bust the admin stats cache — meeting count moved to in_review
            _admin_stats_cache.pop(meeting_org_id or "", None)
        logger.info(f"Analysis complete for meeting {meeting_id}")

        # Phase 4: prep coverage check
        try:
            async with database.with_admin() as conn:
                prep_row = await conn.fetchrow(
                    "SELECT sections FROM meeting_prep WHERE meeting_id=$1", meeting_id
                )
            if prep_row and _jlist(prep_row.get("sections")):
                from utils.ai import check_prep_coverage
                all_questions = []
                for section in _jlist(prep_row.get("sections")):
                    for q in section.get("questions", []):
                        if q.get("included", True) and q.get("text"):
                            all_questions.append({"id": q["id"], "text": q["text"]})
                if all_questions:
                    coverage = await check_prep_coverage(transcript_text, all_questions)
                    async with database.with_admin() as conn:
                        await conn.execute(
                            "UPDATE meeting_prep SET coverage_results=$1::jsonb, coverage_checked_at=$2 WHERE meeting_id=$3",
                            coverage.get("results", {}),
                            coverage.get("checked_at"),
                            meeting_id,
                        )
        except Exception as cov_exc:
            logger.warning(f"Prep coverage check non-fatal failure for {meeting_id}: {cov_exc}")

    except Exception as e:
        err_msg = str(e)[:500]
        logger.error(f"Processing failed for meeting {meeting_id}: {err_msg}")
        async with database.with_admin() as conn:
            await conn.execute(
                "UPDATE meetings SET status='processing_failed', processing_error=$1, updated_at=$2 WHERE id=$3",
                err_msg, datetime.now(timezone.utc).isoformat(), meeting_id,
            )
