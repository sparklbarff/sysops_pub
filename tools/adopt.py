#!/usr/bin/env python3
"""Preview or build a reviewable Claude Code and Codex starter bundle."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class AdoptionError(RuntimeError):
    """Unsafe or incomplete adoption request."""


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _safe_target(raw: str) -> Path:
    target = Path(raw).expanduser().resolve()
    if target == Path(target.anchor) or target in {Path.home().resolve(), Path.cwd().resolve()}:
        raise AdoptionError(f"refusing unsafe bundle target: {target}")
    if _is_within(target, REPO_ROOT):
        raise AdoptionError("bundle target must be outside this repository")
    if _is_within(REPO_ROOT, target):
        raise AdoptionError("bundle target may not contain this repository")
    return target


def _sources(tool: str, platform: str) -> list[tuple[Path, Path]]:
    selected: list[tuple[Path, Path]] = []
    if tool in {"claude-code", "both"}:
        settings_name = (
            "settings.windows.json.example"
            if platform == "windows"
            else "settings.posix.json.example"
        )
        selected.extend(
            [
                (
                    REPO_ROOT / "examples" / "claude-code" / "CLAUDE.md.example",
                    Path("claude-code/CLAUDE.md"),
                ),
                (
                    REPO_ROOT / "examples" / "claude-code" / "PLAYWRIGHT.md.example",
                    Path("claude-code/PLAYWRIGHT.md"),
                ),
                (
                    REPO_ROOT / "examples" / "enforcement" / "scope_guard.py",
                    Path("claude-code/.agent-tools/scope_guard.py"),
                ),
                (
                    REPO_ROOT / "examples" / "claude-code" / settings_name,
                    Path("claude-code/.claude/settings.json"),
                ),
            ]
        )
    if tool in {"codex", "both"}:
        selected.extend(
            [
                (
                    REPO_ROOT / "examples" / "codex" / "AGENTS.md.example",
                    Path("codex/AGENTS.md"),
                ),
                (
                    REPO_ROOT / "examples" / "codex" / "config.toml.example",
                    Path("codex/config.toml.example"),
                ),
                (
                    REPO_ROOT / "examples" / "codex" / "config.sequential.toml.example",
                    Path("codex/config.sequential.toml.example"),
                ),
                (
                    REPO_ROOT / "examples" / "codex" / "review.config.toml.example",
                    Path("codex/review.config.toml.example"),
                ),
            ]
        )
    return selected


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_bundle(target: Path, sources: list[tuple[Path, Path]]) -> None:
    if target.exists():
        raise AdoptionError(f"execution requires a new target path: {target}")
    if not target.parent.is_dir():
        raise AdoptionError(f"target parent directory does not exist: {target.parent}")
    with tempfile.TemporaryDirectory(prefix=f".{target.name}-", dir=target.parent) as directory:
        staging = Path(directory)
        for source, relative in sources:
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)

        expected_paths = {relative for _source, relative in sources}
        actual_paths = {
            candidate.relative_to(staging)
            for candidate in staging.rglob("*")
            if candidate.is_file()
        }
        if actual_paths != expected_paths:
            raise AdoptionError("staged bundle file set does not match the declared sources")
        for source, relative in sources:
            if _sha256(source) != _sha256(staging / relative):
                raise AdoptionError(f"staged bundle hash mismatch: {relative}")
        staging.replace(target)


SETTINGS_REL = Path(".claude/settings.json")


def _safe_install_target(raw: str) -> Path:
    target = Path(raw).expanduser().resolve()
    if target == Path(target.anchor) or target in {Path.home().resolve(), Path.cwd().resolve()}:
        raise AdoptionError(f"refusing unsafe install target: {target}")
    if _is_within(target, REPO_ROOT) or _is_within(REPO_ROOT, target):
        raise AdoptionError("install target must be separate from this repository")
    if not target.is_dir() or target.is_symlink():
        raise AdoptionError(f"install target must be an existing directory: {target}")
    return target


def _install_targets(tool: str, platform: str) -> list[tuple[Path, Path]]:
    """(source, project-relative destination) for the files that belong IN a project.

    Distinct from _sources, which lays out a review bundle. These map each file to where it actually
    lives in an adopting project. CODEX_HOME-level config examples are intentionally excluded here;
    they are not project files. The .claude/settings.json entry is merged, not copied.
    """
    examples = REPO_ROOT / "examples"
    selected: list[tuple[Path, Path]] = []
    if tool in {"claude-code", "both"}:
        settings_name = (
            "settings.windows.json.example"
            if platform == "windows"
            else "settings.posix.json.example"
        )
        selected.extend(
            [
                (examples / "claude-code" / "CLAUDE.md.example", Path("CLAUDE.md")),
                (examples / "claude-code" / "PLAYWRIGHT.md.example", Path("PLAYWRIGHT.md")),
                (examples / "enforcement" / "scope_guard.py", Path(".agent-tools/scope_guard.py")),
                (examples / "claude-code" / settings_name, SETTINGS_REL),
            ]
        )
    if tool in {"codex", "both"}:
        selected.append((examples / "codex" / "AGENTS.md.example", Path("AGENTS.md")))
    return selected


def _merge_settings(existing: dict, addition: dict) -> tuple[dict, bool]:
    """Additively merge the reference settings into an existing settings.json; never remove a key.

    Unions `permissions.<key>` lists, appends a `hooks.<event>` entry only when an identical one is
    absent, and adds any other top-level key only when missing. Returns (merged, changed); a second
    merge of the same addition reports changed=False, so the installer is idempotent.
    """
    merged = copy.deepcopy(existing)
    changed = False
    for key, values in addition.get("permissions", {}).items():
        permissions = merged.setdefault("permissions", {})
        if isinstance(values, list):
            current = permissions.setdefault(key, [])
            for value in values:
                if value not in current:
                    current.append(value)
                    changed = True
        elif key not in permissions:
            permissions[key] = values
            changed = True
    for event, entries in addition.get("hooks", {}).items():
        current_hooks = merged.setdefault("hooks", {}).setdefault(event, [])
        for entry in entries:
            if entry not in current_hooks:
                current_hooks.append(entry)
                changed = True
    for key, value in addition.items():
        if key not in ("permissions", "hooks") and key not in merged:
            merged[key] = value
            changed = True
    return merged, changed


def _install_into(project: Path, tool: str, platform: str, execute: bool) -> int:
    targets = _install_targets(tool, platform)
    missing = [str(s) for s, _ in targets if not s.is_file() or s.is_symlink()]
    if missing:
        raise AdoptionError("missing or unsafe source file(s): " + ", ".join(missing))

    placements = [(s, r) for s, r in targets if r != SETTINGS_REL]
    settings_source = next((s for s, r in targets if r == SETTINGS_REL), None)

    actions: list[tuple[str, Path]] = []
    for source, rel in placements:
        destination = project / rel
        if destination.is_symlink():
            raise AdoptionError(f"refusing to touch a symlink: {destination}")
        if not destination.exists():
            actions.append(("place", rel))
        elif destination.is_file() and _sha256(destination) == _sha256(source):
            actions.append(("present-identical", rel))
        else:
            actions.append(("present-differs-skip", rel))

    settings_action: str | None = None
    if settings_source is not None:
        settings_dest = project / SETTINGS_REL
        if settings_dest.is_symlink():
            raise AdoptionError(f"refusing to touch a symlink: {settings_dest}")
        addition = json.loads(settings_source.read_text(encoding="utf-8"))
        if settings_dest.exists():
            existing = json.loads(settings_dest.read_text(encoding="utf-8"))
            _, changed = _merge_settings(existing, addition)
            settings_action = "merge" if changed else "merge-noop"
        else:
            settings_action = "place"

    for action, rel in actions:
        print(f"{'WOULD ' if not execute else ''}{action.upper():20} {rel}")
    if settings_action is not None:
        print(
            f"{'WOULD ' if not execute else ''}{('settings-' + settings_action).upper():20} {SETTINGS_REL}"
        )
    if not execute:
        print(
            "dry-run only: pass --execute to apply. Existing files are never overwritten; "
            "only .claude/settings.json is merged, after a backup."
        )
        return 0

    for action, rel in actions:
        if action != "place":
            continue
        source = next(s for s, r in placements if r == rel)
        destination = project / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        print(f"PLACED {rel}")
    if settings_source is not None:
        settings_dest = project / SETTINGS_REL
        addition = json.loads(settings_source.read_text(encoding="utf-8"))
        if settings_dest.exists():
            existing = json.loads(settings_dest.read_text(encoding="utf-8"))
            merged, changed = _merge_settings(existing, addition)
            if changed:
                backup = settings_dest.with_name(settings_dest.name + ".sysops-pub.bak")
                if not backup.exists():
                    shutil.copyfile(settings_dest, backup)
                settings_dest.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
                print(f"MERGED {SETTINGS_REL} (backup {backup.name})")
            else:
                print(f"UNCHANGED {SETTINGS_REL}")
        else:
            settings_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(settings_source, settings_dest)
            print(f"PLACED {SETTINGS_REL}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--target", help="build a reviewable bundle at a NEW path outside this repo")
    where.add_argument("--into", help="install into an EXISTING project (merges settings.json)")
    parser.add_argument(
        "--tool",
        choices=("both", "claude-code", "codex"),
        default="both",
        help="which starters to produce (default: both)",
    )
    parser.add_argument(
        "--platform",
        choices=("auto", "posix", "windows"),
        default="auto",
        help="hook command flavour for the Claude Code settings (default: auto, from this host)",
    )
    parser.add_argument(
        "--execute", action="store_true", help="write; without it, adopt only previews"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        platform = (
            ("windows" if os.name == "nt" else "posix")
            if args.platform == "auto"
            else args.platform
        )
        if args.into is not None:
            return _install_into(_safe_install_target(args.into), args.tool, platform, args.execute)
        target = _safe_target(args.target)
        sources = _sources(args.tool, platform)
        if not sources:
            raise AdoptionError("no adoption files were selected")
        missing = [
            str(source)
            for source, _destination in sources
            if not source.is_file() or source.is_symlink()
        ]
        if missing:
            raise AdoptionError("missing or unsafe source file(s): " + ", ".join(missing))

        for source, relative in sources:
            print(f"{'COPY' if args.execute else 'WOULD COPY':10} {relative}")
        if not args.execute:
            print("dry-run only: pass --execute to build the bundle")
        else:
            _build_bundle(target, sources)
            print(f"bundle created and hash-verified: {target}")
        return 0
    except (AdoptionError, OSError, ValueError) as exc:
        print(f"adopt: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
