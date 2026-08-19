import sys, json
sys.path.insert(0, "/app/backend/tests")
from _iter79_login import login, BASE

s = login("admin@supervision.com", "Admin123!")
r = s.get(f"{BASE}/meetings/", timeout=60)
print(r.status_code)
ms = r.json()
if isinstance(ms, dict):
    ms = ms.get("meetings", ms.get("items", []))
print("count", len(ms))
for m in ms:
    print(m.get("id"), "|", m.get("status"), "|", (m.get("title") or "")[:40], "|", m.get("date"), "| transcript:", bool(m.get("transcript_id")))
