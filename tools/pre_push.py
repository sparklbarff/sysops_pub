#!/usr/bin/env python3
"""Verify every outgoing Git commit in an isolated worktree."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OBJECT_ID_PATTERN = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})")


class PrePushError(RuntimeError):
    """The outgoing ref set could not be verified safely."""


def _is_null_sha(value: str) -> bool:
    return bool(value) and set(value) == {"0"}


def parse_outgoing_shas(lines: Iterable[str]) -> list[str]:
    """Return unique outgoing object IDs from Git's pre-push stdin protocol."""
    shas: list[str] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) != 4:
            raise PrePushError(f"malformed pre-push input on line {line_number}")
        _local_ref, local_sha, _remote_ref, _remote_sha = fields
        if _is_null_sha(local_sha):
            continue
        if OBJECT_ID_PATTERN.fullmatch(local_sha) is None:
            raise PrePushError(f"invalid outgoing object ID on line {line_number}")
        if local_sha not in seen:
            seen.add(local_sha)
            shas.append(local_sha)
    return shas


def _git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def verify_outgoing_sha(sha: str) -> None:
    """Run the committed verifier from the exact outgoing tree."""
    resolved = _git("rev-parse", "--verify", f"{sha}^{{commit}}")
    if resolved.returncode:
        detail = resolved.stderr.strip() or f"git rev-parse returned {resolved.returncode}"
        raise PrePushError(f"cannot resolve outgoing commit {sha}: {detail}")
    commit_sha = resolved.stdout.strip()

    with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-") as directory:
        worktree = Path(directory) / "candidate"
        added = _git("worktree", "add", "--quiet", "--detach", str(worktree), commit_sha)
        if added.returncode:
            detail = added.stderr.strip() or f"git worktree add returned {added.returncode}"
            raise PrePushError(f"cannot materialize outgoing commit {commit_sha}: {detail}")
        try:
            verifier = worktree / "tools" / "verify_release.py"
            if not verifier.is_file():
                raise PrePushError(
                    f"outgoing commit {commit_sha} does not contain tools/verify_release.py"
                )
            print(f"pre-push: verifying outgoing commit {commit_sha}", flush=True)
            result = subprocess.run(
                [sys.executable, str(verifier), "--require-tools", "--candidate-sha", commit_sha],
                cwd=worktree,
                check=False,
            )
            if result.returncode:
                raise PrePushError(
                    f"release verification failed for outgoing commit {commit_sha} "
                    f"with exit {result.returncode}"
                )
        finally:
            removed = _git("worktree", "remove", "--force", str(worktree))
            if removed.returncode:
                detail = (
                    removed.stderr.strip() or f"git worktree remove returned {removed.returncode}"
                )
                print(
                    f"pre-push: warning: temporary worktree cleanup failed: {detail}",
                    file=sys.stderr,
                )


def _build_usage_error(arguments: Sequence[str]) -> PrePushError | None:
    if arguments:
        return PrePushError("pre-push verifier does not accept command-line arguments")
    return None


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    usage_error = _build_usage_error(arguments)
    if usage_error is not None:
        print(f"pre-push: {usage_error}", file=sys.stderr)
        return 2
    try:
        outgoing_shas = parse_outgoing_shas(sys.stdin)
        if not outgoing_shas:
            print("pre-push: no outgoing commits require verification")
            return 0
        for sha in outgoing_shas:
            verify_outgoing_sha(sha)
        print(f"pre-push: verified {len(outgoing_shas)} outgoing commit(s)")
        return 0
    except PrePushError as exc:
        print(f"pre-push: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
