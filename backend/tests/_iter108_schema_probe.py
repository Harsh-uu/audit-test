"""Iteration 108 — Phase 2 TEXT->UUID migration schema verification probe.

Run: cd /app/backend && python3 tests/_iter108_schema_probe.py
"""
import asyncio
import json
import sys

import asyncpg
from dotenv import dotenv_values

BE = dotenv_values("/app/backend/.env")
DSN = BE["DATABASE_URL"]

EXPECTED_TEXT = {
    ("login_attempts", "identifier"),
    ("password_reset_tokens", "token"),
    ("invitations", "token"),
    ("evidence_feedback", "evidence_item_id"),
}


async def main():
    c = await asyncpg.connect(DSN)
    out = {}
    cols = await c.fetch(
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema='public'
          AND (column_name='id' OR column_name LIKE '%\\_id' OR column_name LIKE '%\\_by')
        ORDER BY table_name, column_name
        """
    )
    text_cols = [
        (r["table_name"], r["column_name"])
        for r in cols
        if r["data_type"] in ("text", "character varying")
    ]
    uuid_cols = [(r["table_name"], r["column_name"]) for r in cols if r["data_type"] == "uuid"]
    out["uuid_col_count"] = len(uuid_cols)
    out["still_text_id_like_cols"] = sorted(text_cols)
    out["unexpected_text_cols"] = sorted(set(text_cols) - EXPECTED_TEXT)
    out["missing_expected_text"] = sorted(EXPECTED_TEXT - set(text_cols))

    out["fk_count"] = await c.fetchval(
        "SELECT count(*) FROM pg_constraint WHERE contype='f' AND connamespace='public'::regnamespace"
    )
    out["fk_invalid"] = await c.fetchval(
        "SELECT count(*) FROM pg_constraint WHERE contype='f' AND NOT convalidated AND connamespace='public'::regnamespace"
    )
    out["rls_policy_count"] = await c.fetchval("SELECT count(*) FROM pg_policies WHERE schemaname='public'")
    out["rls_enabled_tables"] = await c.fetchval(
        "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relrowsecurity"
    )
    pols = await c.fetch("SELECT tablename, policyname, qual, with_check FROM pg_policies WHERE schemaname='public' ORDER BY tablename")
    bad = [
        dict(p)
        for p in pols
        if p["qual"] and "uuid" not in (p["qual"] or "").lower()
    ]
    out["policies_without_uuid_cast"] = bad
    out["sample_policy"] = dict(pols[0]) if pols else None

    # Row counts
    tables = [r["tablename"] for r in await c.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
    counts = {}
    for t in tables:
        counts[t] = await c.fetchval(f'SELECT count(*) FROM "{t}"')
    out["row_counts"] = counts

    # leftover TEST_ artifacts
    out["test_residue"] = {
        "meetings": await c.fetchval("SELECT count(*) FROM meetings WHERE title LIKE 'TEST_%'"),
        "users": await c.fetchval("SELECT count(*) FROM users WHERE email LIKE 'TEST_%' OR email LIKE '%test_iter%'"),
        "org_settings": await c.fetchval("SELECT count(*) FROM org_settings WHERE name LIKE 'TEST_%'"),
        "teams": await c.fetchval("SELECT count(*) FROM teams WHERE name LIKE 'TEST_%'"),
    }
    await c.close()
    print(json.dumps(out, indent=1, default=str))


asyncio.run(main())
