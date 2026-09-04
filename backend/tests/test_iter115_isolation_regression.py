"""Iter115: focused isolation assertions for the least-privilege pool change (m011).

Strengthens iter114's weak jane assertion: asserts EXACT ownership of every row
returned to a same-org non-attendee user, on both /api/meetings/ and the
combined /api/dashboard/ endpoint (the one the UI actually renders).
"""
import os

import pytest
import requests
from dotenv import dotenv_values

FE = dotenv_values("/app/frontend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or FE["REACT_APP_BACKEND_URL"]).rstrip("/")
API = f"{BASE}/api"
TIMEOUT = 90

ADMIN = ("admin@supervision.com", "Admin123!")
ATTENDEE = ("user@supervision.com", "AnotherNew789!")
JANE = ("jane@supervision.com", "JaneNew456!")


def _login(email, pw):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=TIMEOUT)
    assert r.status_code == 200, f"login {email} -> {r.status_code} {r.text[:200]}"
    assert not r.json().get("requires_mfa"), f"unexpected MFA for {email}"
    return s


def _list(payload):
    return payload if isinstance(payload, list) else payload.get("meetings", [])


def _owned(meeting, uid):
    att = [a.get("user_id") for a in (meeting.get("attendees") or []) if isinstance(a, dict)]
    shared = [a.get("user_id") for a in (meeting.get("shared_with") or []) if isinstance(a, dict)]
    return meeting.get("created_by") == uid or uid in att or uid in shared


@pytest.fixture(scope="module")
def jane():
    return _login(*JANE)


@pytest.fixture(scope="module")
def attendee():
    return _login(*ATTENDEE)


@pytest.fixture(scope="module")
def admin():
    return _login(*ADMIN)


class TestIsolationAfterPoolChange:
    """Same-org, non-attendee user must only ever see her own rows."""

    def test_jane_meetings_endpoint_only_own_rows(self, jane):
        uid = jane.get(f"{API}/auth/me", timeout=TIMEOUT).json()["id"]
        r = jane.get(f"{API}/meetings/?limit=500", timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        ms = _list(r.json())
        assert len(ms) >= 1, "fixture problem: jane should own at least one meeting"
        for m in ms:
            assert _owned(m, uid), f"leaked meeting {m.get('id')} ({m.get('title')})"

    def test_jane_dashboard_endpoint_matches_meetings_endpoint(self, jane):
        d = jane.get(f"{API}/dashboard/", timeout=TIMEOUT)
        assert d.status_code == 200, d.text[:300]
        dash_ids = {m["id"] for m in _list(d.json())}
        lst_ids = {m["id"] for m in _list(jane.get(f"{API}/meetings/?limit=500", timeout=TIMEOUT).json())}
        assert dash_ids == lst_ids, f"dashboard {dash_ids} != meetings {lst_ids}"

    def test_no_overlap_between_two_same_org_attendees(self, jane, attendee):
        j = {m["id"] for m in _list(jane.get(f"{API}/meetings/?limit=500", timeout=TIMEOUT).json())}
        u = {m["id"] for m in _list(attendee.get(f"{API}/meetings/?limit=500", timeout=TIMEOUT).json())}
        assert j and u
        assert not (j & u), f"unexpected shared meetings between the two fixtures: {j & u}"

    def test_admin_superset_of_both_attendees(self, admin, jane, attendee):
        a = {m["id"] for m in _list(admin.get(f"{API}/meetings/?limit=500", timeout=TIMEOUT).json())}
        j = {m["id"] for m in _list(jane.get(f"{API}/meetings/?limit=500", timeout=TIMEOUT).json())}
        u = {m["id"] for m in _list(attendee.get(f"{API}/meetings/?limit=500", timeout=TIMEOUT).json())}
        assert j <= a and u <= a, "admin org-wide list is missing rows visible to attendees"
        assert len(a) > len(j), "admin should see more than a single-meeting attendee"

    def test_attendee_own_portfolio_ok_and_others_blocked(self, attendee, jane):
        uid = attendee.get(f"{API}/auth/me", timeout=TIMEOUT).json()["id"]
        ok = attendee.get(f"{API}/portfolio/{uid}", timeout=TIMEOUT)
        assert ok.status_code == 200, ok.text[:300]
        assert "_id" not in ok.json()
        blocked = jane.get(f"{API}/portfolio/{uid}", timeout=TIMEOUT)
        assert blocked.status_code == 403, f"same-org portfolio leak: {blocked.status_code}"
