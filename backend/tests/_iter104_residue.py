"""Post-run residue check for iteration 104 test data + orphan re-audit."""
import asyncio
import asyncpg
from dotenv import dotenv_values

DSN = dotenv_values("/app/backend/.env")["DATABASE_URL"]

TABLES = ["users", "meetings", "transcripts", "analyses", "audio_files", "review_edits",
          "reviewer_comments", "audit_logs", "org_settings", "teams", "standards_entries",
          "standards_documents", "invitations", "settings", "meeting_types", "focus_topics",
          "meeting_prep", "schedules", "supervision_uploads", "organisations", "jobs"]

FK_Q = """
SELECT src.relname AS child, tgt.relname AS parent,
       (SELECT string_agg(a.attname, ',') FROM unnest(con.conkey) k
          JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k) AS col
FROM pg_constraint con
JOIN pg_class src ON src.oid = con.conrelid
JOIN pg_class tgt ON tgt.oid = con.confrelid
JOIN pg_namespace n ON n.oid = src.relnamespace
WHERE con.contype='f' AND n.nspname='public'
"""


async def main():
    c = await asyncpg.connect(DSN)
    print("── residue (id LIKE 'TEST_iter104%') ──")
    total = 0
    for t in TABLES:
        n = await c.fetchval(f"SELECT count(*) FROM {t} WHERE id LIKE 'TEST_iter104%'")
        if n:
            print(f"  {t}: {n}")
            total += n
    n = await c.fetchval("SELECT count(*) FROM users WHERE email LIKE 'TEST_iter104%'")
    if n:
        print(f"  users(email): {n}")
        total += n
    n = await c.fetchval("SELECT count(*) FROM organisations WHERE name LIKE 'TEST_iter104%'")
    if n:
        print(f"  organisations(name): {n}")
        total += n
    print(f"  TOTAL residue rows: {total}")

    print("── orphan re-audit across all public FKs ──")
    bad = 0
    for r in await c.fetch(FK_Q):
        n = await c.fetchval(
            f"SELECT count(*) FROM {r['child']} t WHERE t.{r['col']} IS NOT NULL "
            f"AND NOT EXISTS (SELECT 1 FROM {r['parent']} p WHERE p.id = t.{r['col']})")
        if n:
            print(f"  ORPHANS {r['child']}.{r['col']}->{r['parent']}: {n}")
            bad += n
    print(f"  TOTAL orphans on constrained columns: {bad}")

    print("── known-unconstrained orphan tracking ──")
    for label, q in [
        ("jobs.meeting_id", "SELECT count(*) FROM jobs j WHERE j.meeting_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM meetings m WHERE m.id=j.meeting_id)"),
        ("invitations.user_id", "SELECT count(*) FROM invitations i WHERE i.user_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM users u WHERE u.id=i.user_id)"),
        ("meetings.created_by", "SELECT count(*) FROM meetings m WHERE m.created_by IS NOT NULL AND NOT EXISTS (SELECT 1 FROM users u WHERE u.id=m.created_by)"),
        ("meetings.sign_off_manager_id", "SELECT count(*) FROM meetings m WHERE m.sign_off_manager_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM users u WHERE u.id=m.sign_off_manager_id)"),
    ]:
        print(f"  {label}: {await c.fetchval(q)}")

    print("── login_attempts rows:", await c.fetchval("SELECT count(*) FROM login_attempts"))
    await c.close()


asyncio.run(main())
