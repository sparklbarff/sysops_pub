#!/usr/bin/env python3
"""Run the dependency-free checks on Windows, macOS, or Linux."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(label: str, arguments: list[str]) -> int:
    print(f"check: {label}", flush=True)
    result = subprocess.run(arguments, cwd=REPO_ROOT, check=False)
    if result.returncode:
        print(f"check failed: {label}", file=sys.stderr)
    return result.returncode


def main() -> int:
    checks = [
        (
            "unit tests",
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        ),
        ("disclosure scan", [sys.executable, "scripts/disclosure_scan.py"]),
        ("portable demo", [sys.executable, "tools/demo.py"]),
    ]
    for label, command in checks:
        if _run(label, command):
            return 1
    print("test suite: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
