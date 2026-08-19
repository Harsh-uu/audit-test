"""Shared helpers for iteration-75 JSONB write-soundness tests."""
import asyncio
import json
import os
import subprocess
import sys

import requests
from dotenv import dotenv_values

FE = dotenv_values("/app/frontend/.env")
BE = dotenv_values("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or FE["REACT_APP_BACKEND_URL"]).rstrip("/") + "/api"
DSN = BE["DATABASE_URL"]
ORG = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"

_CACHE = {}


def db(fn):
    async def runner():
        import asyncpg
        # NOTE: deliberately NO jsonb codec — jsonb values come back as raw text and
        # text binds to $n::jsonb are stored verbatim, so snapshot/restore round-trips
        # cannot themselves double-encode.
        conn = await asyncpg.connect(DSN, ssl="require")
        try:
            return await fn(conn)
        finally:
            await conn.close()
    return asyncio.run(runner())


def login(email, password):
    if email in _CACHE:
        return _CACHE[email]
    db(lambda c: c.execute("DELETE FROM login_attempts"))
    out = subprocess.run([sys.executable, "/app/backend/tests/get_tokens.py", email, password],
                         capture_output=True, text=True, timeout=240)
    try:
        payload = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        raise AssertionError(f"get_tokens.py failed: {out.stdout[-500:]} {out.stderr[-500:]}")
    if "cookies" not in payload:
        raise AssertionError(f"Login failed for {email}: {payload}")
    s = requests.Session()
    for k, v in payload["cookies"].items():
        s.cookies.set(k, v)
    _CACHE[email] = s
    return s


def all_elements_are_dicts(val):
    """True when a JSONB array's elements are real objects (not stringified JSON)."""
    v = json.loads(val) if isinstance(val, str) else val
    if not isinstance(v, list):
        return False, f"not a list: {type(v).__name__}"
    bad = [e for e in v if not isinstance(e, dict)]
    if bad:
        return False, f"{len(bad)}/{len(v)} elements are not objects: {bad[:2]}"
    return True, ""
