"""Scan every git-tracked file for leaked secrets and personal identifiers:
1. Real AWS account IDs (bare 12-digit run, or embedded in ARN) - CLAUDE.md rule
2. Employer/domain names (case-insensitive) - CLAUDE.md: "No employer names,
   client names, or internal project names anywhere in this repo... this is a
   personal, public project."

Run via `make check-secrets` (also wired into pre-commit - see
.pre-commit-config.yaml) rather than by hand.

Only git-tracked files are scanned (`git ls-files`), so gitignored build output
(build/, cdk.out/, .venv/) is never a false-positive source and never a blind spot.
"""

import re
import subprocess
import sys

# The standard placeholder account ID used throughout AWS's own documentation and
# example code - this repo's own tests/test_template.py uses it too (a real CDK
# Environment needs *some* 12-digit account, and this is the conventional fake one).
# Any other 12-digit run is treated as a potential real account ID.
_ALLOWED_ACCOUNT_IDS = {"123456789012"}

# A 12-digit run not immediately preceded/followed by another digit
_TWELVE_DIGITS = re.compile(r"(?<!\d)\d{12}(?!\d)")

# Employer/domain names to reject (case-insensitive)
_FORBIDDEN_NAMES = {
    "pwc",  # PwC
    "pricewaterhousecoopers",
    "pwcllp",
}

# Files exempt from name checks (e.g., this script itself defines the names to scan for)
_EXEMPT_PATHS = {"scripts/check_secrets.py"}


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    )
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    violations = []
    tracked = _tracked_files()

    for path in tracked:
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable - not a text secret-leak candidate

        for line_number, line in enumerate(lines, start=1):
            # Check for AWS account IDs
            for match in _TWELVE_DIGITS.finditer(line):
                if match.group() not in _ALLOWED_ACCOUNT_IDS:
                    violations.append(
                        (path, line_number, "AWS account ID", line.strip())
                    )

            # Check for employer/domain names (case-insensitive) - skip exempt paths
            if path not in _EXEMPT_PATHS:
                line_lower = line.lower()
                for name in _FORBIDDEN_NAMES:
                    if name in line_lower:
                        violations.append(
                            (
                                path,
                                line_number,
                                f"employer/domain ({name})",
                                line.strip(),
                            )
                        )

    if violations:
        print("Found possible secrets/identifiers in tracked files:", file=sys.stderr)
        for path, line_number, violation_type, line in violations:
            print(f"  {path}:{line_number} [{violation_type}]: {line}", file=sys.stderr)
        return 1

    print(
        f"check-secrets: no account IDs or employer names found in {len(tracked)} tracked files."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
