# PRD — Supervision Meeting Compliance App

## Original Problem Statement
React + FastAPI + PostgreSQL (Supabase) app for UK adult social care providers. Managers record/upload supervision meeting audio; AI (Gemini primary, OpenAI fallback) transcribes, diarizes, and analyzes transcripts to surface CQC/Care Certificate compliance evidence, risks, achievements, learning needs, and actions. Strict RLS multi-tenant isolation. Includes EULA acceptance flow, Super Admin management/reporting, public resources, MFA authentication.

## Architecture
- Frontend: React + Vite + PWA (`/app/frontend`)
- Backend: FastAPI + AsyncPG + Postgres/Supabase (`/app/backend`)
- RLS via `app_default` role; `DATABASE_URL` (superuser/migrations) vs `APP_DATABASE_URL` (RLS-scoped app queries) — never mix these
- AI: `emergentintegrations`-routed Gemini (Vertex AI, UK/EU residency) as primary, OpenAI as fallback, orchestrated in `/app/backend/utils/ai.py`

## Key DB Schema
- `eula_versions`, `meetings`, `analyses` (incl. `ai_provider`, `initial_ai_provider`), `teams`

## What's Been Implemented (with dates)

### Prior sessions
- Meeting type dropdown: 14 fixed options + "Other"
- EULA text swapped in-place without re-gating (m029)
- DB perf: dynamic `statement_cache_size`; `get_current_user` refactored to yield-dependency for connection reuse
- Meetings page consolidated into `GET /api/meetings/page-data` (was 3 calls) + `GET /api/org/structure-lite`
- AI provider tracking: migrations m030/m031 (`ai_provider`, `initial_ai_provider`) + Super Admin AI Usage report (`GET /api/super-admin/ai-usage`) + frontend tab (`SuperAdminAIUsage.js`)
- AI fallback: 1-retry before downgrading Gemini→OpenAI (transient blip protection)
- Prompt fix: stopped penalizing staff with "communication pattern" risk when manager rushes session
- Grafana/Loki: suppressed noisy httpx logs, labeled preview logs `env=preview`
- Confidentiality/PII checker: fixed timeout on 80+ min transcripts (concurrent chunk processing instead of sequential) + UI retry-on-error state

### This session (2026-09-23) — Gemini evidence-scan tuning (based on direct Google engineer feedback)
- **Diagnostic**: Shared full evidence-scan system prompt + generation settings with user for their Google conversation. Found transcript hard-truncates at 80,000 chars (`transcript_text[:80000]` in `analyze_meeting`) — flagged as a cliff-edge worth raising with Google if transcripts exceed ~13-14k words.
- **Generation-config split** in `/app/backend/utils/ai.py` — threaded a `warm: bool = False` param through `_openai_chat` → `_vertex_generate_sync` → `_gemini_chat` → `_ai_chat` → `_ai_chat_json`:
  - **Precise (default, warm=False)**: `temperature=0.0`, `top_p=0.1`, `top_k=1` — used by `analyze_meeting`, `analyze_doc_for_evidence`, `analyze_custom_only`, `scan_pii_in_transcript`, `diarize_transcript`, `map_speaker_numbers_to_names`, `extract_document_criteria`, `check_prep_coverage` (all extraction/classification/mapping tasks — removes sampling drift causing evidence-count variance between first scan and rescan)
  - **Warm (warm=True)**: `temperature=0.3`, top_p/top_k left at Gemini defaults — used ONLY by `generate_meeting_summary`, `generate_prep_questions`, `generate_risk_suggestions` (human-facing conversational/coaching text where natural phrasing variation is desirable)
- **CRITICAL SCAN MANDATE**: added a 2-step reasoning instruction (exhaustive inventory pass → multi-standard assignment, one utterance can map to multiple standards) to `ANALYSIS_SYSTEM_PROMPT`, `DOC_EVIDENCE_SYSTEM_PROMPT`, and `analyze_custom_only`'s inline prompt — DRY'd into a shared `_CRITICAL_SCAN_MANDATE` template constant to avoid the 3 copies drifting apart.
- Tested via `testing_agent`: 27/27 pass (21 static/mocked config-kwarg checks + 6 live E2E). Live `analyze_meeting` on a realistic transcript produced 47 cqc_mappings + 5 care_cert_mappings, served by `gemini-2.5-flash` in 55.1s. Warm-path calls (summary/prep-questions/risk-suggestions) confirmed still producing natural, well-formatted text. AI Usage report confirmed showing real (non-null) provider values. No regressions. Test file: `/app/backend/tests/test_iter152_warm_precise_config.py`.
- Note: `gemini-2.5-flash` model itself was NOT changed to `gemini-3.1-flash-lite` in this session — user pivoted from the model-migration plan to this generation-config + prompt-mandate tuning approach instead, after independently consulting Google. The 3.1 migration remains parked, not abandoned — revisit only if user raises it again.

## Prioritized Backlog

### P0
- None open. Monitor real-world evidence-scan results on the next long transcript (80+ min) to confirm the precise+mandate combo actually closes the gap between first-scan and rescan evidence counts in production usage (not just the 1.7k-char test fixture).

### P1
- None open.

### P2
- Storage Reconciliation Job: periodic sweep for orphaned files across upload buckets
- Rejection Trend Alerts: notify admins when a standard's AI evidence rejection rate climbs
- Live Connection Dashboard: super-admin view of real-time DB pool/connection health
- Intermittent UI glitch on Meetings page (click tile → briefly renders → bounces to tile list → works on 2nd click) — BLOCKED, user parked it ("hold for now", suspected cache issue, not reproducible). Revisit only if user raises it again — check `useMeetingReport` hooks / routing in `MeetingReport.js`/`Meetings.js`.
- 80,000-char transcript truncation cliff-edge in `analyze_meeting` (~13-14k words) — not currently causing issues but worth monitoring/raising with Google if very long meetings start hitting it.

### P3
- Course Completion Tracker: let logged-in users tick off Resources course modules as they finish them

## Testing Status
- Test reports: `/app/test_reports/iteration_149.json` through `iteration_152.json`
- Known regressions: None
- Credentials: `/app/memory/test_credentials.md`
