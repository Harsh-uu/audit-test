"""Iter115 edge probes: invalid UUID path param handling + attendee access to
/api/admin/standards (frontend StaffPortfolio calls this for care_cert)."""
import os

import requests
from dotenv import dotenv_values

FE = dotenv_values("/app/frontend/.env")
API = (os.environ.get("REACT_APP_BACKEND_URL") or FE["REACT_APP_BACKEND_URL"]).rstrip("/") + "/api"


def login(email, pw):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=60)
    assert r.status_code == 200, (email, r.status_code, r.text[:200])
    return s


admin = login("admin@supervision.com", "Admin123!")
att = login("user@supervision.com", "AnotherNew789!")

for tag, s in (("admin", admin), ("attendee", att)):
    for path in ("/meetings/not-a-uuid", "/portfolio/not-a-uuid", "/review/not-a-uuid"):
        r = s.get(f"{API}{path}", timeout=60)
        print(f"[{tag}] GET {path} -> {r.status_code} {r.text[:120]}")

r = att.get(f"{API}/admin/standards?type=care_cert", timeout=60)
print("[attendee] /admin/standards?type=care_cert ->", r.status_code, r.text[:120])
