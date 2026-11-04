#!/usr/bin/env python3
"""Native install-lifecycle acceptance: run it on each platform the clone-and-run install claims.

Everything happens in a new temporary directory whose name contains spaces: a fresh clone of this
repository's HEAD, and a separate target project. It covers existing hooks, valid and invalid
policy cases, update, drift, rollback and removal, interruption, and process-tree cleanup, and it
records the platform and runtime it ran on. Nothing outside the temporary directory is written
except the report, and the directory is removed at the end.

    python scripts/acceptance.py --report <new path outside this repository>

Exit status 0 only if every case passed. A case the platform cannot support is a FAIL with its
reason, never a skip: the point is to find where the claim stops being true.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WINDOWS = os.name == "nt"
GRANDCHILD = (
    "import subprocess, sys, time\n"
    "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "import os\n"
    "open(sys.argv[1], 'w').write(f'{os.getpid()} {p.pid}')\n"
    "time.sleep(float(sys.argv[2]))\n"
)


class Run:
    def __init__(self) -> None:
        self.cases: list[dict[str, object]] = []

    def case(self, name: str, ok: bool, detail: str = "") -> bool:
        self.cases.append({"case": name, "result": "PASS" if ok else "FAIL", "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'}  {name}{': ' + detail if detail and not ok else ''}")
        return ok


def sh(args: list[str], cwd: Path, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
    )


def py(
    script: str, *args: str, cwd: Path, timeout: float = 120
) -> subprocess.CompletedProcess[str]:
    return sh([sys.executable, script, *args], cwd=cwd, timeout=timeout)


def alive(pid: int) -> bool:
    if WINDOWS:
        out = sh(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"], Path.cwd()).stdout
        return f'"{pid}"' in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def gone(pid: int, seconds: float = 3) -> bool:
    deadline = time.monotonic() + seconds
    while alive(pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.1)
    return True


def reap(pid: int) -> None:
    """Kill a survivor this harness started, so a failed case leaves nothing running."""
    if not alive(pid):
        return
    if WINDOWS:
        sh(["taskkill", "/F", "/T", "/PID", str(pid)], Path.cwd())
    else:
        os.kill(pid, signal.SIGKILL)


def wait_for(path: Path, seconds: float = 15) -> list[int]:
    """The job's leader and grandchild PIDs, once the leader has written them."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists() and len(path.read_text().split()) == 2:
            return [int(pid) for pid in path.read_text().split()]
        time.sleep(0.05)
    return []


def tree_state(pids: list[int]) -> tuple[bool, str]:
    """Whether every PID has ended, and a description; reaps any survivor either way."""
    survivors = [pid for pid in pids if not gone(pid)]
    for pid in survivors:
        reap(pid)
    if not pids:
        return False, "the job never reported its PIDs"
    return not survivors, f"still running: {survivors}" if survivors else "tree gone"


def bootstrap_cases(run: Run, clone: Path) -> None:
    pyproject = clone / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    declared = 'tools = ["black", "ruff", "gitleaks", "shellcheck"]'
    # A project adopting the gate declares its own tools; git is the one every platform here has.
    run.case("bootstrap: gate declaration found", declared in text)
    pyproject.write_text(text.replace(declared, 'tools = ["git"]'), encoding="utf-8")
    boot = "tools/bootstrap.py"

    sh(["git", "config", "--local", "core.hooksPath", "custom hooks"], clone)
    refused = py(boot, "--execute", cwd=clone)
    kept = sh(["git", "config", "--local", "--get", "core.hooksPath"], clone).stdout.strip()
    run.case(
        "bootstrap refuses to replace an existing core.hooksPath",
        refused.returncode == 2 and kept == "custom hooks",
        f"exit {refused.returncode}, hooksPath {kept!r}: {refused.stderr.strip()[-200:]}",
    )
    taken = py(boot, "--execute", "--replace-existing-hooks", cwd=clone)
    check = py(boot, "--check", cwd=clone)
    now = sh(["git", "config", "--local", "--get", "core.hooksPath"], clone).stdout.strip()
    run.case(
        "bootstrap takes over only when told, and --check verifies it",
        taken.returncode == 0 and check.returncode == 0 and now == ".githooks",
        f"execute {taken.returncode}, check {check.returncode}, hooksPath {now!r}: "
        f"{(taken.stderr + check.stderr).strip()[-300:]}",
    )
    removed = py(boot, "--uninstall", cwd=clone)
    back = sh(["git", "config", "--local", "--get", "core.hooksPath"], clone).stdout.strip()
    run.case(
        "bootstrap --uninstall restores the previous hooksPath exactly",
        removed.returncode == 0 and back == "custom hooks",
        f"exit {removed.returncode}, hooksPath {back!r}: {removed.stderr.strip()[-200:]}",
    )
    sh(["git", "config", "--local", "--unset", "core.hooksPath"], clone)
    hook = clone / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hook.chmod(0o755)
    active = py(boot, "--execute", cwd=clone)
    run.case(
        "bootstrap refuses to silence active .git/hooks",
        active.returncode == 2 and "active hook" in active.stderr,
        f"exit {active.returncode}: {active.stderr.strip()[-200:]}",
    )
    hook.unlink()
    pyproject.write_text(text, encoding="utf-8")


def adopt_cases(run: Run, clone: Path, target: Path) -> None:
    adopt = "tools/adopt.py"
    into = ["--into", str(target)]
    guard = target / ".agent-tools" / "command_guard.py"
    guard.parent.mkdir(parents=True)
    guard.write_text("print('someone else')\n", encoding="utf-8")
    conflict = py(adopt, *into, "--execute", cwd=clone)
    run.case(
        "adopt refuses a conflicting guard and writes nothing",
        conflict.returncode == 2
        and "Nothing was written" in conflict.stderr
        and not (target / "CLAUDE.md").exists()
        and not (target / ".sysops-pub").exists(),
        f"exit {conflict.returncode}: {conflict.stderr.strip()[-200:]}",
    )
    guard.unlink()

    settings = target / ".claude" / "settings.json"
    settings.parent.mkdir()
    original = b'{\n  "model": "user-choice",\n  "permissions": {"allow": ["Bash(ls)"]}\n}\n'
    settings.write_bytes(original)
    placed = py(adopt, *into, "--execute", cwd=clone)
    merged = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
    backup = settings.with_name("settings.json.sysops-pub.bak")
    run.case(
        "adopt merges existing settings, keeps the user's keys, and backs them up",
        placed.returncode == 0
        and merged.get("model") == "user-choice"
        and "Bash(ls)" in merged.get("permissions", {}).get("allow", [])
        and "hooks" in merged
        and backup.exists()
        and backup.read_bytes() == original,
        f"exit {placed.returncode}: {placed.stderr.strip()[-200:]}",
    )
    run.case(
        "adopt --check passes right after adoption",
        py(adopt, *into, "--check", cwd=clone).returncode == 0,
    )

    page = target / "PLAYWRIGHT.md"
    page_bytes = page.read_bytes()
    page.write_bytes(page_bytes + b"local edit\n")
    drift = py(adopt, *into, "--check", cwd=clone)
    page.write_bytes(page_bytes)
    clean = py(adopt, *into, "--check", cwd=clone)
    run.case(
        "adopt --check reports drift and clears when it is undone",
        drift.returncode == 1 and "DRIFTED" in drift.stdout and clean.returncode == 0,
        f"drift exit {drift.returncode}, clean exit {clean.returncode}",
    )

    source = clone / "examples" / "claude-code" / "CLAUDE.md.example"
    source.write_bytes(source.read_bytes() + b"\nA newer release line.\n")
    updated = py(adopt, *into, "--execute", cwd=clone)
    run.case(
        "adopt updates a file it placed when the release changes",
        updated.returncode == 0
        and "UPDATED CLAUDE.md" in updated.stdout
        and (target / "CLAUDE.md").read_bytes() == source.read_bytes()
        and py(adopt, *into, "--check", cwd=clone).returncode == 0,
        f"exit {updated.returncode}: {updated.stdout.strip()[-300:]}",
    )

    agents = target / "AGENTS.md"
    agents.write_bytes(agents.read_bytes() + b"the user's own rule\n")
    removed = py(adopt, *into, "--uninstall", "--execute", cwd=clone)
    run.case(
        "adopt --uninstall rolls back: settings restored byte for byte, edits kept, rest removed",
        removed.returncode == 1
        and settings.read_bytes() == original
        and agents.exists()
        and b"the user's own rule" in agents.read_bytes()
        and not (target / "CLAUDE.md").exists()
        and not guard.exists()
        and not (target / ".sysops-pub" / "adoption.json").exists(),
        f"exit {removed.returncode}: {removed.stdout.strip()[-300:]}",
    )


def policy_cases(run: Run, clone: Path) -> None:
    guard = "examples/enforcement/command_guard.py"
    for command, expected in (
        ("rm -rf build", 2),
        ("Remove-Item -Recurse -Force .\\build", 2),
        ("cat ~/.ssh/id_ed25519", 2),
        ("git push origin main | tail -1", 2),
        ("ls build", 0),
        ("Get-Content .\\README.md", 0),
    ):
        result = py(guard, "--command", command, "--json", cwd=clone)
        run.case(
            f"command guard {'blocks' if expected else 'admits'}: {command}",
            result.returncode == expected,
            f"exit {result.returncode}: {result.stdout.strip()[-200:]}",
        )


def process_cases(run: Run, clone: Path, work: Path) -> None:
    job = str(clone / "tools" / "managed_job.py")
    child = work / "grandchild.py"
    child.write_text(GRANDCHILD, encoding="utf-8")

    plain = sh(
        [
            sys.executable,
            job,
            "--receipt",
            str(work / "r0.json"),
            "--",
            sys.executable,
            "-c",
            "pass",
        ],
        work,
    )
    run.case(
        "managed job: a clean job exits 0 with a receipt",
        plain.returncode == 0 and (work / "r0.json").exists(),
    )

    pidfile = work / "timeout.pid"
    timed = sh(
        [
            sys.executable,
            job,
            "--receipt",
            str(work / "r1.json"),
            "--timeout",
            "3",
            "--",
            sys.executable,
            str(child),
            str(pidfile),
            "60",
        ],
        work,
        timeout=60,
    )
    tree_gone, state = tree_state(wait_for(pidfile, 1))
    run.case(
        "managed job: a timeout ends the whole tree, grandchild included",
        timed.returncode == 124 and tree_gone,
        f"exit {timed.returncode}, {state}",
    )

    pidfile = work / "leftover.pid"
    left = sh(
        [
            sys.executable,
            job,
            "--receipt",
            str(work / "r2.json"),
            "--",
            sys.executable,
            str(child),
            str(pidfile),
            "0",
        ],
        work,
        timeout=60,
    )
    tree_gone, state = tree_state(wait_for(pidfile, 1))
    run.case(
        "managed job: a leader that leaves a child behind is not a success, and the child is ended",
        left.returncode == 125 and tree_gone,
        f"exit {left.returncode}, {state}",
    )

    pidfile = work / "cancel.pid"
    # Windows delivers a console break only to a process group of its own; 0 elsewhere.
    runner = subprocess.Popen(
        [
            sys.executable,
            job,
            "--receipt",
            str(work / "r3.json"),
            "--",
            sys.executable,
            str(child),
            str(pidfile),
            "60",
        ],
        cwd=work,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    pids = wait_for(pidfile)
    if WINDOWS:
        os.kill(runner.pid, signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
    else:
        runner.send_signal(signal.SIGTERM)
    try:
        code = runner.wait(timeout=20)
    except subprocess.TimeoutExpired:
        runner.kill()
        code = runner.wait()
    receipt = work / "r3.json"
    tree_gone, state = tree_state(pids)
    run.case(
        "managed job: cancelling the runner ends the tree and still writes a receipt",
        receipt.exists() and tree_gone,
        f"runner exit {code}, receipt {'written' if receipt.exists() else 'MISSING'}, {state}",
    )


def remove_tree(path: Path) -> None:
    def unlock(function, target, _info) -> None:  # git marks objects read-only on Windows
        os.chmod(target, stat.S_IWRITE)
        function(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=unlock)
    else:
        shutil.rmtree(path, onerror=unlock)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        required=True,
        type=Path,
        help="where to write the JSON report; a new path outside this repository",
    )
    parser.add_argument(
        "--keep", action="store_true", help="leave the temporary directory for inspection"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    report = args.report.resolve()
    if report.exists() or report.is_relative_to(REPO_ROOT):
        parser.error("the report must be a new path outside this repository")
    git = sh(["git", "--version"], REPO_ROOT).stdout.strip()
    head = sh(["git", "rev-parse", "HEAD"], REPO_ROOT).stdout.strip()
    run = Run()
    work = Path(tempfile.mkdtemp(prefix="sysops pub acceptance "))
    clone, target = work / "sysops pub clone", work / "target project"
    try:
        cloned = sh(["git", "clone", "-q", "--no-hardlinks", str(REPO_ROOT), str(clone)], work)
        if not run.case(
            "clone HEAD into a path with spaces", cloned.returncode == 0, cloned.stderr
        ):
            raise SystemExit(1)
        target.mkdir()
        suite = py("tools/test.py", cwd=clone, timeout=1200)
        run.case(
            "tools/test.py (unit tests, disclosure scan, demo) passes natively",
            suite.returncode == 0,
            # Whole, in the report: a platform's failures are the finding.
            "" if suite.returncode == 0 else (suite.stdout + suite.stderr).strip(),
        )
        # A section that crashes is a failed case with its traceback, and the rest still run.
        for name, section in (
            ("policy", lambda: policy_cases(run, clone)),
            ("bootstrap", lambda: bootstrap_cases(run, clone)),
            ("adopt", lambda: adopt_cases(run, clone, target)),
            ("process", lambda: process_cases(run, clone, work)),
        ):
            try:
                section()
            except Exception:  # noqa: BLE001 - reported as a failed case, not swallowed
                run.case(f"{name} cases ran to completion", False, traceback.format_exc())
    finally:
        failed = sum(c["result"] == "FAIL" for c in run.cases)
        result = {
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": sys.version,
            "git": git,
            "source_commit": head,
            "native_windows": WINDOWS,
            "wsl": "microsoft" in platform.release().lower(),
            "passed": len(run.cases) - failed,
            "failed": failed,
            "cases": run.cases,
        }
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(
            f"{result['passed']} passed, {failed} failed on {result['platform']}; report {report}"
        )
        if not args.keep:
            remove_tree(work)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
