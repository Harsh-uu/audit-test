"""Iter116 probe: exercise the real upload -> job worker -> transcription pipeline path.

Uploads a tiny synthetic WAV (tone, no speech) to a throwaway meeting and polls
/processing/{id}/status plus the jobs table, to verify the queue claims the job,
the pipeline runs, and failure/empty-transcript handling is graceful (no stuck
'processing' forever, no unhandled 500).
"""
import asyncio
import io
import math
import struct
import sys
import time
import uuid
import wave
from datetime import datetime, timezone

import asyncpg
import requests
from dotenv import dotenv_values

FE = dotenv_values("/app/frontend/.env")
BE = dotenv_values("/app/backend/.env")
API = FE["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = BE["DATABASE_URL"]
T = 120


def make_wav(seconds=3.0, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            v = int(8000 * math.sin(2 * math.pi * 220 * i / rate))
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))
    return buf.getvalue()


def login(email, pw):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=T)
    r.raise_for_status()
    assert not r.json().get("requires_mfa")
    s.me = s.get(f"{API}/auth/me", timeout=T).json()
    return s


async def job_rows(mid):
    c = await asyncpg.connect(DSN, ssl="require")
    rows = await c.fetch("SELECT id, status, attempts, error, created_at, updated_at FROM jobs WHERE meeting_id=$1", mid)
    await c.close()
    return [dict(r) for r in rows]


def main():
    admin = login("admin@supervision.com", "Admin123!")
    tag = uuid.uuid4().hex[:8]
    r = admin.post(f"{API}/meetings/", json={
        "title": f"TEST_iter116_pipeline_{tag}",
        "meeting_type": "supervision",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "time": "09:00",
        "attendees": [{"user_id": admin.me["id"], "name": admin.me.get("name", "Admin")}],
    }, timeout=T)
    print("create:", r.status_code, r.text[:200])
    mid = r.json()["id"]
    try:
        audio = make_wav()
        up = admin.post(f"{API}/processing/{mid}/upload", data=audio,
                        headers={"Content-Type": "audio/wav"}, timeout=180)
        print("upload:", up.status_code, up.text[:300])
        if up.status_code != 200:
            return
        deadline = time.time() + 210
        last = None
        while time.time() < deadline:
            st = admin.get(f"{API}/processing/{mid}/status", timeout=T)
            body = st.json() if st.status_code == 200 else st.text[:200]
            if body != last:
                print(f"[{int(time.time()%1000)}] status {st.status_code}: {body}")
                last = body
            if isinstance(body, dict) and body.get("status") in ("in_review", "completed", "error", "failed", "review"):
                break
            time.sleep(6)
        print("jobs:", asyncio.run(job_rows(mid)))
        rv = admin.get(f"{API}/review/{mid}", timeout=T)
        print("review:", rv.status_code, str(rv.json())[:600] if rv.status_code == 200 else rv.text[:300])
    finally:
        d = admin.delete(f"{API}/meetings/{mid}", timeout=T)
        print("cleanup delete:", d.status_code)


main()
