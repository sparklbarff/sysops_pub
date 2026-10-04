#!/usr/bin/env python3
"""Demonstrate supervised updates inside an isolated synthetic state directory."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = REPO_ROOT / "samples" / "updates" / "catalog.json"
DEFAULT_STATE = REPO_ROOT / "samples" / "updates" / "state-template.json"
MARKER_NAME = ".sysops-pub-update-sandbox"
STATE_NAME = "state.json"
RECEIPTS_NAME = "receipts"


class UpdateError(RuntimeError):
    """The update request or sandbox state is unsafe or malformed."""


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _resolved_target(raw: str | Path) -> Path:
    unresolved = Path(raw).expanduser()
    if unresolved.is_symlink():
        raise UpdateError(f"refusing symlink target: {unresolved}")
    target = unresolved.resolve()
    if target == Path(target.anchor) or target in {Path.home().resolve(), Path.cwd().resolve()}:
        raise UpdateError(f"refusing unsafe target: {target}")
    if _is_within(target, REPO_ROOT) or _is_within(REPO_ROOT, target):
        raise UpdateError("update sandbox must be separate from this repository")
    return target


def _load_json(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise UpdateError(f"missing or unsafe JSON file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateError(f"invalid JSON file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise UpdateError(f"JSON root must be an object: {path}")
    return value


def _validate_catalog(value: dict[str, object]) -> dict[str, dict[str, str]]:
    if value.get("schema_version") != 1 or set(value) != {"schema_version", "channels"}:
        raise UpdateError("catalog must use schema version 1 and contain only channels")
    channels = value["channels"]
    if not isinstance(channels, dict) or not channels:
        raise UpdateError("catalog channels must be a non-empty object")
    validated: dict[str, dict[str, str]] = {}
    for channel, items in channels.items():
        if not isinstance(channel, str) or not channel or not isinstance(items, dict) or not items:
            raise UpdateError("catalog channel names and item maps must be non-empty")
        validated[channel] = {}
        for name, version in items.items():
            if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
                raise UpdateError("catalog item names and versions must be non-empty strings")
            validated[channel][name] = version
    return validated


def _validate_state(
    value: dict[str, object], catalog: dict[str, dict[str, str]]
) -> dict[str, dict[str, dict[str, object]]]:
    if value.get("schema_version") != 1 or set(value) != {"schema_version", "channels"}:
        raise UpdateError("state must use schema version 1 and contain only channels")
    channels = value["channels"]
    if not isinstance(channels, dict) or set(channels) != set(catalog):
        raise UpdateError("state channels must exactly match the catalog")
    validated: dict[str, dict[str, dict[str, object]]] = {}
    for channel, desired_items in catalog.items():
        items = channels[channel]
        if not isinstance(items, dict) or set(items) != set(desired_items):
            raise UpdateError(f"state items must exactly match catalog channel {channel}")
        validated[channel] = {}
        for name, raw_item in items.items():
            if not isinstance(raw_item, dict) or set(raw_item) != {"running", "version"}:
                raise UpdateError(f"invalid state item: {channel}/{name}")
            version = raw_item["version"]
            running = raw_item["running"]
            if not isinstance(version, str) or not version or not isinstance(running, bool):
                raise UpdateError(f"invalid state values: {channel}/{name}")
            validated[channel][name] = {"version": version, "running": running}
    return validated


def _write_json_atomic(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def initialize(target_raw: str | Path, execute: bool) -> Path:
    target = _resolved_target(target_raw)
    if target.exists():
        if target.is_symlink() or not target.is_dir() or any(target.iterdir()):
            raise UpdateError("initialization requires a new or empty directory")
    elif not target.parent.is_dir():
        raise UpdateError("target parent directory does not exist")
    if not execute:
        print(f"WOULD INITIALIZE {target}")
        print("dry-run only: pass --execute to create the synthetic update sandbox")
        return target
    target.mkdir(exist_ok=True)
    marker = {"purpose": "synthetic-update-demo", "schema_version": 1}
    _write_json_atomic(target / MARKER_NAME, marker)
    _write_json_atomic(target / STATE_NAME, _load_json(DEFAULT_STATE))
    print(f"INITIALIZED {target}")
    return target


def _open_sandbox(
    target_raw: str | Path, catalog_path: Path = DEFAULT_CATALOG
) -> tuple[Path, dict[str, dict[str, str]], dict[str, dict[str, dict[str, object]]]]:
    target = _resolved_target(target_raw)
    if target.is_symlink() or not target.is_dir():
        raise UpdateError("update sandbox does not exist or is unsafe")
    marker = _load_json(target / MARKER_NAME)
    if marker != {"purpose": "synthetic-update-demo", "schema_version": 1}:
        raise UpdateError("update sandbox marker is missing or invalid")
    catalog = _validate_catalog(_load_json(catalog_path))
    state = _validate_state(_load_json(target / STATE_NAME), catalog)
    return target, catalog, state


def plan(
    catalog: dict[str, dict[str, str]],
    state: dict[str, dict[str, dict[str, object]]],
    channel: str | None = None,
) -> list[dict[str, object]]:
    if channel is not None and channel not in catalog:
        raise UpdateError(f"unknown update channel: {channel}")
    channels = [channel] if channel else sorted(catalog)
    result: list[dict[str, object]] = []
    for channel_name in channels:
        assert channel_name is not None
        for name in sorted(catalog[channel_name]):
            available = catalog[channel_name][name]
            installed = state[channel_name][name]
            current = installed["version"]
            running = installed["running"]
            if current == available:
                status = "current"
            elif running:
                status = "deferred"
            else:
                status = "update"
            result.append(
                {
                    "available": available,
                    "channel": channel_name,
                    "current": current,
                    "name": name,
                    "running": running,
                    "status": status,
                }
            )
    return result


def _print_plan(entries: Sequence[dict[str, object]], preview: bool = False) -> None:
    for entry in entries:
        status = str(entry["status"])
        if preview and status == "update":
            status = "would-update"
        print(
            f"{status.upper():12} {entry['channel']}/{entry['name']} "
            f"{entry['current']} -> {entry['available']}"
        )


def check(target_raw: str | Path, channel: str | None = None) -> list[dict[str, object]]:
    _target, catalog, state = _open_sandbox(target_raw)
    entries = plan(catalog, state, channel)
    _print_plan(entries)
    return entries


def _receipt_name(now: datetime) -> str:
    return now.astimezone(UTC).strftime("update-%Y%m%dT%H%M%SZ.json")


def apply(
    target_raw: str | Path,
    channel: str,
    execute: bool,
    clock: Callable[[], datetime] | None = None,
) -> Path | None:
    target, catalog, state = _open_sandbox(target_raw)
    entries = plan(catalog, state, channel)
    _print_plan(entries, preview=not execute)
    if not execute:
        print("dry-run only: pass --execute to update this one synthetic channel")
        return None

    now = (clock or (lambda: datetime.now(UTC)))()
    receipts = target / RECEIPTS_NAME
    receipt_path = receipts / _receipt_name(now)
    if receipt_path.exists():
        raise UpdateError(f"refusing to overwrite existing receipt: {receipt_path.name}")

    before = copy.deepcopy(state)
    actions: list[dict[str, object]] = []
    for entry in entries:
        action = str(entry["status"])
        if action == "update":
            state[channel][str(entry["name"])]["version"] = entry["available"]
            action = "updated"
        actions.append({**entry, "action": action})

    _write_json_atomic(target / STATE_NAME, {"schema_version": 1, "channels": state})
    verified_entries = plan(catalog, state, channel)
    verification_passed = all(
        entry["status"] in {"current", "deferred"} for entry in verified_entries
    )
    receipt = {
        "actions": actions,
        "after": state,
        "before": before,
        "channel": channel,
        "receipt_schema_version": 1,
        "verification_passed": verification_passed,
    }
    receipts.mkdir(exist_ok=True)
    _write_json_atomic(receipt_path, receipt)
    if not verification_passed:
        raise UpdateError("post-update verification failed")
    print(f"VERIFIED     {channel}")
    print(f"RECEIPT      {receipt_path}")
    return receipt_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser(
        "init", help="Create a synthetic update sandbox in a new or empty directory"
    )
    init_parser.add_argument("target", help="New or empty directory for the sandbox")
    init_parser.add_argument(
        "--execute", action="store_true", help="Create it; without this, only preview"
    )
    check_parser = subparsers.add_parser(
        "check", help="List available updates for every channel, or one, without writing"
    )
    check_parser.add_argument("target", help="Synthetic update sandbox directory")
    check_parser.add_argument("--channel", help="Check only this update channel")
    apply_parser = subparsers.add_parser(
        "apply", help="Update one named channel, deferring running items, with a receipt"
    )
    apply_parser.add_argument("target", help="Synthetic update sandbox directory")
    apply_parser.add_argument("--channel", required=True, help="The one channel to update")
    apply_parser.add_argument(
        "--execute", action="store_true", help="Apply the update; without this, only preview"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "init":
            initialize(args.target, args.execute)
        elif args.command == "check":
            check(args.target, args.channel)
        else:
            apply(args.target, args.channel, args.execute)
        return 0
    except (OSError, UpdateError) as exc:
        print(f"update_supervisor: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
