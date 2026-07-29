# Supervision 2.0 — Full MongoDB Schema Reference

Generated: Feb 2026  
Database: MongoDB (via Motor async driver)  
All `_id` fields are BSON ObjectId unless noted.

---

## Collections Index

| Collection | Purpose |
|---|---|
| `users` | All user accounts (all roles, all orgs) |
| `organisations` | Multi-tenant org records |
| `meetings` | Core meeting records |
| `transcripts` | Audio transcription output |
| `analyses` | AI-generated analysis (summary, actions, risks, evidence maps) |
| `audio_files` | Audio upload metadata + GDPR deletion tracking |
| `reviewer_comments` | Post-sign-off comments |
| `review_edits` | Audit log of text edits (summary, actions, evidence) |
| `audit_logs` | System-level event log (speaker edits, PII review, etc.) |
| `standards_entries` | User-managed CQC/Care Cert standards (system + org-custom) |
| `standards` | Read-only system CQC regulations / quality statements (seeded) |
| `standards_documents` | Uploaded org documents parsed into AI criteria |
| `settings` | Key-value store — supervision templates (`supervision_template:{org_id}`) |
| `org_settings` | Org structural settings (departments/care homes) |
| `teams` | Teams within a setting |
| `schedules` | Recurring supervision schedule templates per staff member |
| `meeting_types` | Configurable meeting type definitions per org |
| `supervision_uploads` | Imported previous supervision documents (PDF/DOCX) |
| `meeting_prep` | Dynamic Supervision prep agendas + coverage results |
| `focus_topics` | Org-scoped focus topics for Dynamic Supervision |
| `invitations` | Invite tokens for new org admin onboarding |
| `login_attempts` | Brute force tracking (IP+email keyed) |
| `password_reset_tokens` | Single-use password reset tokens |
| `refresh_tokens` | (Sparse) refresh token records (used by super admin cascade delete) |

---

## `users`

```json
{
  "_id": "ObjectId",
  "email": "string (lowercase, unique)",
  "password_hash": "string (bcrypt)",
  "name": "string",
  "role": "admin | manager | attendee | shared_reviewer | super_admin",
  "org_id": "string (ObjectId ref → organisations)",
  "is_active": "bool",
  "must_change_password": "bool (optional, true for super-admin created users)",
  "team_id": "string (ObjectId ref → teams, optional)",
  "setting_id": "string (ObjectId ref → org_settings, optional)",
  "org_scope": "setting | team | null (optional)",
  "created_at": "ISO datetime string",
  "password_changed_at": "ISO datetime string (optional)"
}
```

**Indexes:** `email` (unique), `org_id`

---

## `organisations`

```json
{
  "_id": "ObjectId",
  "name": "string",
  "slug": "string (URL-safe, unique)",
  "status": "active | suspended",
  "branding": {
    "logo_path": "string | null",
    "primary_color": "string (hex) | null"
  },
  "created_at": "ISO datetime string",
  "updated_at": "ISO datetime string (optional)"
}
```

---

## `meetings`

```json
{
  "_id": "ObjectId",
  "title": "string",
  "date": "string (ISO datetime, e.g. 2026-07-15T10:00)",
  "location": "string | null",
  "meeting_type": "string (e.g. supervision, appraisal)",
  "org_id": "string (ObjectId ref → organisations)",
  "created_by": "string (user_id)",
  "created_by_name": "string",
  "sign_off_manager_id": "string (user_id) | null",
  "sign_off_manager_name": "string | null",
  "team_id": "string | null",
  "setting_id": "string | null",
  "schedule_id": "string (ObjectId ref → schedules) | null",
  "status": "draft | processing | transcribing | analyzing | in_review | reviewed | signed_off | shared | processing_failed",
  "attendees": [
    {
      "user_id": "string",
      "name": "string",
      "email": "string",
      "role": "string",
      "present": "bool",
      "reviewed": "bool",
      "reviewed_at": "ISO datetime string | null"
    }
  ],
  "shared_with": ["string (user_ids)"],
  "recording_events": [
    {
      "type": "notice_acknowledged | started | paused | resumed | stopped",
      "user_id": "string",
      "user_name": "string",
      "timestamp": "ISO datetime string"
    }
  ],
  "paused_periods": [
    {
      "start": "ISO datetime string",
      "end": "ISO datetime string",
      "duration_seconds": "number"
    }
  ],
  "total_paused_duration_seconds": "number",
  "recording_notice_shown_at": "ISO datetime string | null",
  "audio_file_id": "string (ObjectId ref → audio_files) | null",
  "transcript_id": "string (ObjectId ref → transcripts) | null",
  "analysis_id": "string (ObjectId ref → analyses) | null",
  "sign_off_record": {
    "signed_by": "string (user_id)",
    "signed_by_name": "string",
    "signed_at": "ISO datetime string"
  },
  "audio_deletion_status": "none | grace_period | deleted",
  "audio_grace_period_started_at": "ISO datetime string | null",
  "audio_deleted_at": "ISO datetime string | null",
  "pii_review_status": "reviewed | null",
  "pii_reviewed_at": "ISO datetime string | null",
  "pii_reviewed_by": "string (user_id) | null",
  "pii_reviewed_by_name": "string | null",
  "pii_skipped": "bool | null",
  "pii_redactions": [
    {
      "id": "string",
      "original": "string (PII text)",
      "replacement": "string (e.g. [Redacted])",
      "type": "string",
      "added_at": "ISO datetime string",
      "added_by": "string (user_id)"
    }
  ],
  "diarize_status": "processing | done | failed | null",
  "rescan_status": "processing | done | failed | null",
  "retranscribed_at": "ISO datetime string | null",
  "created_at": "ISO datetime string",
  "updated_at": "ISO datetime string"
}
```

**Indexes:** `org_id`, `status`, `attendees.user_id`, `created_at`

---

## `transcripts`

```json
{
  "_id": "ObjectId",
  "meeting_id": "string",
  "text": "string (raw full transcript)",
  "speaker_text": "string (formatted 'Speaker: turn...' lines, optional)",
  "speaker_colors": "object (speaker_label → hex color, optional)",
  "speaker_text_edited_by_name": "string | null",
  "speaker_text_edited_at": "ISO datetime string | null",
  "speaker_text_backup": "string (previous speaker_text, optional)",
  "speaker_text_backup_at": "ISO datetime string | null",
  "speaker_text_backup_by": "string | null",
  "retranscribed_at": "ISO datetime string | null",
  "updated_at": "ISO datetime string | null",
  "created_at": "ISO datetime string"
}
```

---

## `analyses`

```json
{
  "_id": "ObjectId",
  "meeting_id": "string",
  "summary": "string (AI-generated, structured: intro + bullets + closing)",
  "edited_summary": "string | null (manager-edited version)",
  "actions": [
    {
      "id": "string (action_{uuid} or rolled_{src_id}_{uuid})",
      "text": "string",
      "assigned_to": "string | null",
      "due_date": "string | null",
      "completed": "bool",
      "completed_at": "ISO datetime string | null",
      "is_rolled_over": "bool",
      "source_meeting_id": "string | null",
      "source_meeting_title": "string | null"
    }
  ],
  "risks": [
    {
      "text": "string",
      "severity": "HIGH | MEDIUM | LOW"
    }
  ],
  "cqc_mappings": [
    {
      "id": "string",
      "regulation_ref": "string (e.g. Regulation 9)",
      "regulation_name": "string",
      "evidence_summary": "string",
      "edited_evidence_summary": "string | null",
      "transcript_excerpt": "string",
      "confidence": "likely_evidence | needs_review | not_enough_evidence",
      "key_questions": ["string"],
      "status": "pending | accepted | rejected | needs_followup",
      "notes": "string"
    }
  ],
  "care_cert_mappings": [
    {
      "id": "string",
      "standard_ref": "string (e.g. Standard 2)",
      "standard_name": "string",
      "outcome_ref": "string (e.g. 2.1a, optional)",
      "outcome_name": "string | null",
      "evidence_summary": "string",
      "edited_evidence_summary": "string | null",
      "transcript_excerpt": "string",
      "confidence": "likely_evidence | needs_review | not_enough_evidence",
      "status": "pending | accepted | rejected | needs_followup",
      "notes": "string"
    }
  ],
  "custom_mappings": [
    {
      "id": "string",
      "document_id": "string (ObjectId ref → standards_documents)",
      "document_name": "string",
      "criterion_ref": "string",
      "criterion_name": "string",
      "evidence_summary": "string",
      "edited_evidence_summary": "string | null",
      "transcript_excerpt": "string",
      "confidence": "likely_evidence | needs_review | not_enough_evidence",
      "status": "pending | accepted | rejected | needs_followup",
      "notes": "string"
    }
  ],
  "last_edited_at": "ISO datetime string",
  "last_edited_by": "string (user_id) | null",
  "rescanned_at": "ISO datetime string | null",
  "rescanned_by_name": "string | null",
  "created_at": "ISO datetime string"
}
```

---

## `audio_files`

```json
{
  "_id": "ObjectId",
  "meeting_id": "string",
  "storage_path": "string (object storage path)",
  "original_filename": "string",
  "content_type": "string (e.g. audio/webm)",
  "size_bytes": "number",
  "upload_status": "uploaded",
  "processing_status": "pending | processed",
  "deletion_status": "active | deleted",
  "is_deleted": "bool",
  "deleted_at": "ISO datetime string | null",
  "created_at": "ISO datetime string"
}
```

---

## `reviewer_comments`

```json
{
  "_id": "ObjectId",
  "meeting_id": "string",
  "user_id": "string",
  "user_name": "string",
  "text": "string",
  "created_at": "ISO datetime string"
}
```

---

## `review_edits`

```json
{
  "_id": "ObjectId",
  "meeting_id": "string",
  "editor_id": "string (user_id)",
  "editor_name": "string",
  "edit_type": "summary | actions | evidence | transcript_anonymise | evidence_rescan",
  "content": "string (edit details, optional)",
  "created_at": "ISO datetime string"
}
```

---

## `audit_logs`

```json
{
  "_id": "ObjectId",
  "meeting_id": "string",
  "user_id": "string",
  "user_name": "string",
  "action": "speaker_correction | transcript_text_edited | speaker_reset | speaker_restore_backup | pii_review_completed | pii_review_skipped",
  "edit_type": "string (same as action)",
  "detail": "string | null",
  "timestamp": "ISO datetime string"
}
```

---

## `standards_entries`

User-managed (editable) standards: system-seeded + org-custom. Includes all CQC regulations and Care Certificate standards.

```json
{
  "_id": "ObjectId",
  "type": "cqc | care_cert",
  "reference": "string (e.g. Regulation 9, Standard 2)",
  "name": "string",
  "description": "string",
  "keywords": ["string"],
  "source": "string | null",
  "is_active": "bool",
  "is_system": "bool (true = seeded globally, false = org-custom)",
  "org_id": "string | null (null for system entries)",
  "key_questions": ["Safe | Effective | Caring | Responsive | Well-led"],
  "sub_outcomes": [
    {
      "ref": "string (e.g. 2.1a)",
      "name": "string"
    }
  ],
  "created_at": "ISO datetime string",
  "created_by": "string (user_id, optional)"
}
```

---

## `standards` (read-only, system-seeded)

Separate collection for newer CQC system regulations (quality statements, etc.). Read-only — not user-editable.

```json
{
  "_id": "ObjectId",
  "type": "cqc | care_cert",
  "reference": "string",
  "name": "string",
  "description": "string",
  "keywords": ["string"],
  "key_questions": ["string"],
  "is_active": "bool"
}
```

---

## `standards_documents`

Uploaded org documents (Skills for Care guide, job descriptions, etc.) parsed into AI criteria.

```json
{
  "_id": "ObjectId",
  "filename": "string",
  "label": "string (display name)",
  "storage_path": "string",
  "content_type": "string",
  "size_bytes": "number",
  "parse_status": "parsing | parsed | failed",
  "parse_error": "string | null",
  "is_active": "bool",
  "org_id": "string",
  "uploaded_by": "string (user_id)",
  "uploaded_by_name": "string",
  "extracted_text": "string (first 5000 chars preview)",
  "document_summary": "string (AI-generated)",
  "extracted_criteria": [
    {
      "ref": "string",
      "name": "string",
      "description": "string"
    }
  ],
  "criteria_count": "number",
  "parsed_at": "ISO datetime string | null",
  "created_at": "ISO datetime string"
}
```

---

## `settings`

Key-value store. Primary use: per-org supervision templates.

```json
{
  "_id": "string (e.g. supervision_template:{org_id})",
  "org_id": "string",
  "steps": [
    {
      "id": "string",
      "title": "string",
      "description": "string",
      "order": "number"
    }
  ],
  "name": "string",
  "description": "string",
  "updated_at": "ISO datetime string",
  "updated_by_name": "string"
}
```

---

## `org_settings`

Structural org units (care homes, departments, etc.).

```json
{
  "_id": "ObjectId",
  "name": "string",
  "description": "string",
  "manager_user_id": "string | null",
  "org_id": "string",
  "created_at": "ISO datetime string",
  "updated_at": "ISO datetime string"
}
```

---

## `teams`

Teams within an org setting (e.g. Night Team, Day Team).

```json
{
  "_id": "ObjectId",
  "name": "string",
  "description": "string",
  "setting_id": "string (ObjectId ref → org_settings)",
  "supervisor_user_id": "string | null",
  "org_id": "string",
  "created_at": "ISO datetime string",
  "updated_at": "ISO datetime string"
}
```

---

## `schedules`

Recurring supervision schedule templates per staff member.

```json
{
  "_id": "ObjectId",
  "org_id": "string",
  "staff_user_id": "string (user_id)",
  "meeting_type_id": "string (ObjectId ref → meeting_types)",
  "frequency": "string (monthly | quarterly | weeks_6 | etc.)",
  "start_date": "string (ISO date)",
  "is_active": "bool",
  "created_by": "string (user_id)",
  "created_at": "ISO datetime string"
}
```

---

## `meeting_types`

Configurable meeting type definitions per org.

```json
{
  "_id": "ObjectId",
  "org_id": "string",
  "name": "string (e.g. Monthly Supervision, Quarterly Appraisal)",
  "default_frequency": "string",
  "color": "string (hex color)",
  "is_active": "bool",
  "created_at": "ISO datetime string"
}
```

---

## `supervision_uploads`

Imported previous supervision documents (PDF/DOCX) for historical evidence.

```json
{
  "_id": "ObjectId",
  "org_id": "string",
  "uploader_id": "string (user_id)",
  "uploader_name": "string",
  "staff_id": "string (user_id — who the doc is about)",
  "staff_name": "string",
  "filename": "string",
  "label": "string",
  "doc_type": "job_description | supervision_record | other",
  "meeting_date": "string (ISO date)",
  "file_ext": "string",
  "size_bytes": "number",
  "status": "processing | complete | failed",
  "cqc_mappings": [ "same structure as analyses.cqc_mappings" ],
  "care_cert_mappings": [ "same structure as analyses.care_cert_mappings" ],
  "custom_mappings": [ "same structure as analyses.custom_mappings" ],
  "created_at": "ISO datetime string"
}
```

---

## `meeting_prep`

Dynamic Supervision prep agendas and post-meeting coverage results.

```json
{
  "_id": "ObjectId",
  "meeting_id": "string",
  "org_id": "string",
  "supervisee_id": "string (user_id)",
  "focus_topic": "string | null",
  "context_sources": {
    "previous_meetings": "bool",
    "supervision_uploads": "bool",
    "org_standards": "bool"
  },
  "sections": [
    {
      "id": "string",
      "title": "string",
      "questions": [
        {
          "id": "string",
          "text": "string",
          "included": "bool",
          "is_custom": "bool"
        }
      ]
    }
  ],
  "generation_status": "pending | generating | complete | failed",
  "shared_with_supervisee": "bool",
  "coverage_results": {
    "{question_id}": {
      "status": "covered | partial | missed",
      "evidence": "string | null"
    }
  },
  "coverage_checked_at": "ISO datetime string | null",
  "created_at": "ISO datetime string",
  "updated_at": "ISO datetime string"
}
```

---

## `focus_topics`

Org-scoped focus topics for Dynamic Supervision question generation.

```json
{
  "_id": "ObjectId",
  "org_id": "string",
  "topic": "string",
  "is_current": "bool (only one can be current per org)",
  "created_by": "string (user_id)",
  "created_by_name": "string",
  "created_at": "ISO datetime string"
}
```

---

## `invitations`

Single-use invite tokens for new org admin onboarding (72-hour expiry).

```json
{
  "_id": "ObjectId",
  "token": "string (URL-safe random, unique)",
  "user_id": "string (user_id — the invited user)",
  "org_id": "string",
  "email": "string",
  "expires_at": "ISO datetime string",
  "created_at": "ISO datetime string",
  "used_at": "ISO datetime string (set on acceptance, absent = unused)"
}
```

---

## `login_attempts`

Brute force protection tracking.

```json
{
  "_id": "ObjectId",
  "identifier": "string (IP:email)",
  "count": "number",
  "locked_until": "ISO datetime string"
}
```

---

## `password_reset_tokens`

Single-use 1-hour password reset tokens.

```json
{
  "_id": "ObjectId",
  "token": "string",
  "email": "string",
  "expires_at": "datetime",
  "used": "bool"
}
```

---

## Relationship Diagram (Summary)

```
organisations (1) ──────────────────────────────────────────── (many) users
organisations (1) ──────────────────────────────────────────── (many) meetings
organisations (1) ──────────────────────────────────────────── (many) org_settings
org_settings   (1) ──────────────────────────────────────────── (many) teams
teams          (1) ──────────────────────────────────────────── (many) users (via team_id)

meetings (1) ── transcript_id ──► transcripts (1)
meetings (1) ── analysis_id  ──► analyses    (1)
meetings (1) ── audio_file_id──► audio_files (1)
meetings (1) ──────────────────────────────── (many) reviewer_comments
meetings (1) ──────────────────────────────── (many) review_edits
meetings (1) ──────────────────────────────── (many) audit_logs
meetings (1) ──────────────────────────────── (1)    meeting_prep

users (1) ──────────────────────────────────── (many) schedules
users (1) ──────────────────────────────────── (many) supervision_uploads (as staff)

organisations (1) ──────────────────────────── (many) standards_documents
organisations (1) ──────────────────────────── (many) focus_topics
organisations (1) ──────────────────────────── (1)    settings (supervision template)
organisations (1) ──────────────────────────── (many) meeting_types
```

---

## Notes for Developers

1. **Multi-tenancy**: Every collection scoped to `org_id` — **all queries must include `org_id` filter** or data leaks between orgs.
2. **`standards_entries` vs `standards`**: Two separate collections. `standards_entries` is user-managed (editable). `standards` is system-seeded read-only. Both are merged in the AI analysis pipeline.
3. **`pii_redactions` access control**: The raw `pii_redactions` array (containing original PII text) is **stripped from API responses for non-privileged users**. Only meeting creator + listed attendees can see originals.
4. **Audio lifecycle**: `audio_files.is_deleted` + `meetings.audio_deletion_status` track GDPR deletion. Audio is stored in object storage; only the metadata record lives in MongoDB.
5. **`meeting_prep`**: Upserted (not inserted) — one record per `meeting_id`. `coverage_results` is written by the background processing pipeline after transcription.
6. **ObjectId string representation**: All `_id` values are returned as strings in API responses. When querying, wrap in `ObjectId()` before use.
