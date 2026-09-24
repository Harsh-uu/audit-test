"""Iter163 — evidence_feedback tracking extended to document uploads + AI Accuracy report.

Covers:
- Doc upload PUT single evidence -> evidence_feedback row (upload_id set, meeting_id NULL)
- Doc upload bulk-action -> N evidence_feedback rows matching changed_count
- Meeting evidence PUT/bulk-action still work + write meeting_id-based rows (no regression)
- Super Admin AI accuracy report includes source_type/source_label/upload_id/meeting_id;
  by_org totals include document decisions; 403 for non-super-admin.
"""
import asyncio
import os
from datetime import datetime, timezone, timedelta

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

BE = dotenv_values("/app/backend/.env")
FE = dotenv_values("/app/frontend/.env")
BASE = FE["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = BE["DATABASE_URL"]

TEST_ORG_ID = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"
TEST_UPLOAD_ID = "6fd622d4-fafb-4faa-8655-cb21a61ba2fd"
ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PW = "Admin123!X"
SUPERADMIN_EMAIL = "superadmin@1two.one"
SUPERADMIN_PW = "TestPass123!"


async def _override_mfa(email):
    conn = await asyncpg.connect(DSN, ssl="require")
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = datetime.now(timezone.utc) + timedelta(minutes=10)
    await conn.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, exp, email)
    await conn.close()


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=60)
    if r.status_code != 200:
        pytest.skip(f"login failed {email}: {r.status_code} {r.text[:200]}")
    data = r.json()
    if data.get("requires_mfa"):
        asyncio.run(_override_mfa(email))
        r2 = s.post(f"{BASE}/auth/verify-mfa", json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=60)
        if r2.status_code != 200:
            pytest.skip(f"mfa failed {email}: {r2.status_code} {r2.text[:200]}")
    return s


@pytest.fixture(scope="module")
def admin_sess():
    return _login(ADMIN_EMAIL, ADMIN_PW)


@pytest.fixture(scope="module")
def superadmin_sess():
    return _login(SUPERADMIN_EMAIL, SUPERADMIN_PW)


def _fb_row(upload_id=None, meeting_id=None, evidence_item_id=None, user_id=None):
    async def q():
        conn = await asyncpg.connect(DSN, ssl="require")
        try:
            where = []
            args = []
            if upload_id:
                args.append(upload_id); where.append(f"upload_id=${len(args)}")
            if meeting_id:
                args.append(meeting_id); where.append(f"meeting_id=${len(args)}")
            if evidence_item_id:
                args.append(evidence_item_id); where.append(f"evidence_item_id=${len(args)}")
            if user_id:
                args.append(user_id); where.append(f"user_id=${len(args)}")
            rows = await conn.fetch(
                f"SELECT id, meeting_id, upload_id, evidence_item_id, manager_action FROM evidence_feedback WHERE {' AND '.join(where) or '1=1'} ORDER BY timestamp DESC LIMIT 100",
                *args,
            )
            return [dict(r) for r in rows]
        finally:
            await conn.close()
    return asyncio.run(q())


def _cleanup_upload_feedback(upload_id, user_id):
    async def q():
        conn = await asyncpg.connect(DSN, ssl="require")
        try:
            await conn.execute("DELETE FROM evidence_feedback WHERE upload_id=$1 AND user_id=$2", upload_id, user_id)
        finally:
            await conn.close()
    asyncio.run(q())


def _cleanup_meeting_feedback(meeting_id, user_id, since_dt):
    async def q():
        conn = await asyncpg.connect(DSN, ssl="require")
        try:
            await conn.execute(
                "DELETE FROM evidence_feedback WHERE meeting_id=$1 AND user_id=$2 AND timestamp>=$3",
                meeting_id, user_id, since_dt)
        finally:
            await conn.close()
    asyncio.run(q())


# ---------- Doc upload: single PUT writes feedback ----------

class TestDocUploadEvidenceFeedback:
    def test_get_upload_has_mappings(self, admin_sess):
        r = admin_sess.get(f"{BASE}/doc-uploads/{TEST_UPLOAD_ID}", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["id"] == TEST_UPLOAD_ID
        assert isinstance(data.get("cqc_mappings"), list)
        assert len(data["cqc_mappings"]) > 0

    def test_put_evidence_writes_feedback_with_upload_id(self, admin_sess):
        me = admin_sess.get(f"{BASE}/auth/me").json()
        user_id = me["id"]
        # pick a mapping item and flip its status to 'accepted'
        up = admin_sess.get(f"{BASE}/doc-uploads/{TEST_UPLOAD_ID}").json()
        items = up["cqc_mappings"]
        # find any item to flip: pick one where changing status is safe
        target = items[0]
        ev_id = target["id"]
        orig_status = target.get("status")
        new_status = "needs_followup" if orig_status != "needs_followup" else "accepted"

        r = admin_sess.put(
            f"{BASE}/doc-uploads/{TEST_UPLOAD_ID}/evidence/{ev_id}",
            json={"status": new_status},
            timeout=30,
        )
        assert r.status_code == 200, r.text

        rows = _fb_row(upload_id=TEST_UPLOAD_ID, evidence_item_id=ev_id, user_id=user_id)
        assert len(rows) >= 1
        row = rows[0]
        assert row["meeting_id"] is None
        assert str(row["upload_id"]) == TEST_UPLOAD_ID
        assert row["evidence_item_id"] == ev_id
        assert row["manager_action"] == new_status

        # restore original state
        admin_sess.put(
            f"{BASE}/doc-uploads/{TEST_UPLOAD_ID}/evidence/{ev_id}",
            json={"status": orig_status or "pending"},
            timeout=30,
        )
        # cleanup ALL feedback rows we created in this test for this user+upload
        _cleanup_upload_feedback(TEST_UPLOAD_ID, user_id)

    def test_bulk_action_writes_N_feedback_rows(self, admin_sess):
        me = admin_sess.get(f"{BASE}/auth/me").json()
        user_id = me["id"]
        # capture original mappings to restore
        up_before = admin_sess.get(f"{BASE}/doc-uploads/{TEST_UPLOAD_ID}").json()
        orig_cqc = up_before["cqc_mappings"]

        # Get one confidence tier that has pending items
        from collections import Counter
        pending_by_conf = Counter(m.get("confidence") for m in orig_cqc if (m.get("status") or "pending") == "pending")
        if not pending_by_conf:
            pytest.skip("no pending items to bulk-action")
        conf = pending_by_conf.most_common(1)[0][0]
        expected_n = pending_by_conf[conf]

        r = admin_sess.post(
            f"{BASE}/doc-uploads/{TEST_UPLOAD_ID}/evidence/bulk-action",
            json={"confidence": conf, "status": "accepted"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        changed_count = body["changed_count"]
        assert changed_count >= expected_n  # includes possibly care_cert too if same conf label
        assert changed_count > 0

        rows_all = _fb_row(upload_id=TEST_UPLOAD_ID, user_id=user_id)
        assert len(rows_all) >= changed_count
        # verify each has upload_id set + meeting_id NULL + action=accepted
        recent = rows_all[:changed_count]
        assert all(r["meeting_id"] is None for r in recent)
        assert all(str(r["upload_id"]) == TEST_UPLOAD_ID for r in recent)
        assert all(r["manager_action"] == "accepted" for r in recent)

        # restore: PUT each changed one back to 'pending'
        for m in orig_cqc:
            if m.get("confidence") in {conf} and (m.get("status") or "pending") == "pending":
                admin_sess.put(
                    f"{BASE}/doc-uploads/{TEST_UPLOAD_ID}/evidence/{m['id']}",
                    json={"status": "pending"},
                    timeout=30,
                )
        _cleanup_upload_feedback(TEST_UPLOAD_ID, user_id)


# ---------- Meeting evidence regression (unchanged behaviour) ----------

class TestMeetingEvidenceRegression:
    MEETING_ID = "2f1cc088-0687-48b9-9f40-1dabb5285640"

    def test_meeting_review_still_works(self, admin_sess):
        r = admin_sess.get(f"{BASE}/review/{self.MEETING_ID}", timeout=30)
        # may 200 or 403 depending on access — assert it doesn't 500
        assert r.status_code in (200, 403, 404), r.text

    def test_meeting_evidence_put_writes_feedback_with_meeting_id(self, admin_sess):
        me = admin_sess.get(f"{BASE}/auth/me").json()
        user_id = me["id"]
        r = admin_sess.get(f"{BASE}/review/{self.MEETING_ID}", timeout=30)
        if r.status_code != 200:
            pytest.skip(f"meeting not accessible: {r.status_code}")
        data = r.json()
        analysis = data.get("analysis") or {}
        items = analysis.get("cqc_mappings") or []
        if not items:
            pytest.skip("no cqc mappings on meeting")
        target = items[0]
        ev_id = target["id"]
        orig_status = target.get("status") or "pending"
        new_status = "needs_followup" if orig_status != "needs_followup" else "accepted"

        since_dt = datetime.now(timezone.utc)
        r2 = admin_sess.put(
            f"{BASE}/review/{self.MEETING_ID}/evidence/{ev_id}",
            json={"status": new_status},
            timeout=30,
        )
        assert r2.status_code == 200, r2.text

        rows = _fb_row(meeting_id=self.MEETING_ID, evidence_item_id=ev_id, user_id=user_id)
        assert len(rows) >= 1
        row = rows[0]
        assert str(row["meeting_id"]) == self.MEETING_ID
        assert row["upload_id"] is None  # regression: meeting flow must NOT set upload_id
        assert row["manager_action"] == new_status

        # restore
        admin_sess.put(
            f"{BASE}/review/{self.MEETING_ID}/evidence/{ev_id}",
            json={"status": orig_status},
            timeout=30,
        )
        _cleanup_meeting_feedback(self.MEETING_ID, user_id, since_dt)


# ---------- Super Admin AI Accuracy report ----------

class TestAIAccuracyReport:
    def test_forbidden_for_admin(self, admin_sess):
        r = admin_sess.get(f"{BASE}/super-admin/ai-accuracy-report", timeout=30)
        assert r.status_code == 403

    def test_super_admin_can_access(self, superadmin_sess):
        r = superadmin_sess.get(f"{BASE}/super-admin/ai-accuracy-report", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "items" in data
        assert "stats" in data
        assert "by_org" in data
        assert "total" in data["stats"]
        assert "acceptance_rate" in data["stats"]

    def test_items_have_source_type_and_label(self, superadmin_sess, admin_sess):
        # Create one document-source feedback row so we know source_type='document' can appear
        me = admin_sess.get(f"{BASE}/auth/me").json()
        user_id = me["id"]
        up = admin_sess.get(f"{BASE}/doc-uploads/{TEST_UPLOAD_ID}").json()
        target = up["cqc_mappings"][0]
        ev_id = target["id"]
        orig_status = target.get("status")
        admin_sess.put(
            f"{BASE}/doc-uploads/{TEST_UPLOAD_ID}/evidence/{ev_id}",
            json={"status": "accepted"},
            timeout=30,
        )
        try:
            r = superadmin_sess.get(f"{BASE}/super-admin/ai-accuracy-report", timeout=30)
            assert r.status_code == 200
            data = r.json()
            assert len(data["items"]) > 0
            # every item must have source_type + source_label
            for it in data["items"]:
                assert it.get("source_type") in ("meeting", "document"), it
                assert "source_label" in it
                assert "upload_id" in it
                assert "meeting_id" in it
                if it["source_type"] == "document":
                    assert it["upload_id"] is not None
                    assert it["meeting_id"] is None
                else:
                    assert it["meeting_id"] is not None
                    assert it["upload_id"] is None
            # at least one document item should exist
            doc_items = [it for it in data["items"] if it["source_type"] == "document"]
            assert len(doc_items) >= 1

            # by_org totals should include this document decision under Test Company
            tc = next((o for o in data["by_org"] if o["org_id"] == TEST_ORG_ID), None)
            assert tc is not None
            assert tc["total"] >= 1
        finally:
            # restore + cleanup
            admin_sess.put(
                f"{BASE}/doc-uploads/{TEST_UPLOAD_ID}/evidence/{ev_id}",
                json={"status": orig_status or "pending"},
                timeout=30,
            )
            _cleanup_upload_feedback(TEST_UPLOAD_ID, user_id)

    def test_filters_still_work(self, superadmin_sess):
        # org filter
        r = superadmin_sess.get(
            f"{BASE}/super-admin/ai-accuracy-report",
            params={"org_id": TEST_ORG_ID},
            timeout=30,
        )
        assert r.status_code == 200
        data = r.json()
        for it in data["items"]:
            assert it["org_id"] == TEST_ORG_ID

        # action filter
        r2 = superadmin_sess.get(
            f"{BASE}/super-admin/ai-accuracy-report",
            params={"action": "accepted"},
            timeout=30,
        )
        assert r2.status_code == 200
        for it in r2.json()["items"]:
            assert it["manager_action"] == "accepted"

        # date filter shouldn't 500
        r3 = superadmin_sess.get(
            f"{BASE}/super-admin/ai-accuracy-report",
            params={"from_date": "2020-01-01", "to_date": "2099-12-31T23:59:59"},
            timeout=30,
        )
        assert r3.status_code == 200
