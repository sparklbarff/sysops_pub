#!/usr/bin/env python3
"""Prove that a checker rejects a preserved known failure and accepts valid cases.

One fixed command runs the checker against three declared inputs: a preserved known failure, a
valid case and an allowed variation. The failure must exit with the declared rejection code AND
print the declared diagnostic, so a crash or syntax error cannot pass as a rejection. The checker
and every input are fingerprinted, and calibration stops if a run changes any of them. A verified
result covers the declared cases only; it is not product acceptance or owner approval.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROLES = ("known_failure", "valid", "allowed_variation")
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 64 * 1024
INTERPRETER = re.compile(r"python(?:3(?:\.\d+)?)?(?:\.exe)?|node(?:\.exe)?|sh|bash")


class CalibrationError(ValueError):
    """The calibration request cannot produce meaningful evidence."""


def _invokes(command: Sequence[str], checker: Path) -> bool:
    if Path(command[0]).resolve() == checker:
        return True
    return (
        len(command) > 1
        and bool(INTERPRETER.fullmatch(Path(command[0]).name.lower()))
        and Path(command[1]).resolve() == checker
    )


def _fingerprint(path: Path) -> str:
    if not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
        raise CalibrationError(f"missing, non-file or oversized calibration input: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stop(process: subprocess.Popen[bytes]) -> None:
    # POSIX checkers run in their own session, so the whole group is ours to stop. On Windows only
    # the leading process is stopped; use managed_job.py for work that spawns children there.
    if os.name == "posix":
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)
    else:
        with contextlib.suppress(OSError):
            process.kill()
    process.wait(timeout=5)


def _run_case(argv: list[str], timeout: float, diagnostic: str) -> dict[str, Any]:
    # File-backed output avoids pipe deadlocks. Output is searched, never echoed.
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(
            argv, stdout=output, stderr=subprocess.STDOUT, start_new_session=os.name == "posix"
        )
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            _stop(process)
        output.seek(0)
        raw = output.read(MAX_OUTPUT_BYTES + 1)
    return {
        "exit_code": None if timed_out else process.returncode,
        "timed_out": timed_out,
        "output_over_limit": len(raw) > MAX_OUTPUT_BYTES,
        "rejection_diagnostic": diagnostic in raw.decode("utf-8", errors="replace"),
    }


def calibrate(
    checker: Path,
    cases: dict[str, Path],
    command: Sequence[str],
    diagnostic: str,
    reject_code: int = 1,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Run the three declared cases and report whether the checker discriminates them."""
    if set(cases) != set(ROLES):
        raise CalibrationError(
            "a known failure, a valid case and an allowed variation are required"
        )
    if reject_code not in (1, 2):
        raise CalibrationError("the rejection code must be 1 or 2, never success")
    if not math.isfinite(timeout) or not 0 < timeout <= 30:
        raise CalibrationError("each case needs a finite timeout of at most 30 seconds")
    if len(diagnostic.strip()) < 4:
        raise CalibrationError("a specific rejection diagnostic is required")
    if not command or list(command).count("{case}") != 1:
        raise CalibrationError("the fixed command needs exactly one standalone {case} argument")
    checker = checker.resolve()
    if not _invokes(command, checker):
        raise CalibrationError("the fixed command must invoke the fingerprinted checker")
    paths = {"checker": checker, **{role: cases[role].resolve() for role in ROLES}}
    before = {role: _fingerprint(path) for role, path in paths.items()}
    if len({before[role] for role in ROLES}) != len(ROLES):
        raise CalibrationError("the three cases must have distinct bytes")

    results: list[dict[str, Any]] = []
    unchanged = True
    for role in ROLES:
        argv = [str(paths[role]) if arg == "{case}" else arg for arg in command]
        row = _run_case(argv, timeout, diagnostic)
        expected = reject_code if role == "known_failure" else 0
        row.update(role=role, expected_exit_code=expected)
        row["matches"] = (
            row["exit_code"] == expected
            and not row["output_over_limit"]
            and row["rejection_diagnostic"] == (role == "known_failure")
        )
        results.append(row)
        # Later cases must run against the same checker and inputs the result names.
        try:
            unchanged = all(_fingerprint(path) == before[role] for role, path in paths.items())
        except (OSError, CalibrationError):
            unchanged = False
        if not unchanged:
            break
    verified = unchanged and len(results) == len(ROLES) and all(r["matches"] for r in results)
    return {
        "status": "calibration-verified" if verified else "calibration-failed",
        "scope": "declared cases only; not product acceptance or owner approval",
        "command": list(command),
        "inputs": {
            role: {"path": str(path), "sha256": before[role]} for role, path in paths.items()
        },
        "inputs_unchanged": unchanged,
        "cases": results,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--checker", required=True, type=Path, help="The checker file to prove")
    parser.add_argument(
        "--known-failure", required=True, type=Path, help="A preserved input it must reject"
    )
    parser.add_argument("--valid", required=True, type=Path, help="An input it must accept")
    parser.add_argument(
        "--allowed-variation",
        required=True,
        type=Path,
        help="A different valid input it must also accept",
    )
    parser.add_argument(
        "--diagnostic", required=True, help="Text the rejection must print, proving its reason"
    )
    parser.add_argument(
        "--reject-code", type=int, default=1, help="Exit code that means rejection (1 or 2)"
    )
    parser.add_argument(
        "--timeout", type=float, default=10.0, help="Seconds allowed per case (at most 30)"
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="After --, the fixed checker command with one {case} placeholder",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    cases = {
        "known_failure": args.known_failure,
        "valid": args.valid,
        "allowed_variation": args.allowed_variation,
    }
    try:
        result = calibrate(
            args.checker, cases, command, args.diagnostic, args.reject_code, args.timeout
        )
    except (OSError, CalibrationError) as exc:
        print(json.dumps({"status": "calibration-error", "error": str(exc)}))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "calibration-verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
