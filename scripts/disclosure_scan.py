#!/usr/bin/env python3
"""Fail on common personal-path, credential, key, and unsafe-symlink disclosures."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "__pycache__", ".venv", "reports", "demo-output"}
OMISSION_BASENAMES = {"MEMORY.md", ".remember", "secrets"}
TEXT_PATTERNS = {
    "macOS user path": re.compile(r"/Users/[A-Za-z0-9._-]+"),
    "Linux user path": re.compile(r"/home/[A-Za-z0-9._-]+"),
    "external volume path": re.compile(r"/Volumes/[^\s`]+"),
    "private key": re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    "GitHub token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}


def _files() -> list[Path]:
    found: list[Path] = []
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if path.is_file() or path.is_symlink():
            found.append(path)
    return sorted(found)


def scan() -> list[str]:
    findings: list[str] = []
    for path in _files():
        relative = path.relative_to(ROOT)
        if relative == Path("scripts/disclosure_scan.py"):
            continue
        if any(part in OMISSION_BASENAMES for part in relative.parts):
            findings.append(f"omission-only path is tracked in the tree: {relative}")
        if path.is_symlink():
            resolved = path.resolve()
            try:
                resolved.relative_to(ROOT)
            except ValueError:
                findings.append(f"symlink escapes repository: {relative} -> {resolved}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in TEXT_PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append(f"{relative}:{line}: {label}")
    return findings


def main() -> int:
    findings = scan()
    if findings:
        print("disclosure scan failed:", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1
    print("disclosure scan: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
