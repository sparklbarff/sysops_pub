#!/usr/bin/env python3
"""Fail on common personal identifiers, credentials, and unsafe tracked paths."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = ROOT / "scripts" / "disclosure_allowlist.json"
OMISSION_NAMES = {
    ".remember",
    "handoff.md",
    "memory.md",
    "secrets",
    "session.md",
    "transcript.md",
}
OMISSION_DIRECTORIES = {
    "indexes",
    "logs",
    "model-cache",
    "reports",
    "secrets",
    "sessions",
    "transcripts",
}
OMISSION_SUFFIXES = {
    ".7z",
    ".arrow",
    ".bin",
    ".db",
    ".duckdb",
    ".faiss",
    ".gz",
    ".index",
    ".jsonl",
    ".key",
    ".log",
    ".npy",
    ".npz",
    ".p12",
    ".parquet",
    ".pem",
    ".pickle",
    ".pkl",
    ".sqlite",
    ".sqlite3",
    ".tar",
    ".zip",
}
OMISSION_BASENAME_PATTERN = re.compile(
    r"(?:^|[-_.])(?:handoffs?|ledgers?|logs?|memories|memory|metrics?|reports?|sessions?|"
    r"task[-_]?state|transcripts?)(?:$|[-_.0-9])"
)
GITHUB_NOREPLY_PATTERN = re.compile(
    r"^(?:[0-9]+\+)?[A-Za-z0-9-]+@users\.noreply\.github\.com$",
    re.IGNORECASE,
)
TEXT_PATTERNS = {
    "macOS user path": re.compile(r"/Users/[A-Za-z0-9._-]+"),
    "Linux user path": re.compile(r"/home/[A-Za-z0-9._-]+"),
    "Windows user path": re.compile(
        r"[A-Za-z]:(?:\\+|/+)Users(?:\\+|/+)[A-Za-z0-9._-]+",
        re.IGNORECASE,
    ),
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


def _is_text(text: str) -> bool:
    return all(character in "\n\r\t" or character.isprintable() for character in text)


def _hash_bound_entries(value: object, label: str) -> dict[str, dict[str, str]]:
    if not isinstance(value, list):
        raise ScanError(f"disclosure allowlist {label} must be a list")
    entries: dict[str, dict[str, str]] = {}
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "reason"}:
            raise ScanError(f"each {label} entry needs path, sha256, and reason")
        path = entry["path"]
        sha256 = entry["sha256"]
        reason = entry["reason"]
        if not all(isinstance(item, str) and item for item in (path, sha256, reason)):
            raise ScanError(f"{label} path, sha256, and reason must be non-empty strings")
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts or str(relative) != path:
            raise ScanError(f"{label} path must be an exact safe relative path: {path!r}")
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ScanError(f"{label} sha256 must be lowercase hexadecimal: {path}")
        if path in entries:
            raise ScanError(f"duplicate {label} path: {path}")
        entries[path] = {"sha256": sha256, "reason": reason}
    return entries


HISTORY_FINDING_PATTERN = re.compile(r"^[0-9a-f]{40}:[^\s:][^:]*: [^:]+$")
HashBound = dict[str, dict[str, str]]
Allowlist = tuple[set[str], HashBound, HashBound, set[str]]


def _allowlist() -> Allowlist:
    try:
        value = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ScanError(f"invalid disclosure allowlist: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 3:
        raise ScanError("disclosure allowlist schema_version must be 3")
    findings = value.get("findings")
    if not isinstance(findings, list) or not all(isinstance(item, str) for item in findings):
        raise ScanError("disclosure allowlist findings must be a list of strings")
    history = value.get("history_findings", [])
    if not isinstance(history, list) or not all(
        isinstance(item, str) and HISTORY_FINDING_PATTERN.fullmatch(item) for item in history
    ):
        raise ScanError(
            "disclosure allowlist history_findings must be '<full commit>:<path>: <label>' strings"
        )
    binary_files = _hash_bound_entries(value.get("binary_files"), "binary_files")
    omission_files = _hash_bound_entries(value.get("omission_files"), "omission_files")
    return set(findings), binary_files, omission_files, set(history)


def scan() -> list[str]:
    allowlist, binary_allowlist, omission_allowlist, _history = _allowlist()
    findings: list[str] = []
    seen_findings: set[str] = set()
    seen_binaries: set[str] = set()
    seen_omissions: set[str] = set()
    for path in _tracked_files():
        relative = path.relative_to(ROOT)
        relative_string = str(relative)
        lowered_parts = [part.casefold() for part in relative.parts]
        omission_reasons: list[str] = []
        if any(part in OMISSION_NAMES for part in lowered_parts):
            omission_reasons.append("omission-only path")
        elif any(part in OMISSION_DIRECTORIES for part in lowered_parts[:-1]):
            omission_reasons.append("omission-only directory")
        elif OMISSION_BASENAME_PATTERN.search(relative.stem.casefold()):
            omission_reasons.append("omission-only artifact name")
        if relative.suffix.casefold() in OMISSION_SUFFIXES:
            omission_reasons.append("omission-only file type")
        if path.is_symlink():
            resolved = path.resolve()
            try:
                resolved.relative_to(ROOT)
            except ValueError:
                findings.append(f"{relative}: symlink escapes repository -> {resolved}")
            continue
        try:
            content = path.read_bytes()
        except OSError as exc:
            findings.append(f"{relative}: could not read tracked file: {exc}")
            continue
        if omission_reasons:
            omission_entry = omission_allowlist.get(relative_string)
            if omission_entry is None:
                findings.extend(f"{relative}: {reason} is tracked" for reason in omission_reasons)
            else:
                seen_omissions.add(relative_string)
                actual_sha256 = hashlib.sha256(content).hexdigest()
                if actual_sha256 != omission_entry["sha256"]:
                    findings.append(f"{relative}: omission allowlist SHA-256 mismatch")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = None
        if text is None or not _is_text(text):
            binary_entry = binary_allowlist.get(relative_string)
            if binary_entry is None:
                findings.append(f"{relative}: non-text file is not binary-allowlisted")
                continue
            seen_binaries.add(relative_string)
            actual_sha256 = hashlib.sha256(content).hexdigest()
            if actual_sha256 != binary_entry["sha256"]:
                findings.append(f"{relative}: binary allowlist SHA-256 mismatch")
            continue
        if relative_string in binary_allowlist:
            seen_binaries.add(relative_string)
            findings.append(f"{relative}: binary allowlist entry points to a UTF-8 text file")
        for label, pattern in TEXT_PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                finding = f"{relative}:{line}: {label}"
                seen_findings.add(finding)
                if finding not in allowlist:
                    findings.append(finding)
    unused = sorted(allowlist - seen_findings)
    findings.extend(f"allowlist entry is stale: {entry}" for entry in unused)
    unused_binaries = sorted(set(binary_allowlist) - seen_binaries)
    findings.extend(f"binary allowlist entry is stale: {entry}" for entry in unused_binaries)
    unused_omissions = sorted(set(omission_allowlist) - seen_omissions)
    findings.extend(f"omission allowlist entry is stale: {entry}" for entry in unused_omissions)
    return findings


def _history_content_findings() -> list[str]:
    """Match every line any reachable commit added against the identifier patterns.

    A commit is published the moment it exists, so a line that was added and later removed is as
    disclosed as one still in the tree. The current-tree scan cannot see it; this one reads each
    commit's own diff. A hit is reported once per commit, path and label, and is suppressed only by
    an exact `history_findings` entry naming that full commit; an entry that no longer matches is
    reported as stale. Merge commits show no diff of their own here, so a conflict resolution that
    introduces text appears under the commit that carries it.
    """
    _findings, _binaries, _omissions, allowlist = _allowlist()
    result = subprocess.run(
        ["git", "log", "-p", "--format=%x1e%H", "--unified=0", "--no-color", "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if result.returncode:
        raise ScanError("git log -p failed; commit content could not be audited")
    findings: list[str] = []
    seen: set[str] = set()
    for record in result.stdout.decode("utf-8", errors="replace").split("\x1e"):
        header, _separator, body = record.partition("\n")
        commit = header.strip()
        if not commit:
            continue
        path: str | None = None
        in_hunk = False
        for line in body.splitlines():
            if line.startswith("diff --git "):
                path = None
                in_hunk = False
            elif line.startswith("+++ ") and not in_hunk:
                target = line[4:]
                path = None if target == "/dev/null" else target.removeprefix("b/")
            elif line.startswith("@@"):
                in_hunk = path is not None
            elif in_hunk and line.startswith("+"):
                for label, pattern in TEXT_PATTERNS.items():
                    if pattern.search(line[1:]):
                        finding = f"{commit}:{path}: {label}"
                        if finding in seen:
                            continue
                        seen.add(finding)
                        if finding not in allowlist:
                            findings.append(finding)
    unused = sorted(allowlist - seen)
    findings.extend(f"history allowlist entry is stale: {entry}" for entry in unused)
    return findings


def _history_metadata_findings() -> list[str]:
    result = subprocess.run(
        ["git", "log", "HEAD", "--format=%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1e"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise ScanError("git log failed; commit identity metadata could not be audited")
    findings: list[str] = []
    for raw_record in result.stdout.split("\x1e"):
        record = raw_record.strip("\r\n")
        if not record:
            continue
        fields = record.split("\x1f")
        if len(fields) != 5:
            raise ScanError("git log returned malformed commit identity metadata")
        commit, author_name, author_email, committer_name, committer_email = fields
        for role, name, email in (
            ("author", author_name, author_email),
            ("committer", committer_name, committer_email),
        ):
            if not GITHUB_NOREPLY_PATTERN.fullmatch(email):
                findings.append(f"commit {commit}: {role} email is not GitHub noreply metadata")
            for label, pattern in TEXT_PATTERNS.items():
                if label == "email address":
                    continue
                if pattern.search(name):
                    findings.append(f"commit {commit}: {role} name contains {label}")
    return findings


def main() -> int:
    try:
        findings = scan()
        findings.extend(_history_content_findings())
        findings.extend(_history_metadata_findings())
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
