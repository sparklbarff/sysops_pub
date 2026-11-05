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
                    REPO_ROOT / "examples" / "enforcement" / "command_guard.py",
                    Path("claude-code/.agent-tools/command_guard.py"),
                ),
                (
                    REPO_ROOT / "examples" / "enforcement" / "read_guard.py",
                    Path("claude-code/.agent-tools/read_guard.py"),
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
                (
                    REPO_ROOT / "examples" / "codex" / "hooks.json.example",
                    Path("codex/.codex/hooks.json"),
                ),
                (
                    REPO_ROOT / "examples" / "enforcement" / "scope_guard.py",
                    Path("codex/.agent-tools/scope_guard.py"),
                ),
                (
                    REPO_ROOT / "examples" / "enforcement" / "command_guard.py",
                    Path("codex/.agent-tools/command_guard.py"),
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
                raise AdoptionError(f"staged bundle hash mismatch: {relative.as_posix()}")
        staging.replace(target)


SETTINGS_REL = Path(".claude/settings.json")
# The adoption record (repair handoff 2026-11-03, Stage 5): what this tool placed, with hashes, so
# drift can be detected and an update or uninstall touches only files that are still ours.
RECORD_REL = Path(".sysops-pub/adoption.json")
# Files the installed hooks execute. A different file already at one of these paths is a conflict,
# not a skip: the hooks would run someone else's code under this tool's name.
WIRED = (".agent-tools/", ".codex/hooks.json")


def _source_commit() -> str:
    import subprocess

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() or "unknown"


def _atomic_write(destination: Path, data: bytes) -> None:
    """A private, unpredictable temporary file beside the destination, then a rename: never a
    shared, guessable path that could be a planted symlink."""
    handle, temporary = tempfile.mkstemp(dir=destination.parent, prefix=f".{destination.name}.")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(temporary, destination)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _read_record(project: Path) -> dict:
    path = _project_destination(project, RECORD_REL)
    if not path.exists():
        return {}
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AdoptionError(f"adoption record is unreadable: {path}: {exc}") from exc
    if not isinstance(record, dict):
        raise AdoptionError(f"adoption record is not an object: {path}")
    return record


def _write_record(project: Path, record: dict) -> None:
    path = _project_destination(project, RECORD_REL)
    path.parent.mkdir(parents=True, exist_ok=True)
    _project_destination(project, RECORD_REL)
    _atomic_write(path, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode())


def _safe_install_target(raw: str) -> Path:
    unresolved = Path(raw).expanduser()
    if unresolved.is_symlink():
        raise AdoptionError(f"refusing symlink install target: {unresolved}")
    target = unresolved.resolve()
    if target == Path(target.anchor) or target in {Path.home().resolve(), Path.cwd().resolve()}:
        raise AdoptionError(f"refusing unsafe install target: {target}")
    if _is_within(target, REPO_ROOT) or _is_within(REPO_ROOT, target):
        raise AdoptionError("install target must be separate from this repository")
    if not target.is_dir() or target.is_symlink():
        raise AdoptionError(f"install target must be an existing directory: {target}")
    return target


def _project_destination(project: Path, relative: Path) -> Path:
    destination = project / relative
    current = destination
    while current != project:
        if current.is_symlink():
            raise AdoptionError(f"refusing symlink in project destination: {current}")
        current = current.parent
    if not _is_within(destination.resolve(), project):
        raise AdoptionError(f"destination escapes project: {destination}")
    return destination


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
                (
                    examples / "enforcement" / "command_guard.py",
                    Path(".agent-tools/command_guard.py"),
                ),
                (examples / "enforcement" / "read_guard.py", Path(".agent-tools/read_guard.py")),
                (examples / "claude-code" / settings_name, SETTINGS_REL),
            ]
        )
    if tool in {"codex", "both"}:
        selected.extend(
            [
                (examples / "codex" / "AGENTS.md.example", Path("AGENTS.md")),
                (examples / "codex" / "hooks.json.example", Path(".codex/hooks.json")),
                (
                    examples / "enforcement" / "scope_guard.py",
                    Path(".agent-tools/scope_guard.py"),
                ),
                (
                    examples / "enforcement" / "command_guard.py",
                    Path(".agent-tools/command_guard.py"),
                ),
            ]
        )
    # Both tools share the guards; place each project path once, in first-seen order.
    unique: dict[Path, Path] = {}
    for source, relative in selected:
        unique.setdefault(relative, source)
    return [(source, relative) for relative, source in unique.items()]


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

    record = _read_record(project)
    owned: dict[str, str] = dict(record.get("files") or {})
    # Helpers the installed hooks run that were already here, identical, before adoption: the
    # policy depends on them, so their integrity is recorded and checked, but they are the
    # owner's, so nothing here ever updates or removes them.
    preexisting: dict[str, str] = dict(record.get("preexisting") or {})
    actions: list[tuple[str, Path]] = []
    for source, rel in placements:
        destination = _project_destination(project, rel)
        if destination.is_symlink():
            raise AdoptionError(f"refusing to touch a symlink: {destination}")
        if not destination.exists():
            actions.append(("place", rel))
        elif destination.is_file() and _sha256(destination) == _sha256(source):
            actions.append(("present-identical", rel))
            if rel.as_posix() not in owned and rel.as_posix().startswith(WIRED):
                preexisting[rel.as_posix()] = _sha256(destination)
        elif destination.is_file() and owned.get(rel.as_posix()) == _sha256(destination):
            # Placed by an earlier adoption and unchanged since: ours to update.
            actions.append(("update", rel))
        elif rel.as_posix().startswith(WIRED):
            actions.append(("conflict", rel))
        else:
            actions.append(("present-differs-skip", rel))
    conflicts = [rel for action, rel in actions if action == "conflict"]

    settings_action: str | None = None
    if settings_source is not None:
        settings_dest = _project_destination(project, SETTINGS_REL)
        _project_destination(project, SETTINGS_REL.with_name("settings.json.sysops-pub.bak"))
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
        print(f"{'WOULD ' if not execute else ''}{action.upper():20} {rel.as_posix()}")
    if settings_action is not None:
        print(
            f"{'WOULD ' if not execute else ''}{('settings-' + settings_action).upper():20} {SETTINGS_REL.as_posix()}"
        )
    if conflicts:
        message = (
            "a different file already sits where the installed hooks would run this tool's "
            "guard: "
            + ", ".join(rel.as_posix() for rel in conflicts)
            + ". Rename or merge it, then "
            "adopt again."
        )
        if execute:
            raise AdoptionError(message + " Nothing was written.")
        print(f"CONFLICT: {message}")
    if not execute:
        print(
            "dry-run only: pass --execute to apply. Existing files are never overwritten (files "
            "an earlier adoption placed and nobody changed since are updated); only "
            ".claude/settings.json is merged, after a backup."
        )
        return 2 if conflicts else 0

    for action, rel in actions:
        if action not in ("place", "update"):
            continue
        source = next(s for s, r in placements if r == rel)
        destination = _project_destination(project, rel)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _project_destination(project, rel)
        _atomic_write(destination, source.read_bytes())
        owned[rel.as_posix()] = _sha256(destination)
        print(f"{'UPDATED' if action == 'update' else 'PLACED'} {rel.as_posix()}")
    # The settings record holds the original (as a backup, or "placed" when there was none) and
    # "sha256", the last state this tool actually wrote. Only a write updates it: a merge that
    # changes nothing writes nothing, so it cannot claim the user's edited file as ours. A merge
    # into a file someone edited after our last write carries their edit; from then on restoring
    # the original would erase it, so "restorable" goes false and uninstall keeps the file.
    settings_record = dict(record.get("settings") or {})
    if settings_source is not None:
        settings_dest = _project_destination(project, SETTINGS_REL)
        addition = json.loads(settings_source.read_text(encoding="utf-8"))
        last_written = settings_record.get("sha256")
        if settings_dest.exists():
            edited_since = bool(last_written) and _sha256(settings_dest) != last_written
            existing = json.loads(settings_dest.read_text(encoding="utf-8"))
            merged, changed = _merge_settings(existing, addition)
            if changed:
                backup = settings_dest.with_name(settings_dest.name + ".sysops-pub.bak")
                _project_destination(project, backup.relative_to(project))
                if not last_written and not backup.exists():
                    shutil.copyfile(settings_dest, backup)
                    settings_record.setdefault("backup", backup.name)
                if edited_since:
                    settings_record["restorable"] = False
                _atomic_write(settings_dest, (json.dumps(merged, indent=2) + "\n").encode())
                settings_record["sha256"] = _sha256(settings_dest)
                print(f"MERGED {SETTINGS_REL.as_posix()} (backup {backup.name})")
            else:
                note = " (edited since adoption; left as it is)" if edited_since else ""
                print(f"UNCHANGED {SETTINGS_REL.as_posix()}{note}")
        else:
            settings_dest.parent.mkdir(parents=True, exist_ok=True)
            _project_destination(project, SETTINGS_REL)
            _atomic_write(settings_dest, settings_source.read_bytes())
            if not last_written:
                settings_record["placed"] = True
            settings_record["sha256"] = _sha256(settings_dest)
            print(f"PLACED {SETTINGS_REL.as_posix()}")
    record.update(
        source_commit=_source_commit(),
        tool=tool,
        platform=platform,
        files=owned,
        preexisting=preexisting,
        settings=settings_record,
        skipped=[rel.as_posix() for action, rel in actions if action == "present-differs-skip"],
    )
    _write_record(project, record)
    print(f"RECORDED {RECORD_REL.as_posix()}")
    return 0


def _check(project: Path) -> int:
    """Drift since adoption: each recorded file and the settings against their recorded hashes."""
    record = _read_record(project)
    if not record:
        raise AdoptionError(f"no adoption record at {project / RECORD_REL}")
    drift = 0
    for rel, digest in sorted((record.get("files") or {}).items()):
        path = _project_destination(project, Path(rel))
        state = "MISSING" if not path.exists() else "OK" if _sha256(path) == digest else "DRIFTED"
        drift += state != "OK"
        print(f"{state:8} {rel}")
    for rel, digest in sorted((record.get("preexisting") or {}).items()):
        path = _project_destination(project, Path(rel))
        state = "MISSING" if not path.exists() else "OK" if _sha256(path) == digest else "DRIFTED"
        drift += state != "OK"
        print(f"{state:8} {rel} (was here before adoption; the hooks run it)")
    settings = record.get("settings") or {}
    if settings.get("sha256"):
        path = _project_destination(project, SETTINGS_REL)
        same = path.exists() and _sha256(path) == settings["sha256"]
        drift += not same
        print(f"{'OK' if same else 'DRIFTED':8} {SETTINGS_REL.as_posix()}")
    print(f"adopted from {record.get('source_commit', 'unknown')}; {drift} drifted")
    return 1 if drift else 0


def _uninstall(project: Path, execute: bool) -> int:
    """Remove only what adoption placed and nobody changed since; restore the settings backup only
    if the settings are still exactly what adoption wrote. Everything else is reported and kept."""
    record = _read_record(project)
    if not record:
        raise AdoptionError(f"no adoption record at {project / RECORD_REL}; nothing of ours")
    kept = 0
    prefix = "WOULD " if not execute else ""
    for rel, digest in sorted((record.get("files") or {}).items()):
        path = _project_destination(project, Path(rel))
        if not path.exists():
            continue
        if _sha256(path) != digest:
            kept += 1
            print(f"KEEP     {rel} (changed since adoption)")
            continue
        print(f"{prefix}REMOVE {rel}")
        if execute:
            path.unlink()
    for rel in sorted(record.get("preexisting") or {}):
        if _project_destination(project, Path(rel)).exists():
            print(f"KEEP     {rel} (was here before adoption)")
    settings = record.get("settings") or {}
    settings_path = _project_destination(project, SETTINGS_REL)
    if settings.get("sha256") and settings_path.exists():
        if _sha256(settings_path) != settings["sha256"]:
            kept += 1
            print(f"KEEP     {SETTINGS_REL.as_posix()} (changed since adoption)")
        elif settings.get("restorable") is False:
            kept += 1
            original = settings.get("backup")
            print(
                f"KEEP     {SETTINGS_REL.as_posix()} (holds edits made after adoption; "
                + (f"the original is in {original}" if original else "there was no original")
                + ")"
            )
        elif settings.get("placed"):
            print(f"{prefix}REMOVE {SETTINGS_REL.as_posix()}")
            if execute:
                settings_path.unlink()
        elif settings.get("backup"):
            backup = settings_path.with_name(settings["backup"])
            print(f"{prefix}RESTORE {SETTINGS_REL.as_posix()} from {backup.name}")
            if execute:
                os.replace(backup, settings_path)
    if execute:
        _project_destination(project, RECORD_REL).unlink()
    if not execute:
        print("dry-run only: pass --execute to remove")
    return 1 if kept else 0


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
    lifecycle = parser.add_mutually_exclusive_group()
    lifecycle.add_argument(
        "--check", action="store_true", help="with --into: report drift since adoption"
    )
    lifecycle.add_argument(
        "--uninstall",
        action="store_true",
        help="with --into: remove what adoption placed and nobody changed since",
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
        if (args.check or args.uninstall) and args.into is None:
            raise AdoptionError("--check and --uninstall work on a project: pass --into")
        if args.into is not None:
            project = _safe_install_target(args.into)
            if args.check:
                return _check(project)
            if args.uninstall:
                return _uninstall(project, args.execute)
            return _install_into(project, args.tool, platform, args.execute)
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
            print(f"{'COPY' if args.execute else 'WOULD COPY':10} {relative.as_posix()}")
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
