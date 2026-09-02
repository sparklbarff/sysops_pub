#!/usr/bin/env python3
"""Run the complete local-only release verification suite."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OPTIONAL_TOOLS = ("black", "ruff", "gitleaks", "shellcheck")
HOOKS_PATH = ".githooks"


def _run(label: str, command: list[str]) -> bool:
    print(f"\ncheck: {label}", flush=True)
    result = subprocess.run(command, cwd=REPO_ROOT, check=False)
    if result.returncode:
        print(f"FAIL: {label} returned {result.returncode}", file=sys.stderr)
        return False
    print(f"PASS: {label}")
    return True


def _validate_data_files() -> bool:
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "--cached", "-z"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
        ).stdout.split(b"\0")
        paths = [REPO_ROOT / Path(raw.decode("utf-8")) for raw in tracked if raw]
        json_paths = sorted(
            path
            for path in paths
            if path.name.endswith(".json") or path.name.endswith(".json.example")
        )
        toml_paths = sorted(
            path
            for path in paths
            if path.name.endswith(".toml") or path.name.endswith(".toml.example")
        )
        for path in json_paths:
            json.loads(path.read_text(encoding="utf-8"))
        for path in toml_paths:
            tomllib.loads(path.read_text(encoding="utf-8"))
    except (
        OSError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
        tomllib.TOMLDecodeError,
    ) as exc:
        print(f"FAIL: configuration syntax: {exc}", file=sys.stderr)
        return False
    print(f"PASS: configuration syntax ({len(json_paths)} JSON, {len(toml_paths)} TOML)")
    return True


def _generated_paths_absent() -> bool:
    offenders = []
    for name in ("demo-output", "reports"):
        path = REPO_ROOT / name
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            offenders.append(name)
    if offenders:
        print(
            "FAIL: generated directories are non-empty: " + ", ".join(offenders),
            file=sys.stderr,
        )
        return False
    print("PASS: generated output directories are absent or empty")
    return True


def _no_untracked_files() -> bool:
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        print("FAIL: could not enumerate untracked files", file=sys.stderr)
        return False
    untracked = [line for line in result.stdout.splitlines() if line]
    if untracked:
        print("FAIL: untracked files are outside the release candidate:", file=sys.stderr)
        for path in untracked:
            print(f"  {path}", file=sys.stderr)
        return False
    print("PASS: no untracked files")
    return True


def _verify_hook_wiring() -> bool:
    result = subprocess.run(
        [sys.executable, "tools/bootstrap.py", "--check"],
        cwd=REPO_ROOT,
        check=False,
    )
    if result.returncode:
        print("FAIL: mandatory local pre-push gate is not wired", file=sys.stderr)
        return False
    hook = REPO_ROOT / HOOKS_PATH / "pre-push"
    if os.name != "nt" and not os.access(hook, os.X_OK):
        print("FAIL: mandatory local pre-push hook is not executable", file=sys.stderr)
        return False
    print("PASS: mandatory local pre-push gate is wired")
    return True


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-tools",
        action="store_true",
        help="Fail when Black, Ruff, gitleaks, or ShellCheck is unavailable",
    )
    parser.add_argument(
        "--candidate-sha",
        help="Require the checked-out HEAD to match this outgoing commit SHA",
    )
    return parser


def _verify_candidate_sha(candidate_sha: str | None) -> bool:
    if candidate_sha is None:
        return True
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    actual = result.stdout.strip()
    if result.returncode or actual != candidate_sha:
        detail = actual or "unavailable"
        print(
            f"FAIL: candidate identity: expected {candidate_sha}, checked out {detail}",
            file=sys.stderr,
        )
        return False
    print(f"PASS: candidate identity ({candidate_sha})")
    return True


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if sys.version_info < (3, 11):
        print("release verification requires Python 3.11 or newer", file=sys.stderr)
        return 2

    passed = True
    passed &= _verify_candidate_sha(args.candidate_sha)
    passed &= _verify_hook_wiring()
    passed &= _run("dependency-free suite", [sys.executable, "tools/test.py"])
    passed &= _run("case exercises", [sys.executable, "tools/case_exercises.py", "all"])
    passed &= _validate_data_files()
    passed &= _generated_paths_absent()
    passed &= _run("no unstaged tracked changes", ["git", "diff", "--quiet"])
    passed &= _no_untracked_files()
    passed &= _run("working-tree whitespace", ["git", "diff", "--check"])
    passed &= _run("staged whitespace", ["git", "diff", "--cached", "--check"])

    shell_scripts = [str(path) for path in sorted((REPO_ROOT / "scripts").glob("*.sh"))]
    shell_scripts.append(str(REPO_ROOT / ".githooks" / "pre-push"))
    tool_commands = {
        "black": ["black", "--check", "."],
        "ruff": ["ruff", "check", "--no-cache", "."],
        "shellcheck": ["shellcheck", *shell_scripts],
    }
    for tool in OPTIONAL_TOOLS:
        if shutil.which(tool):
            if tool == "gitleaks":
                passed &= _run(
                    "gitleaks current tree",
                    ["gitleaks", "dir", ".", "--no-banner", "--redact"],
                )
                passed &= _run(
                    "gitleaks Git history",
                    ["gitleaks", "git", ".", "--no-banner", "--redact"],
                )
            else:
                passed &= _run(tool, tool_commands[tool])
        elif args.require_tools:
            print(f"FAIL: required release tool is unavailable: {tool}", file=sys.stderr)
            passed = False
        else:
            print(f"SKIP: optional release tool is unavailable: {tool}")

    if passed:
        print("\nrelease verification: pass")
        print("manual step: review the complete outgoing commit range before pushing")
        return 0
    print("\nrelease verification: fail", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
