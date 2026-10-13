#!/usr/bin/env python3
"""Demonstrate supervised updates inside an isolated synthetic state directory."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = REPO_ROOT / "samples" / "updates" / "catalog.json"
DEFAULT_STATE = REPO_ROOT / "samples" / "updates" / "state-template.json"
MARKER_NAME = ".sysops-pub-update-sandbox"
STATE_NAME = "state.json"
RECEIPTS_NAME = "receipts"
UNRESOLVED_NAME = "unresolved.json"


class UpdateError(RuntimeError):
    """The update request or sandbox state is unsafe or malformed."""


class UnresolvedError(UpdateError):
    """An earlier failed update is still unmet, whatever this run did."""


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
    """Replace path through a fresh, exclusively created temporary file in a real directory.

    A predictable temporary name could already exist as a symlink to a file outside the sandbox,
    and writing to it would follow the link. The temporary file is created with a unique name that
    cannot pre-exist, and neither the destination nor its directory may be a symlink.
    """
    if path.is_symlink():
        raise UpdateError(f"refusing to write through a symlink: {path}")
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise UpdateError(f"output directory is missing or a symlink: {path.parent}")
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _prepare_outputs(target: Path, receipt_path: Path) -> None:
    """Refuse every output path that could leave the sandbox, before the first write.

    The receipts directory must be a real directory inside the sandbox, created here if absent, and
    no output file may be a symlink. Checking afterwards would be too late: the state is the first
    thing written.
    """
    receipts = receipt_path.parent
    for path in (target / STATE_NAME, target / UNRESOLVED_NAME, receipt_path):
        if path.is_symlink():
            raise UpdateError(f"refusing output path that is a symlink: {path}")
    if receipts.is_symlink() or (receipts.exists() and not receipts.is_dir()):
        raise UpdateError(f"receipts path is not a real directory: {receipts}")
    receipts.mkdir(exist_ok=True)
    if receipts.resolve().parent != target:
        raise UpdateError(f"receipts directory resolves outside the sandbox: {receipts}")


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
    target, catalog, state = _open_sandbox(target_raw)
    entries = plan(catalog, state, channel)
    _print_plan(entries)
    # A check that changes nothing must still surface an earlier failure that has not cleared, and
    # a check writes nothing: whether an entry is satisfied is reported, and the record changes only
    # in an apply.
    _raise_if_unresolved(reconcile_unresolved(target, catalog, state, persist=False), state)
    return entries


def _load_pins(target: Path) -> dict[str, str]:
    path = target / UNRESOLVED_NAME
    if not path.exists():
        return {}
    pins = _load_json(path)
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in pins.items()):
        raise UpdateError("unresolved record must map channel/name to a target version")
    return {str(k): str(v) for k, v in pins.items()}


def reconcile_unresolved(
    target: Path,
    catalog: dict[str, dict[str, str]],
    state: dict[str, dict[str, dict[str, object]]],
    failed: dict[str, str] | None = None,
    persist: bool = True,
) -> dict[str, str]:
    """Re-check every recorded failure against the real state; persist what is unmet if asked.

    A pin records what a failed run should have left. Reaching it satisfies the pin, and so does
    reaching the catalog's current version, which supersedes an older target. Anything else,
    including an update that simply never happened, stays recorded. Without persist, a satisfied
    pin is only reported; the record is left for the next mutating operation to clear.
    """
    pins = {**_load_pins(target), **(failed or {})}
    remaining: dict[str, str] = {}
    for key, pinned in sorted(pins.items()):
        channel, _, name = key.partition("/")
        if _observed(state, key) not in (pinned, catalog.get(channel, {}).get(name)):
            remaining[key] = pinned
            print(f"UNRESOLVED   {_describe(key, pinned, state)}")
        elif not persist:
            print(f"RESOLVED     {key} now {_observed(state, key)}; cleared by the next apply")
    if persist and (pins or (target / UNRESOLVED_NAME).exists()):
        _write_json_atomic(target / UNRESOLVED_NAME, remaining)
    return remaining


def _observed(state: dict[str, dict[str, dict[str, object]]], key: str) -> object:
    channel, _, name = key.partition("/")
    return state.get(channel, {}).get(name, {}).get("version")


def _describe(key: str, pinned: str, state: dict[str, dict[str, dict[str, object]]]) -> str:
    return f"{key} expected {pinned}, observed {_observed(state, key)}"


def _raise_if_unresolved(
    remaining: dict[str, str], state: dict[str, dict[str, dict[str, object]]]
) -> None:
    if remaining:
        details = "; ".join(_describe(key, pin, state) for key, pin in sorted(remaining.items()))
        raise UnresolvedError(f"earlier update failures persist: {details}")


def _failed_dimensions(
    channel: str,
    actions: Sequence[dict[str, object]],
    expected: dict[str, dict[str, dict[str, object]]],
    observed: dict[str, dict[str, dict[str, object]]] | None,
) -> dict[str, str]:
    """Every item whose persisted version is not what the run expected, with that expectation.

    That covers a selected update that did not persist and an unselected item a collateral write
    changed: both are recorded at the version they should have. Pinning only the selected items
    would let a correct selected version clear the record at once and hide the collateral damage.
    When the state could not be read back at all, the selected updates are what is known to be at
    risk.
    """
    if observed is None:
        return {
            f"{channel}/{item['name']}": str(item["available"])
            for item in actions
            if item["action"] == "updated"
        }
    failed: dict[str, str] = {}
    for channel_name, items in expected.items():
        for name, item in items.items():
            persisted = observed.get(channel_name, {}).get(name, {}).get("version")
            if persisted != item["version"]:
                failed[f"{channel_name}/{name}"] = str(item["version"])
    return failed


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
    _prepare_outputs(target, receipt_path)

    before = copy.deepcopy(state)
    actions: list[dict[str, object]] = []
    for entry in entries:
        action = str(entry["status"])
        if action == "update":
            state[channel][str(entry["name"])]["version"] = entry["available"]
            action = "updated"
        actions.append({**entry, "action": action})

    _write_json_atomic(target / STATE_NAME, {"schema_version": 1, "channels": state})
    # Read the real subject again. Inspecting the dictionary we just changed only
    # verifies our intention, not persistence or preservation of other channels.
    verification_error = None
    observed = None
    try:
        _target, observed_catalog, observed = _open_sandbox(target)
        verification_passed = observed_catalog == catalog and observed == state
    except (OSError, UpdateError) as exc:
        verification_error = str(exc)
        verification_passed = False
    receipt = {
        "actions": actions,
        "after": observed,
        "before": before,
        "channel": channel,
        "expected_after": state,
        "receipt_schema_version": 3,
        "verification_error": verification_error,
        "verification_passed": verification_passed,
    }
    failed = {} if verification_passed else _failed_dimensions(channel, actions, state, observed)
    reread = observed if observed is not None else before
    receipt["unresolved"] = reconcile_unresolved(target, catalog, reread, failed)
    _write_json_atomic(receipt_path, receipt)
    if not verification_passed:
        raise UpdateError("post-update verification failed")
    print(f"VERIFIED     {channel}")
    print(f"RECEIPT      {receipt_path}")
    _raise_if_unresolved(receipt["unresolved"], reread)
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
    except UnresolvedError as exc:
        print(f"update_supervisor: {exc}", file=sys.stderr)
        return 1
    except (OSError, UpdateError) as exc:
        print(f"update_supervisor: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
