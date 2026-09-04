"""Safety-net timeout: reclaim a stalled request's connection + locks.

idle_in_transaction_session_timeout was 0 (disabled) database-wide — a
request that stalls mid-transaction (lock wait, huge dataset, accidental
blocking call) held its connection and any locks forever, with nothing to
reclaim them. Set at the DATABASE level (not per-role) so it applies
uniformly to both with_org() (app_rls_user) and with_admin() (postgres)
sessions alike. 30s is generous — the two endpoints that legitimately did
the most in-transaction work (admin.py export_evidence/export_transcripts)
had their Python-side processing moved outside the transaction in the same
change that introduced this timeout, so no real request should ever
approach it.
"""

VERSION = "010_idle_timeout"


async def up(conn):
    db_name = await conn.fetchval("SELECT current_database()")
    await conn.execute(f'ALTER DATABASE "{db_name}" SET idle_in_transaction_session_timeout = \'30s\'')
