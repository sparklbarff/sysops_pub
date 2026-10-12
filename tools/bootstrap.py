#!/usr/bin/env python3
"""Preview, install, or verify this clone's mandatory local pre-push gate.

The gate needs the commands that pyproject.toml lists under [tool.sysops_pub.gate] as tools on
PATH; without a declaration it needs this repository's four, Black, Ruff, gitleaks and ShellCheck.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_PATH = ".githooks"
PRE_PUSH = REPO_ROOT / HOOKS_PATH / "pre-push"
GATE_TABLE = ("tool", "sysops_pub", "gate")
DEFAULT_RELEASE_TOOLS = ("black", "ruff", "gitleaks", "shellcheck")


class BootstrapError(RuntimeError):
    """The local gate could not be established or verified."""


def release_tools() -> tuple[str, ...]:
    """The commands the declared gate needs on PATH, or this repository's four."""
    pyproject = REPO_ROOT / "pyproject.toml"
    if not pyproject.is_file():
        return DEFAULT_RELEASE_TOOLS
    try:
        data: object = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BootstrapError(f"pyproject.toml is unreadable: {exc}") from exc
    table = data
    for key in GATE_TABLE:
        table = table.get(key) if isinstance(table, dict) else None
    tools = table.get("tools") if isinstance(table, dict) else None
    if tools is None:
        return DEFAULT_RELEASE_TOOLS
    if not isinstance(tools, list) or not all(isinstance(tool, str) and tool for tool in tools):
        raise BootstrapError("[tool.sysops_pub.gate] tools must be a list of command names")
    return tuple(tools)


def _missing_release_tools() -> list[str]:
    return [tool for tool in release_tools() if shutil.which(tool) is None]


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
    missing = _missing_release_tools()
    if missing:
        raise BootstrapError("mandatory release tool(s) are unavailable: " + ", ".join(missing))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="Install and verify the local gate")
    mode.add_argument("--check", action="store_true", help="Verify the local gate without writing")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.check:
            verify()
            print("bootstrap: mandatory local pre-push gate is wired")
            return 0
        if not PRE_PUSH.is_file():
            raise BootstrapError(f"tracked pre-push hook is missing: {PRE_PUSH}")
        missing = _missing_release_tools()
        if missing:
            print("MISSING mandatory release tool(s): " + ", ".join(missing))
        else:
            print("READY mandatory release tools: " + (", ".join(release_tools()) or "none"))
        print(f"WOULD SET git config --local core.hooksPath {HOOKS_PATH}")
        if not args.execute:
            print("dry-run only: pass --execute to install the local gate")
            return 0
        if missing:
            raise BootstrapError(
                "install the mandatory release tools before executing bootstrap: "
                + ", ".join(missing)
            )
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
