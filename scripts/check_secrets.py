"""Scan every git-tracked file for a real AWS account ID (a bare 12-digit run, or
one embedded in an ARN) - CLAUDE.md: "No employer names, client names, or internal
project names anywhere in this repo... this is a personal, public project," and a
live AWS account ID is the same category of leak. Run via `make check-secrets`
(also wired into pre-commit - see .pre-commit-config.yaml) rather than by hand.

Only git-tracked files are scanned (`git ls-files`), so gitignored build output
(build/, cdk.out/, .venv/) is never a false-positive source and never a blind spot -
anything not tracked can't be committed either.
"""

import re
import subprocess
import sys

# The standard placeholder account ID used throughout AWS's own documentation and
# example code - this repo's own tests/test_template.py uses it too (a real CDK
# Environment needs *some* 12-digit account, and this is the conventional fake one).
# Any other 12-digit run is treated as a potential real account ID.
_ALLOWED_ACCOUNT_IDS = {"123456789012"}

# A 12-digit run not immediately preceded/followed by another digit (so it doesn't
# false-positive inside a longer number, e.g. a byte count or timestamp).
_TWELVE_DIGITS = re.compile(r"(?<!\d)\d{12}(?!\d)")


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    )
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    violations = []
    for path in _tracked_files():
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable - not a text secret-leak candidate
        for line_number, line in enumerate(lines, start=1):
            for match in _TWELVE_DIGITS.finditer(line):
                if match.group() not in _ALLOWED_ACCOUNT_IDS:
                    violations.append((path, line_number, line.strip()))

    if violations:
        print("Found possible AWS account ID(s) in tracked files:", file=sys.stderr)
        for path, line_number, line in violations:
            print(f"  {path}:{line_number}: {line}", file=sys.stderr)
        return 1

    print(
        f"check-secrets: no account IDs found in {len(_tracked_files())} tracked files."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
