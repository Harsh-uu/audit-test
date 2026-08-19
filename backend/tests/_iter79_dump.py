import io, sys, re
sys.path.insert(0, "/app/backend/tests")
from _iter79_login import login, BASE
from pypdf import PdfReader

MID = "0f38f385-7c85-428e-923c-d7c365659192"
s = login("admin@supervision.com", "Admin123!")
for ep in ("export-pdf", "export-transcript"):
    r = s.get(f"{BASE}/review/{MID}/{ep}", timeout=180)
    print("=" * 30, ep, r.status_code, len(r.content))
    txt = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(r.content)).pages)
    print(txt[:3000])
    print("...TAIL...")
    print(txt[-1500:])
