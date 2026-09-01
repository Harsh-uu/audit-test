"""Verify the migration split is a faithful copy of the original monolithic init_db.py.

Extracts all SQL-ish string literals from the pre-refactor init_db.py (git HEAD)
and from the new migrations/*.py, normalises whitespace, and reports statements
present in the old file but missing from the new package (and vice versa).
"""
import ast
import re
import subprocess
from pathlib import Path

MIG_DIR = Path("/app/backend/migrations")


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def sql_literals(src):
    out = []
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value
            if re.search(r"\b(CREATE|ALTER|DROP|GRANT|INSERT|UPDATE|DELETE|SELECT)\b", v, re.I):
                out.append(norm(v))
    return out


old_src = subprocess.check_output(
    ["git", "show", "HEAD:backend/init_db.py"], cwd="/app", text=True
)
old = sql_literals(old_src)

new = []
for f in sorted(MIG_DIR.glob("*.py")):
    new += sql_literals(f.read_text())

print(f"old SQL literals: {len(old)}   new SQL literals: {len(new)}")

new_set = set(new)
old_set = set(old)
missing = [s for s in old if s not in new_set]
added = [s for s in new if s not in old_set]

print(f"\nMISSING from migrations/ ({len(missing)}):")
for s in missing:
    print("  -", s[:220])

print(f"\nEXTRA in migrations/ ({len(added)}):")
for s in added:
    print("  +", s[:220])

# duplicates check
from collections import Counter
dups = {k: v for k, v in Counter(new).items() if v > 1}
print(f"\nDUPLICATED statements in migrations/: {len(dups)}")
for k, v in list(dups.items())[:10]:
    print(f"  x{v}", k[:180])
