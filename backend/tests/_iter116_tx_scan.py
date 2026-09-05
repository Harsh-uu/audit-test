"""Static scan: find AI / network / sleep awaits executed INSIDE an open
database transaction (with_org/with_admin), which would be exposed to the new
idle_in_transaction_session_timeout=30s DB setting."""
import re, pathlib

SLOW = re.compile(r"await\s+(analyze_meeting|transcribe_with_assemblyai|diarize_transcript|"
                  r"generate_meeting_summary|map_speaker_numbers_to_names|asyncio\.sleep|"
                  r"httpx|client\.|send_email|call_llm|_call_|generate_|put_audio|get_audio|delete_audio)")

for p in sorted(pathlib.Path("/app/backend").rglob("*.py")):
    if "tests" in str(p) or "migrations" in str(p):
        continue
    lines = p.read_text().splitlines()
    stack = None
    for i, line in enumerate(lines):
        m = re.match(r"(\s*)async with database\.with_(org|admin)\(", line)
        if m:
            stack = (len(m.group(1)), i + 1)
            continue
        if stack:
            indent = len(line) - len(line.lstrip())
            if line.strip() and indent <= stack[0]:
                stack = None
            elif SLOW.search(line):
                print(f"{p}:{i+1}  (tx opened line {stack[1]}):{line.strip()[:120]}")
