"""Iteration 78 — Backend auth rate-limiting rewrite (failed attempts only, threshold 5).

Covers:
  - repeated SUCCESSFUL logins must never be rate-limited
  - 5 consecutive FAILED logins lock the account (429 on next attempt)
  - a successful login after a few failures clears the counter (no block)
  - MFA response shape for a role with mandatory MFA (masked-email source data)
"""
import asyncio
import os

import asyncpg
import pytest
import requests
from dotenv import dotenv_values

fe = dotenv_values("/app/frontend/.env")
be = dotenv_values("/app/backend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or fe["REACT_APP_BACKEND_URL"]).rstrip("/")
API = f"{BASE_URL}/api"

STAFF = {"email": "user@supervision.com", "password": "Staff123!"}
MANAGER_EMAIL = "manager@supervision.com"


def _clear_attempts():
    async def run():
        conn = await asyncpg.connect(be["DATABASE_URL"], ssl="require")
        await conn.execute("DELETE FROM login_attempts")
        await conn.close()
    asyncio.get_event_loop().run_until_complete(run()) if False else asyncio.run(run())


@pytest.fixture(autouse=True)
def clean_limits():
    _clear_attempts()
    yield
    _clear_attempts()


def _login(email, password):
    return requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)


# ── (a) successful logins must not count toward the lockout ──────────────────
def test_repeated_successful_logins_not_rate_limited():
    for i in range(7):
        r = _login(STAFF["email"], STAFF["password"])
        assert r.status_code == 200, f"attempt {i+1} failed: {r.status_code} {r.text[:200]}"
        data = r.json()
        assert data["email"] == STAFF["email"]
        assert data["role"] == "attendee"
        assert "supervision_access" in r.cookies


# ── (b) 5 failed attempts lock the account ──────────────────────────────────
def test_five_failed_attempts_locks_account():
    codes = []
    for i in range(5):
        r = _login(STAFF["email"], "WrongPassword123!")
        codes.append(r.status_code)
        assert r.status_code in (401, 429), f"attempt {i+1}: {r.status_code} {r.text[:200]}"
    # 5th failure message should mention the lock
    assert codes[:4] == [401, 401, 401, 401], codes
    # next attempt (even with the CORRECT password) must be blocked with 429
    blocked = _login(STAFF["email"], STAFF["password"])
    assert blocked.status_code == 429, f"expected 429 lockout, got {blocked.status_code} {blocked.text[:200]}"
    assert "lock" in blocked.json()["detail"].lower() or "too many" in blocked.json()["detail"].lower()


# ── (c) success after a few failures resets the counter ─────────────────────
def test_success_after_failures_resets_counter():
    for i in range(3):
        r = _login(STAFF["email"], "WrongPassword123!")
        assert r.status_code == 401, f"failure {i+1}: {r.status_code}"
    ok = _login(STAFF["email"], STAFF["password"])
    assert ok.status_code == 200, f"login after 3 failures blocked: {ok.status_code} {ok.text[:200]}"
    # counter cleared → 3 more failures must still not lock
    for i in range(3):
        r = _login(STAFF["email"], "WrongPassword123!")
        assert r.status_code == 401, f"post-reset failure {i+1}: {r.status_code} {r.text[:200]}"
    ok2 = _login(STAFF["email"], STAFF["password"])
    assert ok2.status_code == 200, f"blocked though counter should have reset: {ok2.status_code} {ok2.text[:200]}"


# ── (d) MFA response shape for mandatory-MFA role ──────────────────────────
def test_mfa_role_returns_session_and_email():
    r = _login(MANAGER_EMAIL, "Manager123!")
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    data = r.json()
    assert data.get("requires_mfa") is True
    assert isinstance(data.get("mfa_session"), str) and len(data["mfa_session"]) > 20
    assert data.get("email") == MANAGER_EMAIL
    assert "supervision_access" not in r.cookies


def test_wrong_password_does_not_leak_user_existence():
    r1 = _login("nosuchuser_iter78@example.com", "WhateverPass1!")
    assert r1.status_code == 401
    assert r1.json()["detail"] == "Invalid credentials"
