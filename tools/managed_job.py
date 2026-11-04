#!/usr/bin/env python3
"""Run one foreground command to completion and write a sanitized ownership receipt."""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RECEIPT_SCHEMA_VERSION = 2
TIMEOUT_RETURN_CODE = 124
START_FAILURE_RETURN_CODE = 127
OWNERSHIP_RETURN_CODE = 125
# SIGBREAK is Windows' console break (CTRL_BREAK_EVENT), its only catchable cancellation.
CANCEL_SIGNALS = tuple(
    number
    for number in (
        getattr(signal, "SIGTERM", None),
        getattr(signal, "SIGHUP", None),
        getattr(signal, "SIGBREAK", None),
    )
    if number is not None
)


class ManagedJobError(RuntimeError):
    """The managed job request is unsafe or incomplete."""


class _Cancelled(BaseException):
    """The runner itself was asked to stop while it waited on the owned job."""

    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


@contextlib.contextmanager
def _cancellation() -> Iterator[dict[str, int]]:
    """Route SIGTERM and SIGHUP (SIGBREAK on Windows) into the runner, so cancelling it cleans up
    what it owns.

    The child runs in its own session, so a signal to the runner never reaches it; left to the
    default action the runner would die and leave the job running with no receipt. Every signal is
    recorded; only while the caller has armed the state does the first one raise into the wait, so
    cleanup and the receipt always complete. Handlers can be installed only from the main thread;
    elsewhere the previous behavior is unchanged.
    """
    state = {"armed": 0, "signum": 0}
    if threading.current_thread() is not threading.main_thread():
        yield state
        return

    def handler(signum: int, _frame: object) -> None:
        if not state["signum"]:
            state["signum"] = signum
        if state["armed"]:
            state["armed"] = 0
            raise _Cancelled(signum)

    previous = {number: signal.signal(number, handler) for number in CANCEL_SIGNALS}
    try:
        yield state
    finally:
        for number, original in previous.items():
            signal.signal(number, original)


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
    """Write the whole receipt to a private, unpredictable temporary file, then publish it with a
    hard link, which fails rather than overwrite anything already at the path and never follows a
    symlink there. The fixed `.name.tmp` it replaces followed a planted symlink and overwrote the
    sentinel behind it (repair audit 2026-11-03)."""
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise ManagedJobError(f"refusing to overwrite receipt: {path}") from exc
    finally:
        Path(temporary).unlink(missing_ok=True)


SETTLE_SECONDS = 0.5


def _owned_group_active(process_id: int) -> bool | None:
    """Whether any member of the owned POSIX process group still exists.

    Signal 0 probes the group without delivering anything, so the check stays in-process. A
    sandboxed runtime can refuse to spawn ps, and a probe that depended on it reported unknown
    ownership, and so failure, on every job run inside one. A zombie still exists until its parent
    reaps it, so a caller that needs a terminal verdict polls through _group_terminal rather than
    trusting one sample.
    """
    try:
        os.killpg(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


class _WindowsJob:
    """A Windows job object: the process group POSIX gets from start_new_session.

    Every process the leader starts joins the job, so the whole tree can be counted and ended at
    once, after the leader has gone. Before this, Windows ended only the leader, and a grandchild
    outlived every timeout and cancellation (native acceptance, 2026-11-04). The job is created
    with KILL_ON_JOB_CLOSE, so even a runner that dies outright takes the tree with it.

    The leader is assigned just after it starts. A child it spawns in that instant, before its
    interpreter or program has even loaded, would escape; nothing here starts that fast.
    """

    KILL_ON_JOB_CLOSE = 0x2000
    EXTENDED_LIMIT_INFORMATION = 9
    BASIC_ACCOUNTING_INFORMATION = 1

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimits),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        class Accounting(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_int64),
                ("TotalKernelTime", ctypes.c_int64),
                ("ThisPeriodTotalUserTime", ctypes.c_int64),
                ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                ("TotalPageFaultCount", wintypes.DWORD),
                ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD),
                ("TotalTerminatedProcesses", wintypes.DWORD),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
        kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        )
        kernel32.QueryInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.LPVOID,
        )
        kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._ctypes = ctypes
        self._kernel32 = kernel32
        self._accounting = Accounting
        self._handle = kernel32.CreateJobObjectW(None, None)
        if not self._handle:
            raise ManagedJobError(f"cannot create a job object: error {ctypes.get_last_error()}")
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = self.KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            self._handle,
            self.EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            error = ctypes.get_last_error()
            self.close()
            raise ManagedJobError(f"cannot configure the job object: error {error}")

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        """Put the leader in the job, or end it: an unowned job is never left running."""
        handle = int(process._handle)  # type: ignore[attr-defined]
        if not self._kernel32.AssignProcessToJobObject(self._handle, handle):
            error = self._ctypes.get_last_error()
            process.kill()
            process.wait()
            raise ManagedJobError(f"cannot place the job in a job object: error {error}")

    def active(self) -> bool | None:
        accounting = self._accounting()
        if not self._kernel32.QueryInformationJobObject(
            self._handle,
            self.BASIC_ACCOUNTING_INFORMATION,
            self._ctypes.byref(accounting),
            self._ctypes.sizeof(accounting),
            None,
        ):
            return None
        return accounting.ActiveProcesses > 0

    def terminate(self) -> None:
        self._kernel32.TerminateJobObject(self._handle, 1)

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


def _tree(process: subprocess.Popen[bytes], job: _WindowsJob | None) -> Callable[[], bool | None]:
    """Whether anything the job started is still running: its job object on Windows, its process
    group on POSIX."""
    if job is not None:
        return job.active
    if os.name == "posix":
        return lambda: _owned_group_active(process.pid)
    return lambda: process.poll() is None


def _group_terminal(
    active: Callable[[], bool | None], seconds: float = SETTLE_SECONDS
) -> bool | None:
    """True once the tree is empty, False if members remain after the window, None if unknown.

    The window covers children a dead leader left as zombies: the system reparents and reaps them
    within milliseconds, and a live child outlasts the window and stays a leftover.
    """
    deadline = time.monotonic() + seconds
    while True:
        state = active()
        if state is None:
            return None
        if not state:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)


def _stop_owned_process(process: subprocess.Popen[bytes], job: _WindowsJob | None) -> bool:
    active = _tree(process, job)
    if active() is False:
        return False
    try:
        if job is not None:
            job.terminate()  # every member at once; Windows has no graceful group signal
        elif os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        return False
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        process.poll()
        if active() is False:
            break
        time.sleep(0.02)
    else:
        try:
            if os.name == "posix" and job is None:
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
    process.wait(timeout=2)
    return True


def _wait(process: subprocess.Popen[bytes], timeout: float | None) -> int:
    """process.wait, in short slices on Windows: its wait is one uninterruptible system call, so a
    cancellation signal's handler would not run until the job ended on its own."""
    if os.name != "nt":
        return process.wait(timeout=timeout)
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        try:
            return process.wait(timeout=0.1)
        except subprocess.TimeoutExpired:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(process.args, timeout) from None


def run_managed(
    command: Sequence[str],
    receipt_raw: str | Path,
    timeout: float | None = None,
) -> int:
    if not command or not command[0]:
        raise ManagedJobError("a command is required")
    if timeout is not None and (not math.isfinite(timeout) or timeout <= 0):
        raise ManagedJobError("timeout must be positive and finite")
    receipt_path = _safe_receipt(receipt_raw)
    started_at = datetime.now(UTC)
    started_clock = time.monotonic()
    timed_out = False
    interrupted = False
    termination_attempted = False
    process_id: int | None = None
    owned_group_terminal: bool | None = None
    leftover_children = False

    popen_options: dict[str, object] = {}
    if os.name == "posix":
        popen_options["start_new_session"] = True
    elif os.name == "nt":
        popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

    job = _WindowsJob() if os.name == "nt" else None
    try:
        with _cancellation() as cancel:
            try:
                process = subprocess.Popen(list(command), **popen_options)
                process_id = process.pid
            except OSError as exc:
                return_code = START_FAILURE_RETURN_CODE
                start_error = type(exc).__name__
            else:
                start_error = None
                if job is not None:
                    job.assign(process)
                try:
                    try:
                        # Armed only while waiting: a signal during cleanup or the receipt is
                        # recorded, never raised, and one that arrived while starting is honored
                        # now.
                        cancel["armed"] = 1
                        if cancel["signum"]:
                            raise _Cancelled(cancel["signum"])
                        return_code = _wait(process, timeout)
                    finally:
                        cancel["armed"] = 0
                except subprocess.TimeoutExpired:
                    timed_out = True
                    termination_attempted = _stop_owned_process(process, job)
                    return_code = TIMEOUT_RETURN_CODE
                except KeyboardInterrupt:
                    interrupted = True
                    termination_attempted = _stop_owned_process(process, job)
                    return_code = 130
                except _Cancelled as cancelled:
                    interrupted = True
                    termination_attempted = _stop_owned_process(process, job)
                    return_code = 128 + cancelled.signum

                if os.name in ("posix", "nt"):
                    active = _tree(process, job)
                    if _group_terminal(active) is not True:
                        leftover_children = not timed_out and not interrupted
                        termination_attempted = (
                            _stop_owned_process(process, job) or termination_attempted
                        )
                        if leftover_children:
                            return_code = OWNERSHIP_RETURN_CODE
                    owned_group_terminal = _group_terminal(active)
                    if not owned_group_terminal:
                        return_code = OWNERSHIP_RETURN_CODE
            return _finish(
                receipt_path,
                command,
                started_at,
                started_clock,
                return_code=return_code,
                start_error=start_error,
                process_id=process_id,
                timed_out=timed_out,
                interrupted=interrupted,
                termination_attempted=termination_attempted,
                leftover_children=leftover_children,
                owned_group_terminal=owned_group_terminal,
            )
    finally:
        if job is not None:
            job.close()


def _finish(
    receipt_path: Path,
    command: Sequence[str],
    started_at: datetime,
    started_clock: float,
    *,
    return_code: int,
    start_error: str | None,
    process_id: int | None,
    timed_out: bool,
    interrupted: bool,
    termination_attempted: bool,
    leftover_children: bool,
    owned_group_terminal: bool | None,
) -> int:
    ended_at = datetime.now(UTC)
    receipt = {
        "argument_count": max(0, len(command) - 1),
        "command_name": Path(command[0]).name,
        "duration_seconds": round(time.monotonic() - started_clock, 6),
        "ended_at": ended_at.isoformat(),
        "interrupted": interrupted,
        "leftover_children": leftover_children,
        "owned_group_terminal": owned_group_terminal,
        "process_id": process_id,
        "receipt_schema_version": RECEIPT_SCHEMA_VERSION,
        "return_code": return_code,
        "start_error": start_error,
        "started_at": started_at.isoformat(),
        "termination_attempted": termination_attempted,
        "timed_out": timed_out,
    }
    _write_receipt(receipt_path, receipt)
    if return_code == OWNERSHIP_RETURN_CODE:
        print(
            "managed_job: leading process exited without terminal ownership proof", file=sys.stderr
        )
    print(f"managed job receipt: {receipt_path}")
    return return_code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--receipt",
        required=True,
        help="Path for the sanitized receipt; must be new and outside this repository",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        help="Seconds before the owned process group is terminated; positive and finite",
    )
    parser.add_argument(
        "command", nargs=argparse.REMAINDER, help="The command to run in the foreground"
    )
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
