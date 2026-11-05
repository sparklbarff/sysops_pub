#!/usr/bin/env python3
"""Preview, install, verify or remove this clone's mandatory local pre-push gate.

The gate needs the commands that pyproject.toml lists under [tool.sysops_pub.gate] as tools on
PATH; without a declaration it needs this repository's four, Black, Ruff, gitleaks and ShellCheck.

Installing points core.hooksPath at .githooks. That replaces whatever ran Git hooks before: another
core.hooksPath, or the active hooks in .git/hooks, which Git stops running once core.hooksPath is
set. So bootstrap detects both and refuses to take them over unless told to
(--replace-existing-hooks), records what it replaced in an install record inside .git, and
--uninstall puts that back exactly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_PATH = ".githooks"
PRE_PUSH = REPO_ROOT / HOOKS_PATH / "pre-push"
GATE_TABLE = ("tool", "sysops_pub", "gate")
DEFAULT_RELEASE_TOOLS = ("black", "ruff", "gitleaks", "shellcheck")
RECORD_NAME = "sysops-pub-bootstrap.json"


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


def _git_dir() -> Path:
    result = _git_config("rev-parse", "--git-common-dir")
    if result.returncode:
        raise BootstrapError("not inside a Git clone")
    directory = Path(result.stdout.strip())
    return directory if directory.is_absolute() else REPO_ROOT / directory


def current_hooks_path() -> str | None:
    result = _git_config("config", "--local", "--get", "core.hooksPath")
    return result.stdout.strip() or None if result.returncode == 0 else None


def inherited_hooks_path() -> tuple[str, str, str] | None:
    """(value, scope, origin) of a core.hooksPath this clone inherits rather than sets locally.

    Git uses the last value it reads, so a local value wins; but with none, a global, system or
    command-line value is what runs the hooks today, and setting a local one silently overrides
    the owner's binding. None when no hooks path is in force or the one in force is local.
    """
    result = _git_config("config", "--show-scope", "--show-origin", "--get", "core.hooksPath")
    if result.returncode or not result.stdout.strip():
        return None
    scope, origin, value = result.stdout.rstrip("\n").split("\t", 2)
    if scope == "local":
        return None
    return value, scope, origin


def active_default_hooks() -> list[str]:
    """Hooks in .git/hooks that Git runs today: not samples, and executable where that applies."""
    hooks = _git_dir() / "hooks"
    if not hooks.is_dir():
        return []
    return sorted(
        path.name
        for path in hooks.iterdir()
        if path.is_file()
        and not path.name.endswith(".sample")
        and (os.name == "nt" or os.access(path, os.X_OK))
    )


def _record_path() -> Path:
    return _git_dir() / RECORD_NAME


def verify() -> None:
    actual = current_hooks_path()
    if actual != HOOKS_PATH:
        raise BootstrapError(
            f"core.hooksPath must be {HOOKS_PATH!r}; current local value is {actual or 'unset'!r}"
        )
    if not PRE_PUSH.is_file():
        raise BootstrapError(f"tracked pre-push hook is missing: {PRE_PUSH}")
    if os.name != "nt" and not os.access(PRE_PUSH, os.X_OK):
        raise BootstrapError(f"tracked pre-push hook is not executable: {PRE_PUSH}")
    missing = _missing_release_tools()
    if missing:
        raise BootstrapError("mandatory release tool(s) are unavailable: " + ", ".join(missing))


def existing_binding() -> str | None:
    """What runs this clone's Git hooks today, if anything installing would take over."""
    previous = current_hooks_path()
    if previous:
        return f"core.hooksPath {previous!r}"
    inherited = inherited_hooks_path()
    if inherited and inherited[0] != HOOKS_PATH:
        value, scope, origin = inherited
        return f"core.hooksPath {value!r}, inherited from {scope} configuration ({origin})"
    if not inherited:
        active = active_default_hooks()
        if active:
            return f"the active hook(s) in .git/hooks ({', '.join(active)})"
    return None


def install(replace: bool) -> None:
    previous, active = current_hooks_path(), active_default_hooks()
    if previous == HOOKS_PATH:
        verify()
        print("bootstrap: already installed; verified")
        return
    owned = existing_binding()
    if owned and not replace:
        raise BootstrapError(
            f"this clone's Git hooks already run through {owned}; installing would stop them. "
            "Wire .githooks/pre-push into that setup yourself, or re-run with "
            "--replace-existing-hooks to take over (--uninstall restores it)."
        )
    record = {
        "installed_at": datetime.now(UTC).isoformat(),
        "installed_hooks_path": HOOKS_PATH,
        "pre_push_sha256": hashlib.sha256(PRE_PUSH.read_bytes()).hexdigest(),
        "previous_hooks_path": previous,
        "previous_active_hooks": active,
        # Not ours to restore: removing the local value lets it apply again.
        "previous_inherited_hooks_path": inherited_hooks_path() if not previous else None,
    }
    record_path = _record_path()
    temporary = record_path.with_name(f".{RECORD_NAME}.{os.getpid()}")
    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, record_path)
    result = _git_config("config", "--local", "core.hooksPath", HOOKS_PATH)
    if result.returncode:
        record_path.unlink(missing_ok=True)
        detail = result.stderr.strip() or f"git config returned {result.returncode}"
        raise BootstrapError(detail)
    verify()


def uninstall() -> None:
    """Put back exactly what the install record says was there before."""
    record_path = _record_path()
    if not record_path.is_file():
        raise BootstrapError(f"no install record at {record_path}; nothing of ours to remove")
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BootstrapError(f"install record is unreadable: {exc}") from exc
    if current_hooks_path() != record.get("installed_hooks_path"):
        raise BootstrapError(
            f"core.hooksPath is now {current_hooks_path() or 'unset'!r}, not what bootstrap "
            "installed; someone else changed it since, so it is left alone"
        )
    previous = record.get("previous_hooks_path")
    args = ("core.hooksPath", previous) if previous else ("--unset", "core.hooksPath")
    result = _git_config("config", "--local", *args)
    if result.returncode:
        raise BootstrapError(result.stderr.strip() or "git config failed")
    record_path.unlink()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="Install and verify the local gate")
    mode.add_argument("--check", action="store_true", help="Verify the local gate without writing")
    mode.add_argument(
        "--uninstall", action="store_true", help="Restore the hook setup bootstrap replaced"
    )
    parser.add_argument(
        "--replace-existing-hooks",
        action="store_true",
        help="Take over from an existing core.hooksPath or active .git/hooks (recorded)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.check:
            verify()
            print("bootstrap: mandatory local pre-push gate is wired")
            return 0
        if args.uninstall:
            uninstall()
            print("bootstrap: removed; the previous hook setup is restored")
            return 0
        if not PRE_PUSH.is_file():
            raise BootstrapError(f"tracked pre-push hook is missing: {PRE_PUSH}")
        missing = _missing_release_tools()
        if missing:
            print("MISSING mandatory release tool(s): " + ", ".join(missing))
        else:
            print("READY mandatory release tools: " + (", ".join(release_tools()) or "none"))
        existing = existing_binding() if current_hooks_path() != HOOKS_PATH else None
        if existing:
            print(
                f"CONFLICT this clone's hooks run through {existing}; installing needs "
                "--replace-existing-hooks, and --uninstall restores it"
            )
        print(f"WOULD SET git config --local core.hooksPath {HOOKS_PATH}")
        if not args.execute:
            print("dry-run only: pass --execute to install the local gate")
            return 0
        if missing:
            raise BootstrapError(
                "install the mandatory release tools before executing bootstrap: "
                + ", ".join(missing)
            )
        install(args.replace_existing_hooks)
        print("bootstrap: mandatory local pre-push gate installed and verified")
        return 0
    except BootstrapError as exc:
        print(f"bootstrap: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
