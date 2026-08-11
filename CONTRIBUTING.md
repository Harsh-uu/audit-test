# Supervision 2.0 — Contributor Rules

## The asyncpg + RLS JSONB Trap (READ THIS FIRST)

### What happens
When a query runs inside `database.with_org()`, PostgreSQL switches to the `app_rls_user`
role via `SET LOCAL ROLE`. Under Supabase's connection pooler, this role switch causes
asyncpg's prepared-statement cache to reset — and the driver then returns **JSONB columns
as raw JSON strings** instead of decoded Python dicts/lists.

This means `row["my_jsonb_column"]` can be `'[{"id": "abc"}]'` (a string) instead of
`[{"id": "abc"}]` (a list). Calling `.get()` on a string raises `AttributeError`; iterating
over it iterates characters, not items.

`database.with_admin()` (`SET LOCAL row_security = off`) can also exhibit this — do not
assume `with_admin()` is safe.

### The rule

**Every JSONB column read from asyncpg MUST be guarded before use.**

Use one of the existing helpers:

```python
# For list columns (attendees, actions, risks, mappings, sub_outcomes, …)
_ensure_list(row["my_list_col"])   # defined in review.py, meetings.py
_jlist(row["my_list_col"])         # defined in processing.py, admin.py

# For dict columns (sign_off_record, branding, settings.data, …)
_ensure_dict(row["my_dict_col"])   # defined in review.py, meetings.py
_jdict(row["my_dict_col"])         # defined in org.py
```

Or write inline:

```python
import json
val = row["my_jsonb_col"]
parsed = json.loads(val) if isinstance(val, str) else (val or [])
```

### Where guards already exist

| Helper | Lives in |
|--------|----------|
| `_parse_meeting_row()` | `meetings.py`, `review.py` — guards all meeting JSONB fields |
| `_parse_analysis_row()` | `meetings.py`, `review.py` — guards all analysis JSONB fields |
| `_parse_std_row()` | `processing.py`, `review.py`, `doc_uploads.py` — guards `standards_entries` JSONB |
| `_upload_dict()` | `doc_uploads.py` — guards supervision_upload mapping fields |
| `_jdict()` | `org.py` — guards `organisations.branding` |

### When you add a new JSONB column

1. Add `ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} JSONB ...` to `init_db.py`.
2. Add the column name to the relevant `_parse_*_row()` helper **in the same commit**.
3. Never read it with bare `row["col"]` — always go through the helper.

### Nested JSONB (double-encoded arrays)

`recording_events` and similar columns that store arrays of objects can come back as
`['{"event": "start"}', '{"event": "pause"}']` — a list of JSON strings rather than a
list of dicts. Use `_normalize_rec_events()` (defined in `review.py`) for these, or write
a custom flattener that handles `isinstance(item, str)`.

---

## Migration Protocol

Every new column added to a `CREATE TABLE` block **must** have a matching:

```sql
ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {type} {default};
```

at the bottom of `init_db.py`. `CREATE TABLE IF NOT EXISTS` does not add columns to
existing tables — the column will silently be missing in production and cause 500 errors.
