"""Safety-net timeout: reclaim a fully-idle (not mid-transaction) abandoned
connection. idle_in_transaction_session_timeout (m010) only closes a session
stuck INSIDE a transaction; a connection that finished its transaction and
was simply never closed (e.g. a crashed process, or the fixed min_size=2/1
connections in database.py's two pools after an ungraceful restart) stays
open forever with idle_session_timeout=0. Matches Supabase's own documented
best-practice value (10min) and reuses the ALTER DATABASE approach already
proven to work for idle_in_transaction_session_timeout under this same role
(ALTER SYSTEM needs true superuser, which this role does not have — see
m001's role docstring). Applies uniformly to every role/pool (app_default,
postgres, and any Supabase-managed connection to this database).
"""

VERSION = "012_idle_session_timeout"


async def up(conn):
    db_name = await conn.fetchval("SELECT current_database()")
    await conn.execute(f'ALTER DATABASE "{db_name}" SET idle_session_timeout = \'10min\'')
