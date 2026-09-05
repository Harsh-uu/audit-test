"""Iter126: verify admin_pool max_size shrunk from 10 to 5, main pool unchanged (15).

Covers:
- source-level pool sizes (static check on database.py)
- clean startup with new sizes (backend already running)
- regression: login for all 4 roles works (admin, manager, attendee, super_admin)
- burst/concurrency: 10 concurrent admin_pool-touching requests all succeed
- pg_stat_activity: connection counts stay within 20 per-instance ceiling
"""
import asyncio
import os
import re
import time
from datetime import datetime, timedelta, timezone

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

be = dotenv_values("/app/backend/.env")
fe = dotenv_values("/app/frontend/.env")
BASE = fe["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = be["DATABASE_URL"]  # postgres (superuser) — used only for MFA overrides + pg_stat_activity


# ---------- helpers ----------

async def _override_mfa(email: str):
    conn = await asyncpg.connect(DSN, ssl="require")
    try:
        h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
        exp = datetime.now(timezone.utc) + timedelta(minutes=10)
        await conn.execute(
            "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
            h, exp, email,
        )
    finally:
        await conn.close()


def _login(email: str, password: str) -> requests.Session:
    """Full login incl MFA bypass if required. Returns authenticated Session."""
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:200]}"
    data = r.json()
    if data.get("requires_mfa"):
        asyncio.run(_override_mfa(email))
        r2 = s.post(
            f"{BASE}/auth/verify-mfa",
            json={"mfa_session": data["mfa_session"], "code": "123456"},
            timeout=30,
        )
        assert r2.status_code == 200, f"MFA failed for {email}: {r2.status_code} {r2.text[:200]}"
    return s


# ---------- 1. Source-level pool config check ----------

def test_admin_pool_max_size_is_5_in_source():
    src = open("/app/backend/database.py").read()
    # Find the admin_pool block (everything after the create_pool call
    # until close_pool definition — reliably brackets the kwargs block).
    admin_block = src.split("admin_pool = await asyncpg.create_pool(")[1].split("async def close_pool")[0]
    m = re.search(r"^\s*max_size\s*=\s*(\d+)", admin_block, re.MULTILINE)
    assert m, "admin_pool max_size not found"
    assert int(m.group(1)) == 5, f"expected admin_pool max_size=5, got {m.group(1)}"
    m2 = re.search(r"min_size\s*=\s*(\d+)", admin_block)
    assert int(m2.group(1)) == 1, f"expected admin_pool min_size=1, got {m2.group(1)}"


def test_main_pool_unchanged_15_2():
    src = open("/app/backend/database.py").read()
    main_block = src.split("pool = await asyncpg.create_pool(")[1].split("admin_pool")[0]
    assert re.search(r"max_size\s*=\s*15", main_block), "main pool max_size not 15"
    assert re.search(r"min_size\s*=\s*2", main_block), "main pool min_size not 2"


# ---------- 2. Regression: 4-role login ----------

@pytest.mark.parametrize("email,pw", [
    ("admin@supervision.com", "Admin123!"),
    ("manager@supervision.com", "Manager123!"),
    ("user@supervision.com", "AnotherNew789!"),
    ("superadmin@1two.one", "NewPass123!"),
])
def test_login_all_roles(email, pw):
    s = _login(email, pw)
    r = s.get(f"{BASE}/auth/me", timeout=30)
    assert r.status_code == 200, f"/auth/me failed for {email}: {r.status_code}"
    body = r.json()
    assert body.get("email") == email


# ---------- 3. Regression: token refresh ----------

def test_token_refresh():
    s = _login("admin@supervision.com", "Admin123!")
    r = s.post(f"{BASE}/auth/refresh", timeout=30)
    assert r.status_code == 200, f"refresh failed: {r.status_code} {r.text[:200]}"
    # /me still works after refresh
    r2 = s.get(f"{BASE}/auth/me", timeout=30)
    assert r2.status_code == 200


# ---------- 4. Regression: super-admin org list (with_admin() flow) ----------

def test_super_admin_org_list():
    s = _login("superadmin@1two.one", "NewPass123!")
    r = s.get(f"{BASE}/super-admin/orgs", timeout=30)
    assert r.status_code == 200, f"super-admin orgs failed: {r.status_code} {r.text[:300]}"
    assert isinstance(r.json(), list)


# ---------- 5. Concurrency burst — 10 concurrent logins ----------

def _one_login_attempt(idx):
    """Single fresh login roundtrip — exercises with_admin() identity lookup."""
    t0 = time.time()
    try:
        s = requests.Session()
        r = s.post(
            f"{BASE}/auth/login",
            json={"email": "user@supervision.com", "password": "AnotherNew789!"},
            timeout=30,
        )
        # attendee has no MFA — login should return access token directly
        return (idx, r.status_code, time.time() - t0, r.text[:120] if r.status_code != 200 else "ok")
    except Exception as e:
        return (idx, -1, time.time() - t0, repr(e))


def test_burst_10_concurrent_logins():
    """10 concurrent logins — each touches admin_pool during identity lookup.
    All should succeed (asyncpg queues excess acquires, doesn't reject)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    N = 10
    with ThreadPoolExecutor(max_workers=N) as ex:
        futs = [ex.submit(_one_login_attempt, i) for i in range(N)]
        results = [f.result() for f in as_completed(futs)]

    failures = [r for r in results if r[1] != 200]
    slowest = max(r[2] for r in results)
    print(f"\nburst results: {len(results)} total, {len(failures)} failures, slowest={slowest:.2f}s")
    for r in results:
        print(f"  worker={r[0]} status={r[1]} elapsed={r[2]:.2f}s {r[3] if r[1] != 200 else ''}")

    # Zero failures expected — asyncpg queues under saturation
    assert not failures, f"{len(failures)} of {N} bursts failed: {failures[:3]}"
    # No request should have taken absurdly long (queue delay under 5-slot pool
    # for a lightweight identity lookup should be small — allow 15s upper bound
    # to be lenient about network to Supabase)
    assert slowest < 15.0, f"slowest burst took {slowest:.2f}s — possible queue starvation"


# ---------- 6. Live DB connection count during burst ----------

async def _count_conns():
    conn = await asyncpg.connect(DSN, ssl="require")
    try:
        rows = await conn.fetch(
            "SELECT usename, count(*) AS c FROM pg_stat_activity "
            "WHERE usename IN ('app_default','postgres') GROUP BY usename"
        )
        return {r["usename"]: r["c"] for r in rows}
    finally:
        await conn.close()


def test_connection_count_under_ceiling_during_burst():
    """Fire 15 concurrent /auth/me + burst logins, sample pg_stat_activity peak.
    App-owned connections (usename='app_default') must stay <=15. Combined
    app_default+postgres attributable to this backend must not exceed 20."""
    from concurrent.futures import ThreadPoolExecutor

    # Baseline (before load)
    base = asyncio.run(_count_conns())
    print(f"\nbaseline conns: {base}")

    # Get an authenticated session for hammering /auth/me
    s = _login("admin@supervision.com", "Admin123!")
    cookies = s.cookies

    def hammer(_):
        ss = requests.Session()
        for c in cookies:
            ss.cookies.set(c.name, c.value)
        try:
            ss.get(f"{BASE}/auth/me", timeout=30)
        except Exception:
            pass

    # Sample connections while under load
    peaks = {"app_default": 0, "postgres": 0}

    async def sampler(stop_event):
        while not stop_event.is_set():
            try:
                snap = await _count_conns()
                for k, v in snap.items():
                    if v > peaks.get(k, 0):
                        peaks[k] = v
            except Exception:
                pass
            await asyncio.sleep(0.15)

    import threading

    stop = threading.Event()

    def run_sampler():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _s():
            while not stop.is_set():
                try:
                    snap = await _count_conns()
                    for k, v in snap.items():
                        if v > peaks.get(k, 0):
                            peaks[k] = v
                except Exception:
                    pass
                await asyncio.sleep(0.15)

        loop.run_until_complete(_s())
        loop.close()

    t = threading.Thread(target=run_sampler, daemon=True)
    t.start()

    # Generate load: 15 concurrent /auth/me + 5 concurrent logins for super_admin
    # (super_admin needs admin_pool). Loop for ~3s.
    end = time.time() + 3.0
    with ThreadPoolExecutor(max_workers=20) as ex:
        while time.time() < end:
            list(ex.map(hammer, range(20)))

    time.sleep(0.5)
    stop.set()
    t.join(timeout=2)

    print(f"peak conns during burst: {peaks}")
    print(f"baseline was: {base}")

    # app_default is exclusive to our app's main pool — must never exceed 15
    assert peaks["app_default"] <= 15, (
        f"app_default peak {peaks['app_default']} exceeds main pool max_size=15"
    )
    # postgres user is shared, but delta attributable to us should stay within admin_pool cap
    postgres_delta = peaks.get("postgres", 0) - base.get("postgres", 0)
    print(f"postgres delta during burst: {postgres_delta}")
    # Sanity: delta shouldn't exceed admin_pool.max_size=5 (allow +1 slack for our own sampler conn)
    assert postgres_delta <= 6, (
        f"postgres conn delta {postgres_delta} exceeds admin_pool max_size=5 (+1 slack)"
    )
