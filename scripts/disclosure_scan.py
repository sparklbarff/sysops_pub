#!/usr/bin/env python3
"""Fail on common personal identifiers, credentials, and unsafe tracked paths."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = ROOT / "scripts" / "disclosure_allowlist.json"
OMISSION_BASENAMES = {"MEMORY.md", ".remember", "secrets"}
TEXT_PATTERNS = {
    "macOS user path": re.compile(r"/Users/[A-Za-z0-9._-]+"),
    "Linux user path": re.compile(r"/home/[A-Za-z0-9._-]+"),
    "Windows user path": re.compile(r"[A-Za-z]:\\Users\\[A-Za-z0-9._-]+"),
    "external volume path": re.compile(r"/Volumes/[A-Za-z0-9._-][^\s`]*"),
    "private key": re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    "GitHub token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "email address": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "IPv4 address": re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])"),
    "MAC address": re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"),
    "UUID-like device identifier": re.compile(
        r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[1-5][0-9A-Fa-f]{3}-"
        r"[89ABab][0-9A-Fa-f]{3}-[0-9A-Fa-f]{12}\b"
    ),
    "local hostname": re.compile(r"\b[A-Za-z0-9][A-Za-z0-9-]{1,62}\.local\b"),
    "hostname declaration": re.compile(
        r"(?im)\b(?:computer_name|host|hostname)\s*[:=]\s*[A-Za-z0-9][A-Za-z0-9._-]*"
    ),
}


class ScanError(RuntimeError):
    """The scanner could not establish the tracked disclosure surface."""


def _tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "-z"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if result.returncode:
        raise ScanError("git ls-files failed; run this check from a Git clone")
    found: list[Path] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        relative = Path(raw.decode("utf-8"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ScanError(f"Git returned an unsafe tracked path: {relative}")
        path = ROOT / relative
        if path.exists() or path.is_symlink():
            found.append(path)
    return sorted(found)


def _allowlist() -> set[str]:
    try:
        value = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ScanError(f"invalid disclosure allowlist: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ScanError("disclosure allowlist schema_version must be 1")
    findings = value.get("findings")
    if not isinstance(findings, list) or not all(isinstance(item, str) for item in findings):
        raise ScanError("disclosure allowlist findings must be a list of strings")
    return set(findings)


def scan() -> list[str]:
    allowlist = _allowlist()
    findings: list[str] = []
    seen_findings: set[str] = set()
    for path in _tracked_files():
        relative = path.relative_to(ROOT)
        if any(part in OMISSION_BASENAMES for part in relative.parts):
            findings.append(f"{relative}: omission-only path is tracked")
        if path.is_symlink():
            resolved = path.resolve()
            try:
                resolved.relative_to(ROOT)
            except ValueError:
                findings.append(f"{relative}: symlink escapes repository -> {resolved}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in TEXT_PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                finding = f"{relative}:{line}: {label}"
                seen_findings.add(finding)
                if finding not in allowlist:
                    findings.append(finding)
    unused = sorted(allowlist - seen_findings)
    findings.extend(f"allowlist entry is stale: {entry}" for entry in unused)
    return findings


def main() -> int:
    try:
        findings = scan()
    except ScanError as exc:
        print(f"disclosure scan failed: {exc}", file=sys.stderr)
        return 2
    if findings:
        print("disclosure scan failed:", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1
    print("disclosure scan: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
