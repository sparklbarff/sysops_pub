#!/usr/bin/env python3
"""Portable desired-state control loop for the sysops_pub sandbox.

The controller manages only regular files declared by a registry and selected by a profile.
Mutation is restricted to a marked sandbox and requires an explicit --execute flag.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / "registry" / "components.json"
DEFAULT_PROFILE = REPO_ROOT / "profiles" / "demo.json"
MARKER_NAME = ".sysops_pub_sandbox"
MARKER_CONTENT = "sysops_pub sandbox v1\n"
SUPPORTED_PLATFORMS = {"any", "linux", "macos", "windows"}


class ControlError(RuntimeError):
    """Configuration or safety error suitable for a concise CLI message."""


@dataclass(frozen=True)
class ManagedFile:
    component: str
    source: Path
    destination: Path
    destination_root: Path
    relative_destination: str


@dataclass(frozen=True)
class FileState:
    component: str
    path: str
    status: str
    expected_sha256: str | None
    actual_sha256: str | None


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ControlError(f"could not read configuration {path}: {exc}") from exc
    except UnicodeError as exc:
        raise ControlError(f"configuration is not valid UTF-8: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ControlError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ControlError(f"top-level JSON value must be an object: {path}")
    return value


def _safe_relative(raw: str, label: str) -> Path:
    value = Path(raw)
    if value.is_absolute() or not value.parts or ".." in value.parts:
        raise ControlError(f"{label} must be a non-traversing relative path: {raw!r}")
    return value


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _current_platform() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "win32":
        return "windows"
    raise ControlError(f"unsupported host platform: {sys.platform}")


def _registry_components(registry_path: Path) -> dict[str, dict[str, Any]]:
    registry = _load_json(registry_path)
    if registry.get("schema_version") != 1:
        raise ControlError("registry schema_version must be 1")
    raw_components = registry.get("components")
    if not isinstance(raw_components, list):
        raise ControlError("registry components must be a list")

    components: dict[str, dict[str, Any]] = {}
    for entry in raw_components:
        if not isinstance(entry, dict):
            raise ControlError("each registry component must be an object")
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise ControlError("each registry component needs a non-empty name")
        if name in components:
            raise ControlError(f"duplicate registry component: {name}")
        platforms = entry.get("platforms")
        if (
            not isinstance(platforms, list)
            or not platforms
            or not all(isinstance(platform, str) for platform in platforms)
        ):
            raise ControlError(f"component platforms must be a non-empty string list: {name}")
        unknown_platforms = sorted(set(platforms) - SUPPORTED_PLATFORMS)
        if unknown_platforms:
            raise ControlError(
                f"component {name} names unsupported platform(s): " + ", ".join(unknown_platforms)
            )
        components[name] = entry
    return components


def _selected_names(
    profile_path: Path,
    components: dict[str, dict[str, Any]],
    requested: Sequence[str],
) -> list[str]:
    profile = _load_json(profile_path)
    if profile.get("schema_version") != 1:
        raise ControlError("profile schema_version must be 1")
    configured = profile.get("components")
    if not isinstance(configured, dict):
        raise ControlError("profile components must be an object")

    unknown = sorted(set(configured) - set(components))
    if unknown:
        raise ControlError(f"profile names unknown component(s): {', '.join(unknown)}")

    enabled: list[str] = []
    for name, settings in configured.items():
        if not isinstance(settings, dict):
            raise ControlError(f"profile component settings must be an object: {name}")
        unknown_settings = sorted(set(settings) - {"enabled"})
        if unknown_settings:
            raise ControlError(
                f"profile component {name} has unknown setting(s): " + ", ".join(unknown_settings)
            )
        is_enabled = settings.get("enabled")
        if not isinstance(is_enabled, bool):
            raise ControlError(f"profile component enabled must be a boolean: {name}")
        if is_enabled:
            enabled.append(name)
    if requested:
        missing = sorted(set(requested) - set(enabled))
        if missing:
            raise ControlError(
                "requested component(s) are absent or disabled in the profile: "
                + ", ".join(missing)
            )
        selected = list(dict.fromkeys(requested))
        if not selected:
            raise ControlError("at least one component must be selected")
        return selected
    if not enabled:
        raise ControlError("profile must enable at least one component")
    return enabled


def _check_no_symlink(path: Path, stop: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise ControlError(f"managed path may not traverse a symlink: {current}")
        if current == stop:
            return
        if current.parent == current:
            raise ControlError(f"path escaped safety root: {path}")
        current = current.parent


def _managed_files(
    target: Path,
    registry_path: Path,
    profile_path: Path,
    requested: Sequence[str],
) -> list[ManagedFile]:
    components = _registry_components(registry_path)
    names = _selected_names(profile_path, components, requested)
    managed: list[ManagedFile] = []
    destinations: set[Path] = set()
    destination_roots: dict[Path, str] = {}
    current_platform = _current_platform()

    for name in names:
        entry = components[name]
        platforms = entry["platforms"]
        if "any" not in platforms and current_platform not in platforms:
            raise ControlError(f"component {name} does not support platform {current_platform}")
        source_value = entry.get("source")
        destination_value = entry.get("destination")
        if not isinstance(source_value, str) or not source_value:
            raise ControlError(f"component source must be a non-empty string: {name}")
        if not isinstance(destination_value, str) or not destination_value:
            raise ControlError(f"component destination must be a non-empty string: {name}")
        source_rel = _safe_relative(source_value, f"{name}.source")
        destination_rel = _safe_relative(destination_value, f"{name}.destination")
        destination_root = target / destination_rel
        for existing_root, existing_name in destination_roots.items():
            if _is_within(destination_root, existing_root) or _is_within(
                existing_root, destination_root
            ):
                raise ControlError(
                    "enabled component destination roots overlap: "
                    f"{existing_name} ({existing_root}) and {name} ({destination_root})"
                )
        destination_roots[destination_root] = name
        declared_source_root = REPO_ROOT / source_rel
        _check_no_symlink(declared_source_root, REPO_ROOT)
        source_root = declared_source_root.resolve()
        if not _is_within(source_root, REPO_ROOT):
            raise ControlError(f"component source escapes repository: {name}")
        if not source_root.is_dir():
            raise ControlError(f"component source is not a directory: {source_root}")
        _check_no_symlink(source_root, REPO_ROOT)

        component_file_count = 0
        for source in sorted(source_root.rglob("*")):
            if source.is_symlink():
                raise ControlError(f"component source may not contain symlinks: {source}")
            if not source.is_file():
                continue
            component_file_count += 1
            relative = source.relative_to(source_root)
            destination = target / destination_rel / relative
            if destination in destinations:
                raise ControlError(f"two components manage the same destination: {destination}")
            destinations.add(destination)
            managed.append(
                ManagedFile(
                    component=name,
                    source=source,
                    destination=destination,
                    destination_root=destination_root,
                    relative_destination=str(destination.relative_to(target)),
                )
            )
        if component_file_count == 0:
            raise ControlError(f"enabled component has no managed files: {name}")
    return managed


def _states(files: Iterable[ManagedFile], target: Path) -> list[FileState]:
    states: list[FileState] = []
    for item in files:
        expected = _sha256(item.source)
        if item.destination.is_symlink():
            status = "unsafe-symlink"
            actual = None
        elif not item.destination.exists():
            status = "missing"
            actual = None
        elif not item.destination.is_file():
            status = "wrong-type"
            actual = None
        else:
            _check_no_symlink(item.destination, target)
            actual = _sha256(item.destination)
            status = "match" if actual == expected else "drift"
        states.append(
            FileState(
                component=item.component,
                path=item.relative_destination,
                status=status,
                expected_sha256=expected,
                actual_sha256=actual,
            )
        )
    return states


def _unmanaged_states(files: Sequence[ManagedFile], target: Path) -> list[FileState]:
    managed_paths = {item.destination for item in files}
    roots = {(item.component, item.destination_root) for item in files}
    states: list[FileState] = []
    for component, root in sorted(roots, key=lambda item: (item[0], str(item[1]))):
        if not root.exists() or not root.is_dir():
            continue
        _check_no_symlink(root, target)
        for candidate in sorted(root.rglob("*")):
            if candidate in managed_paths:
                continue
            if candidate.is_symlink():
                actual = None
            elif candidate.is_dir():
                continue
            elif candidate.is_file():
                _check_no_symlink(candidate, target)
                actual = _sha256(candidate)
            else:
                continue
            states.append(
                FileState(
                    component=component,
                    path=str(candidate.relative_to(target)),
                    status="unmanaged",
                    expected_sha256=None,
                    actual_sha256=actual,
                )
            )
    return states


def _safe_target(raw: str) -> Path:
    target = Path(raw).expanduser().resolve()
    forbidden = {
        Path(target.anchor).resolve(),
        Path.home().resolve(),
        REPO_ROOT,
        Path.cwd().resolve(),
    }
    if target in forbidden:
        raise ControlError(f"refusing unsafe sandbox target: {target}")
    return target


def _require_marker(target: Path) -> None:
    marker = target / MARKER_NAME
    if marker.is_symlink() or not marker.is_file():
        raise ControlError(f"target is not a marked sysops_pub sandbox: {target}")
    if marker.read_text(encoding="utf-8") != MARKER_CONTENT:
        raise ControlError(f"sandbox marker content is invalid: {marker}")


def _initialize(target: Path) -> None:
    if target.exists() and not target.is_dir():
        raise ControlError(f"sandbox target is not a directory: {target}")
    if target.exists():
        entries = list(target.iterdir())
        if entries and not (target / MARKER_NAME).is_file():
            raise ControlError(f"refusing to mark a non-empty directory: {target}")
    target.mkdir(parents=True, exist_ok=True)
    marker = target / MARKER_NAME
    if marker.exists():
        _require_marker(target)
    else:
        marker.write_text(MARKER_CONTENT, encoding="utf-8")
    print(f"initialized sandbox: {target}")


def _print_states(states: Sequence[FileState]) -> None:
    for state in states:
        print(f"{state.status.upper():14} {state.component:14} {state.path}")
    counts: dict[str, int] = {}
    for state in states:
        counts[state.status] = counts.get(state.status, 0) + 1
    summary = ", ".join(f"{name}={counts[name]}" for name in sorted(counts)) or "no files"
    print(f"summary: {summary}")


def _apply(files: Sequence[ManagedFile], target: Path, execute: bool) -> int:
    before = _states(files, target)
    _print_states(before)
    unsafe = [state for state in before if state.status in {"unsafe-symlink", "wrong-type"}]
    if unsafe:
        paths = ", ".join(state.path for state in unsafe)
        print(f"control: refusing unsafe destination state(s): {paths}", file=sys.stderr)
        return 2
    if not execute:
        print("dry-run only: pass --execute to write")
        return 0

    _require_marker(target)
    for item, state in zip(files, before, strict=True):
        if state.status == "match":
            continue
        _check_no_symlink(item.destination.parent, target)
        item.destination.parent.mkdir(parents=True, exist_ok=True)
        _check_no_symlink(item.destination.parent, target)
        with tempfile.NamedTemporaryFile(dir=item.destination.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(item.source.read_bytes())
        os.chmod(temporary, 0o644)
        temporary.replace(item.destination)
        print(f"APPLIED        {item.component:14} {item.relative_destination}")

    after = _states(files, target)
    failed = [state for state in after if state.status != "match"]
    if failed:
        _print_states(after)
        return 1
    print(f"apply verified: {len(after)} managed file(s) match")
    return 0


def _report(states: Sequence[FileState], target: Path, as_json: bool) -> None:
    counts: dict[str, int] = {}
    for state in states:
        counts[state.status] = counts.get(state.status, 0) + 1
    if as_json:
        print(
            json.dumps(
                {
                    "target": str(target),
                    "summary": counts,
                    "files": [asdict(state) for state in states],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    print("# sysops_pub status report")
    print()
    print(f"Target: `{target}`")
    print()
    print("| Status | Component | Path |")
    print("|---|---|---|")
    for state in states:
        print(f"| {state.status} | {state.component} | `{state.path}` |")
    print()
    print("Summary: " + ", ".join(f"{key}={counts[key]}" for key in sorted(counts)))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY,
        help="Component registry to read (default: registry/components.json)",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=DEFAULT_PROFILE,
        help="Desired-state profile that selects components (default: profiles/demo.json)",
    )
    parser.add_argument(
        "--component",
        action="append",
        default=[],
        help="Limit the operation to an enabled profile component; repeat as needed",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create an empty marked sandbox")
    init_parser.add_argument(
        "--target",
        required=True,
        help="New, empty, or already marked directory to use as the sandbox",
    )

    phases = {
        "plan": "Compare desired files to the target without writing",
        "apply": "Preview the writes; with --execute, write inside the marked sandbox",
        "verify": "Independently recompute expected hashes and compare the target",
        "report": "Summarize matched, missing, drifted, and unmanaged files",
    }
    for command, summary in phases.items():
        subparser = subparsers.add_parser(command, help=summary)
        subparser.add_argument("--target", required=True, help="Marked sandbox directory")
        if command == "apply":
            subparser.add_argument(
                "--execute", action="store_true", help="Write; without it, apply only previews"
            )
        if command == "report":
            subparser.add_argument("--json", action="store_true", help="Print the report as JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        target = _safe_target(args.target)
        if args.command == "init":
            _initialize(target)
            return 0

        files = _managed_files(
            target=target,
            registry_path=args.registry.resolve(),
            profile_path=args.profile.resolve(),
            requested=args.component,
        )
        states = _states(files, target)
        if args.command == "plan":
            _print_states(states)
            return 0
        if args.command == "apply":
            return _apply(files, target, args.execute)
        if args.command == "verify":
            _print_states(states)
            return 0 if all(state.status == "match" for state in states) else 1
        if args.command == "report":
            _report(states + _unmanaged_states(files, target), target, args.json)
            return 0
        raise ControlError(f"unknown command: {args.command}")
    except (ControlError, OSError, RuntimeError, ValueError) as exc:
        print(f"control: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
