#!/usr/bin/env python3
"""Verify every outgoing Git commit in an isolated worktree with the gate that commit declares.

Git's pre-push protocol names each ref's local and remote object IDs on stdin. Every commit the push
would publish is listed, oldest first, and each is checked out detached into a temporary worktree
and verified there with its own gate: the command its pyproject.toml declares under
[tool.sysops_pub.gate], with {commit} replaced by the commit's identity. Without a declaration the
gate is tools/verify_release.py --require-tools, this repository's own. A tree this clone has
already verified with the same command is not verified again; that memo lives inside .git, is never
tracked, records the tree and the command but not the tools' versions, and deleting it forces a
full re-verification.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Iterable, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OBJECT_ID_PATTERN = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})")
GATE_TABLE = ("tool", "sysops_pub", "gate")
DEFAULT_GATE = (
    "python3",
    "tools/verify_release.py",
    "--require-tools",
    "--candidate-sha",
    "{commit}",
)
MEMO_NAME = "sysops-pub-verified-trees"


class PrePushError(RuntimeError):
    """The outgoing ref set could not be verified safely."""


def _is_null_sha(value: str) -> bool:
    return bool(value) and set(value) == {"0"}


def parse_outgoing_refs(lines: Iterable[str]) -> list[tuple[str, str]]:
    """Return unique (local, remote) object ID pairs from Git's pre-push stdin protocol."""
    refs: list[tuple[str, str]] = []
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) != 4:
            raise PrePushError(f"malformed pre-push input on line {line_number}")
        _local_ref, local_sha, _remote_ref, remote_sha = fields
        if _is_null_sha(local_sha):
            continue
        if OBJECT_ID_PATTERN.fullmatch(local_sha) is None:
            raise PrePushError(f"invalid outgoing object ID on line {line_number}")
        if OBJECT_ID_PATTERN.fullmatch(remote_sha) is None:
            raise PrePushError(f"invalid remote object ID on line {line_number}")
        if (local_sha, remote_sha) not in refs:
            refs.append((local_sha, remote_sha))
    return refs


def _git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def outgoing_commits(refs: Iterable[tuple[str, str]]) -> list[str]:
    """Every commit the push would publish, oldest first, not only each ref's tip.

    A commit is outgoing when it is reachable from the pushed object and from neither the remote
    ref's current value nor any remote-tracking ref. A remote value this clone has never fetched
    cannot bound the range, so the push is refused rather than verified on a guess.
    """
    commits: list[str] = []
    for local_sha, remote_sha in refs:
        excluded = ["--remotes"]
        if not _is_null_sha(remote_sha):
            known = _git("cat-file", "-e", f"{remote_sha}^{{commit}}")
            if known.returncode:
                raise PrePushError(
                    f"remote commit {remote_sha} is not in this clone; fetch before pushing"
                )
            excluded.insert(0, remote_sha)
        listed = _git("rev-list", "--reverse", "--topo-order", local_sha, "--not", *excluded)
        if listed.returncode:
            detail = listed.stderr.strip() or f"git rev-list returned {listed.returncode}"
            raise PrePushError(f"cannot list outgoing commits for {local_sha}: {detail}")
        for commit in listed.stdout.split():
            if commit not in commits:
                commits.append(commit)
    return commits


def gate_command(commit_sha: str) -> list[str]:
    """The verifier the commit declares in its own pyproject.toml, or this repository's default."""
    shown = _git("show", f"{commit_sha}:pyproject.toml")
    if shown.returncode:
        return list(DEFAULT_GATE)
    try:
        data: object = tomllib.loads(shown.stdout)
    except tomllib.TOMLDecodeError as exc:
        raise PrePushError(f"pyproject.toml in {commit_sha} is not valid TOML: {exc}") from exc
    table = data
    for key in GATE_TABLE:
        table = table.get(key) if isinstance(table, dict) else None
    if table is None:
        return list(DEFAULT_GATE)
    command = table.get("command") if isinstance(table, dict) else None
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(item, str) and item for item in command)
    ):
        raise PrePushError(
            f"[tool.sysops_pub.gate] command in {commit_sha} must be a non-empty list of strings"
        )
    return list(command)


def _resolved_gate(command: Sequence[str], commit_sha: str) -> list[str]:
    argv = [item.replace("{commit}", commit_sha) for item in command]
    if argv[0] in {"python3", "python"}:
        argv[0] = sys.executable
    return argv


def _memo_path() -> Path | None:
    common = _git("rev-parse", "--git-common-dir")
    if common.returncode:
        return None
    directory = Path(common.stdout.strip())
    if not directory.is_absolute():
        directory = REPO_ROOT / directory
    return directory / MEMO_NAME


def memo_key(commit_sha: str, command: Sequence[str]) -> str:
    """The tree a commit carries and the command that verified it; history is not part of it."""
    tree = _git("rev-parse", f"{commit_sha}^{{tree}}")
    if tree.returncode:
        raise PrePushError(f"cannot resolve the tree of {commit_sha}")
    digest = hashlib.sha256(json.dumps(list(command)).encode("utf-8")).hexdigest()
    return f"{tree.stdout.strip()} {digest}"


def _already_verified(key: str) -> bool:
    memo = _memo_path()
    if memo is None or not memo.is_file():
        return False
    try:
        return key in memo.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False


def _remember(key: str) -> None:
    memo = _memo_path()
    if memo is None:
        return
    try:
        with memo.open("a", encoding="utf-8") as handle:
            handle.write(key + "\n")
    except OSError as exc:
        print(f"pre-push: warning: could not record the verified tree: {exc}", file=sys.stderr)


def verify_outgoing_sha(sha: str) -> bool:
    """Run the commit's declared gate from its exact tree; False when the tree was already verified."""
    resolved = _git("rev-parse", "--verify", f"{sha}^{{commit}}")
    if resolved.returncode:
        detail = resolved.stderr.strip() or f"git rev-parse returned {resolved.returncode}"
        raise PrePushError(f"cannot resolve outgoing commit {sha}: {detail}")
    commit_sha = resolved.stdout.strip()
    command = gate_command(commit_sha)
    key = memo_key(commit_sha, command)
    if _already_verified(key):
        print(f"pre-push: tree of {commit_sha} already verified in this clone; skipping")
        return False

    with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-") as directory:
        worktree = Path(directory) / "candidate"
        added = _git("worktree", "add", "--quiet", "--detach", str(worktree), commit_sha)
        if added.returncode:
            detail = added.stderr.strip() or f"git worktree add returned {added.returncode}"
            raise PrePushError(f"cannot materialize outgoing commit {commit_sha}: {detail}")
        try:
            argv = _resolved_gate(command, commit_sha)
            if list(command) == list(DEFAULT_GATE) and not (worktree / DEFAULT_GATE[1]).is_file():
                raise PrePushError(
                    f"outgoing commit {commit_sha} does not contain {DEFAULT_GATE[1]}"
                )
            executable = argv[0]
            if "/" in executable or "\\" in executable:
                found = Path(executable).is_file() or (worktree / executable).is_file()
            else:
                found = shutil.which(executable) is not None
            if not found:
                raise PrePushError(f"gate command for {commit_sha} is not available: {executable}")
            print(f"pre-push: verifying outgoing commit {commit_sha}", flush=True)
            result = subprocess.run(argv, cwd=worktree, check=False)
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
    _remember(key)
    return True


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
        outgoing_shas = outgoing_commits(parse_outgoing_refs(sys.stdin))
        if not outgoing_shas:
            print("pre-push: no outgoing commits require verification")
            return 0
        verified = 0
        skipped = 0
        for sha in outgoing_shas:
            if verify_outgoing_sha(sha):
                verified += 1
            else:
                skipped += 1
        summary = f"pre-push: verified {verified} outgoing commit(s)"
        if skipped:
            summary += f", {skipped} already verified in this clone"
        print(summary)
        return 0
    except PrePushError as exc:
        print(f"pre-push: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
