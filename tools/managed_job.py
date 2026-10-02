#!/usr/bin/env python3
"""Run one foreground command to completion and write a sanitized ownership receipt."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RECEIPT_SCHEMA_VERSION = 1
TIMEOUT_RETURN_CODE = 124
START_FAILURE_RETURN_CODE = 127


class ManagedJobError(RuntimeError):
    """The managed job request is unsafe or incomplete."""


def _safe_receipt(raw: str | Path) -> Path:
    unresolved = Path(raw).expanduser()
    if unresolved.is_symlink():
        raise ManagedJobError(f"refusing symlink receipt: {unresolved}")
    path = unresolved.resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError:
        pass
    else:
        raise ManagedJobError("receipt must be written outside this repository")
    if path.exists() or path.is_symlink():
        raise ManagedJobError(f"refusing to overwrite receipt: {path}")
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise ManagedJobError(f"receipt parent is missing or unsafe: {path.parent}")
    return path


def _write_receipt(path: Path, value: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _stop_owned_process(process: subprocess.Popen[bytes]) -> bool:
    if process.poll() is not None:
        return False
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        return False
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
        process.wait()
    return True


def run_managed(
    command: Sequence[str],
    receipt_raw: str | Path,
    timeout: float | None = None,
) -> int:
    if not command or not command[0]:
        raise ManagedJobError("a command is required")
    if timeout is not None and timeout <= 0:
        raise ManagedJobError("timeout must be positive")
    receipt_path = _safe_receipt(receipt_raw)
    started_at = datetime.now(UTC)
    started_clock = time.monotonic()
    timed_out = False
    interrupted = False
    termination_attempted = False
    process_id: int | None = None

    popen_options: dict[str, object] = {}
    if os.name == "posix":
        popen_options["start_new_session"] = True
    elif os.name == "nt":
        popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        process = subprocess.Popen(list(command), **popen_options)
        process_id = process.pid
    except OSError as exc:
        return_code = START_FAILURE_RETURN_CODE
        start_error = type(exc).__name__
    else:
        start_error = None
        try:
            return_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            termination_attempted = _stop_owned_process(process)
            return_code = TIMEOUT_RETURN_CODE
        except KeyboardInterrupt:
            interrupted = True
            termination_attempted = _stop_owned_process(process)
            return_code = 130

    ended_at = datetime.now(UTC)
    receipt = {
        "argument_count": max(0, len(command) - 1),
        "command_name": Path(command[0]).name,
        "duration_seconds": round(time.monotonic() - started_clock, 6),
        "ended_at": ended_at.isoformat(),
        "interrupted": interrupted,
        "process_id": process_id,
        "receipt_schema_version": RECEIPT_SCHEMA_VERSION,
        "return_code": return_code,
        "start_error": start_error,
        "started_at": started_at.isoformat(),
        "termination_attempted": termination_attempted,
        "timed_out": timed_out,
    }
    _write_receipt(receipt_path, receipt)
    print(f"managed job receipt: {receipt_path}")
    return return_code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--timeout", type=float)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    try:
        return run_managed(command, args.receipt, args.timeout)
    except (ManagedJobError, OSError) as exc:
        print(f"managed_job: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
