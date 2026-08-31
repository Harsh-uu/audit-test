"""Diagnose super-admin login 502 through the public ingress."""
import time, json, requests
from dotenv import dotenv_values
FE = dotenv_values("/app/frontend/.env")
BASE = FE["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
LOCAL = "http://localhost:8001/api"
body = {"email": "superadmin@1two.one", "password": "NewPass123!"}
for label, url in (("LOCAL", LOCAL), ("PUBLIC", BASE)):
    t = time.time()
    try:
        r = requests.post(f"{url}/auth/login", json=body, timeout=180)
        print(label, r.status_code, round(time.time() - t, 1), "s", r.text[:150].replace("\n", " "))
    except Exception as e:
        print(label, "EXC", round(time.time() - t, 1), type(e).__name__, str(e)[:150])
# control: admin login through public
t = time.time()
r = requests.post(f"{BASE}/auth/login", json={"email": "admin@supervision.com", "password": "Admin123!"}, timeout=120)
print("PUBLIC admin", r.status_code, round(time.time() - t, 1), "s")
