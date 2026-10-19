#!/usr/bin/env python3
"""
Lightweight secret scanner — P0-02 follow-up.

Blocks commits (and CI runs) that introduce a hardcoded signing/API secret
literal, the exact class of bug that leaked JWT_SECRET via
backend/tests/test_org_id_jwt_claim.py. Intentionally narrow (SECRET /
API_KEY / PRIVATE_KEY / ACCESS_KEY-named variables only) to avoid flagging
the many pre-existing throwaway test-account PASSWORD fixtures already in
this codebase, which are not the threat model here.

Usage:
    python3 scripts/check_secrets.py               # scan staged files (pre-commit)
    python3 scripts/check_secrets.py --all         # scan all tracked files (CI)
    python3 scripts/check_secrets.py file1 file2   # scan specific files
"""
import re
import subprocess
import sys

# Variable-name / literal-value heuristic: a SECRET-ish name assigned a long
# quoted literal, NOT read from the environment or a known safe test helper.
_ASSIGN_RE = re.compile(
    r'\b([A-Za-z_][A-Za-z0-9_]*(?:SECRET|API_KEY|PRIVATE_KEY|ACCESS_KEY)[A-Za-z0-9_]*)'
    r'\s*[:=]\s*["\']([A-Za-z0-9_\-./+=]{20,})["\']'
)
_SAFE_RHS_MARKERS = ("os.environ", "os.getenv", "_read_env(", "dotenv_values", "getenv(")
_SKIP_DIRS = ("node_modules/", ".git/", "venv/", "__pycache__/", "build/", "dist/")
_SKIP_EXTS = (".png", ".jpg", ".jpeg", ".ico", ".svg", ".woff", ".woff2", ".lock")


def _staged_files():
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [f for f in out.splitlines() if f]


def _all_tracked_files():
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if f]


def _read_staged_content(path):
    """Read a file's STAGED content (what will actually be committed), not
    the working-tree copy — matches what a real pre-commit hook must check."""
    result = subprocess.run(["git", "show", f":{path}"], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else None


def scan_file(path, content):
    findings = []
    for lineno, line in enumerate(content.splitlines(), start=1):
        if any(marker in line for marker in _SAFE_RHS_MARKERS):
            continue
        m = _ASSIGN_RE.search(line)
        if m:
            findings.append((lineno, m.group(1)))
    return findings


def main(argv):
    if "--all" in argv:
        files = _all_tracked_files()
        use_staged = False
    elif len(argv) > 1:
        files = [a for a in argv[1:] if a != "--all"]
        use_staged = False
    else:
        files = _staged_files()
        use_staged = True

    violations = []
    for path in files:
        if any(skip in path for skip in _SKIP_DIRS) or path.endswith(_SKIP_EXTS):
            continue
        if use_staged:
            content = _read_staged_content(path)
        else:
            try:
                with open(path, "r", errors="ignore") as f:
                    content = f.read()
            except (FileNotFoundError, IsADirectoryError):
                content = None
        if content is None:
            continue
        for lineno, varname in scan_file(path, content):
            violations.append(f"  {path}:{lineno} — hardcoded literal assigned to `{varname}`")

    if violations:
        print("BLOCKED: possible hardcoded secret(s) found:\n" + "\n".join(violations))
        print("\nFix: read the value from the environment instead "
              "(os.environ[...] / _read_env(...)), never hardcode it.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
