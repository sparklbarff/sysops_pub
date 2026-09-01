#!/usr/bin/env python3
"""Preview, install, or verify this clone's mandatory local pre-push gate."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_PATH = ".githooks"
PRE_PUSH = REPO_ROOT / HOOKS_PATH / "pre-push"


class BootstrapError(RuntimeError):
    """The local gate could not be established or verified."""


def _git_config(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def verify() -> None:
    result = _git_config("config", "--local", "--get", "core.hooksPath")
    if result.returncode or result.stdout.strip() != HOOKS_PATH:
        actual = result.stdout.strip() or "unset"
        raise BootstrapError(
            f"core.hooksPath must be {HOOKS_PATH!r}; current local value is {actual!r}"
        )
    if not PRE_PUSH.is_file():
        raise BootstrapError(f"tracked pre-push hook is missing: {PRE_PUSH}")
    if os.name != "nt" and not os.access(PRE_PUSH, os.X_OK):
        raise BootstrapError(f"tracked pre-push hook is not executable: {PRE_PUSH}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="Install and verify the local gate")
    mode.add_argument("--check", action="store_true", help="Verify the local gate without writing")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if sys.version_info < (3, 11):
        print("bootstrap: Python 3.11 or newer is required", file=sys.stderr)
        return 2
    try:
        if args.check:
            verify()
            print("bootstrap: mandatory local pre-push gate is wired")
            return 0
        if not PRE_PUSH.is_file():
            raise BootstrapError(f"tracked pre-push hook is missing: {PRE_PUSH}")
        print(f"WOULD SET git config --local core.hooksPath {HOOKS_PATH}")
        if not args.execute:
            print("dry-run only: pass --execute to install the local gate")
            return 0
        result = _git_config("config", "--local", "core.hooksPath", HOOKS_PATH)
        if result.returncode:
            detail = result.stderr.strip() or f"git config returned {result.returncode}"
            raise BootstrapError(detail)
        verify()
        print("bootstrap: mandatory local pre-push gate installed and verified")
        return 0
    except BootstrapError as exc:
        print(f"bootstrap: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
