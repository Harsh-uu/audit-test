"""Iter105 probe 3: is the lingering probe.webm a CDN cache artefact?"""
import os, sys, requests, time
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
url = os.environ["SUPABASE_URL"].rstrip("/")
key = os.environ["SUPABASE_SERVICE_KEY"]
h = {"Authorization": f"Bearer {key}", "apikey": key, "Cache-Control": "no-cache"}
p = "audio-recordings/TEST_iter105/probe.webm"
for suffix in ["", "?cb=" + str(int(time.time()))]:
    r = requests.get(f"{url}/storage/v1/object/{p}{suffix}", headers=h, timeout=30)
    print(suffix or "(plain)", "->", r.status_code, dict(list(r.headers.items()))if r.status_code==200 else r.text[:120])
# authenticated info endpoint (no CDN)
r = requests.get(f"{url}/storage/v1/object/info/{p}", headers=h, timeout=30)
print("info ->", r.status_code, r.text[:200])
