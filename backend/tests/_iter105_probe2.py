"""Iter105 probe 2: dig into whether remove() actually deletes."""
import os, sys, json, time
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")
from supabase import create_client
import supabase as sb_mod

print("supabase-py version:", getattr(sb_mod, "__version__", "?"))
client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
b = client.storage.from_("audio-recordings")
path = "TEST_iter105b/probe2.webm"
b.upload(path, b"hello-iter105b", file_options={"content-type": "audio/webm", "upsert": "true"})
print("uploaded")
print("list before:", [f["name"] for f in b.list("TEST_iter105b")])
res = b.remove([path])
print("remove() returned:", json.dumps(res, default=str)[:500])
time.sleep(2)
print("list after:", [f["name"] for f in b.list("TEST_iter105b")])
try:
    d = b.download(path)
    print("download after remove: STILL PRESENT", len(d))
except Exception as e:
    print("download after remove raised:", type(e).__name__, str(e)[:200])

# re-check the first probe path
print("list TEST_iter105:", [f["name"] for f in b.list("TEST_iter105")])
try:
    d = b.download("TEST_iter105/probe.webm")
    print("probe.webm still downloadable:", len(d))
except Exception as e:
    print("probe.webm gone:", type(e).__name__, str(e)[:200])
