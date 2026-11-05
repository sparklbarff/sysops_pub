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

Cases belong to a population. The original 23 are "baseline"; the four added after the
2026-11-05 lifecycle audit are "lifecycle". The report counts each population separately, and
--population runs one of them, so results for the new cases never change what was recorded for the
baseline. The lifecycle cases build their repositories locally and read no Git configuration but
their own.
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


POPULATIONS = ("baseline", "lifecycle")


class Run:
    def __init__(self) -> None:
        self.cases: list[dict[str, object]] = []
        self.population = "baseline"

    def case(self, name: str, ok: bool, detail: str = "") -> bool:
        self.cases.append(
            {
                "case": name,
                "population": self.population,
                "result": "PASS" if ok else "FAIL",
                "detail": detail,
            }
        )
        print(f"{'PASS' if ok else 'FAIL'}  {name}{': ' + detail if detail and not ok else ''}")
        return ok


def sh(
    args: list[str],
    cwd: Path,
    timeout: float = 120,
    capture: bool = True,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """capture=False for jobs whose children may outlive them: a survivor holding the output
    pipe open would turn a failed case into a hang."""
    if not capture:
        return subprocess.run(
            args,
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
        input=stdin,
    )


def py(
    script: str,
    *args: str,
    cwd: Path,
    timeout: float = 120,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return sh([sys.executable, script, *args], cwd=cwd, timeout=timeout, env=env, stdin=stdin)


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
        capture=False,
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
        capture=False,
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
        capture=False,
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
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
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


def isolated_git(work: Path, global_config: Path | None = None) -> dict[str, str]:
    """An environment in which Git reads no configuration but the repository's own and, when
    given, one synthetic global file: the owner's real settings can neither help nor hurt."""
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = str(global_config or work / "empty global gitconfig")
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def git_commit(repo: Path, env: dict[str, str], message: str) -> str:
    sh(["git", "add", "-A"], repo, env=env)
    sh(
        [
            "git",
            "-c",
            "user.name=example-user",
            "-c",
            "user.email=example" + "@" + "example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            message,
        ],
        repo,
        env=env,
    )
    return sh(["git", "rev-parse", "HEAD"], repo, env=env).stdout.strip()


def outgoing_count(result: subprocess.CompletedProcess[str]) -> int | None:
    """How many commits a pre-push run inspected, verified or remembered, from its own summary."""
    if "no outgoing commits require verification" in result.stdout:
        return 0
    for line in result.stdout.splitlines():
        if line.startswith("pre-push: verified "):
            words = line.replace(",", "").split()
            verified = int(words[2])
            remembered = int(words[5]) if "already" in line else 0
            return verified + remembered
    return None


def lifecycle_settings_case(run: Run, clone: Path, work: Path, env: dict[str, str]) -> None:
    """Adopt over existing settings, edit them, adopt again, uninstall: the edit must survive.
    Adopt, edit, uninstall with no second adoption is the control."""
    original = b'{\n  "model": "user-choice"\n}\n'
    outcomes = {}
    for label, readopt in (("re-adopted", True), ("control, direct uninstall", False)):
        project = work / f"settings project {label}"
        settings = project / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_bytes(original)
        into = ["--into", str(project)]
        first = py("tools/adopt.py", *into, "--execute", cwd=clone, env=env)
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["user_edit"] = "made after adoption"
        settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        second = py("tools/adopt.py", *into, "--execute", cwd=clone, env=env) if readopt else None
        removed = py("tools/adopt.py", *into, "--uninstall", "--execute", cwd=clone, env=env)
        after = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
        outcomes[label] = (
            first.returncode == 0
            and (second is None or second.returncode == 0)
            and after.get("user_edit") == "made after adoption",
            (
                f"{label}: adopt {first.returncode}, "
                f"re-adopt {second.returncode if second else '-'}, "
                f"uninstall {removed.returncode}, "
                f"edit {'kept' if after.get('user_edit') else 'LOST'}"
            ),
        )
    run.case(
        "adopt keeps a settings edit made after adoption through re-adoption and uninstall",
        all(ok for ok, _ in outcomes.values()),
        "; ".join(detail for _, detail in outcomes.values()),
    )


def lifecycle_push_case(run: Run, clone: Path, work: Path, env: dict[str, str]) -> None:
    """Point a named remote at a new, empty repository while tracking refs for the old one
    remain: inspection through the name and through the location must both find the one commit.
    A remote whose push URL differs from its fetch URL is the control.

    These repositories live in their own directory with no spaces in its name: an earlier driver
    split the remote's URL list on whitespace, so a location containing a space never matched and
    hid the stale-tracking-ref defect this case exists to catch."""
    base = Path(tempfile.mkdtemp(prefix="sysops-pub-push-"))
    try:
        lifecycle_push_steps(run, clone, base, env)
    finally:
        remove_tree(base)


def lifecycle_push_steps(run: Run, clone: Path, work: Path, env: dict[str, str]) -> None:
    repo = work / "repo"
    old, new = work / "old.git", work / "new.git"
    for bare in (old, new):
        sh(["git", "init", "-q", "--bare", str(bare)], work, env=env)
    sh(["git", "init", "-q", "-b", "main", str(repo)], work, env=env)
    (repo / "tools").mkdir()
    shutil.copyfile(clone / "tools" / "pre_push.py", repo / "tools" / "pre_push.py")
    (repo / "pyproject.toml").write_text(
        '[tool.sysops_pub.gate]\ncommand = ["python3", "-c", "pass"]\n', encoding="utf-8"
    )
    commit = git_commit(repo, env, "the one outgoing commit")
    sh(["git", "remote", "add", "origin", str(old)], repo, env=env)
    target = Path(
        sh(["git", "remote", "get-url", "--push", "origin"], repo, env=env).stdout.strip()
    )
    if not target.resolve().is_relative_to(work.resolve()):
        raise RuntimeError(f"refusing to push outside the case's directory: {target}")
    sh(["git", "push", "-q", "origin", "main"], repo, env=env)
    sh(["git", "remote", "set-url", "origin", str(new)], repo, env=env)
    protocol = f"refs/heads/main {commit} refs/heads/main {'0' * 40}\n"
    memo = repo / ".git" / "sysops-pub-verified-gates"

    def inspect(name: str, location: str) -> tuple[int | None, str]:
        memo.unlink(missing_ok=True)
        result = py("tools/pre_push.py", name, location, cwd=repo, env=env, stdin=protocol)
        return outgoing_count(result), (result.stdout + result.stderr).strip()[-200:]

    named, named_out = inspect("origin", str(new))
    direct, direct_out = inspect(str(new), str(new))
    sh(["git", "remote", "add", "split", str(old)], repo, env=env)
    sh(["git", "fetch", "-q", "split"], repo, env=env)
    sh(["git", "remote", "set-url", "--push", "split", str(new)], repo, env=env)
    split, split_out = inspect("split", str(new))
    run.case(
        "push inspection reads the receiving destination: named, direct and split push agree",
        named == direct == split == 1,
        f"named {named} ({named_out}); direct {direct} ({direct_out}); "
        f"control split push {split} ({split_out})",
    )


def lifecycle_helper_case(run: Run, clone: Path, work: Path, env: dict[str, str]) -> None:
    """Helpers the installed hooks run were already in the project, identical, before adoption.
    A change to one must show as drift, and uninstall must keep both; the unchanged one is the
    control."""
    project = work / "helper project"
    tools = project / ".agent-tools"
    tools.mkdir(parents=True)
    changed, unchanged = tools / "scope_guard.py", tools / "command_guard.py"
    for helper in (changed, unchanged):
        shutil.copyfile(clone / "examples" / "enforcement" / helper.name, helper)
    into = ["--into", str(project)]
    adopted = py("tools/adopt.py", *into, "--execute", cwd=clone, env=env)
    before = py("tools/adopt.py", *into, "--check", cwd=clone, env=env)
    edited = changed.read_bytes() + b"# changed after adoption\n"
    changed.write_bytes(edited)
    after = py("tools/adopt.py", *into, "--check", cwd=clone, env=env)
    removed = py("tools/adopt.py", *into, "--uninstall", "--execute", cwd=clone, env=env)
    reported = any(
        line.startswith("DRIFTED") and ".agent-tools/scope_guard.py" in line
        for line in after.stdout.splitlines()
    )
    run.case(
        "adopt reports drift in a pre-existing wired helper and keeps both helpers on uninstall",
        adopted.returncode == 0
        and before.returncode == 0
        and after.returncode == 1
        and reported
        and changed.exists()
        and changed.read_bytes() == edited
        and unchanged.exists(),
        f"adopt {adopted.returncode}, check before {before.returncode}, check after "
        f"{after.returncode} ({'drift named' if reported else 'drift NOT named'}), uninstall "
        f"{removed.returncode}, changed helper {'kept' if changed.exists() else 'REMOVED'}, "
        f"unchanged helper {'kept' if unchanged.exists() else 'REMOVED'}",
    )


def lifecycle_hooks_case(run: Run, clone: Path, work: Path) -> None:
    """A hooks path inherited from global configuration is the owner's binding: the preview must
    name it and an ordinary install must leave it in force. Explicit takeover and its uninstall
    are the controls."""
    inherited = (work / "inherited hooks").as_posix()
    global_config = work / "inherited global gitconfig"
    global_config.write_text(f'[core]\n\thooksPath = "{inherited}"\n', encoding="utf-8")
    env = isolated_git(work, global_config)
    pyproject = clone / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    declared = 'tools = ["black", "ruff", "gitleaks", "shellcheck"]'
    pyproject.write_text(text.replace(declared, 'tools = ["git"]'), encoding="utf-8")
    sh(["git", "config", "--local", "--unset", "core.hooksPath"], clone, env=env)

    def binding() -> tuple[str, str]:
        local = sh(["git", "config", "--local", "--get", "core.hooksPath"], clone, env=env)
        effective = sh(["git", "config", "--get", "core.hooksPath"], clone, env=env)
        return local.stdout.strip(), effective.stdout.strip()

    try:
        boot = "tools/bootstrap.py"
        preview = py(boot, cwd=clone, env=env)
        refused = py(boot, "--execute", cwd=clone, env=env)
        after_refusal = binding()
        taken = py(boot, "--execute", "--replace-existing-hooks", cwd=clone, env=env)
        after_takeover = binding()
        removed = py(boot, "--uninstall", cwd=clone, env=env)
        after_uninstall = binding()
    finally:
        pyproject.write_text(text, encoding="utf-8")
        sh(["git", "config", "--local", "--unset", "core.hooksPath"], clone, env=env)
    named = inherited in preview.stdout
    run.case(
        "bootstrap previews and preserves an inherited hooks path; takeover and uninstall still work",
        named
        and refused.returncode == 2
        and after_refusal == ("", inherited)
        and taken.returncode == 0
        and after_takeover == (".githooks", ".githooks")
        and removed.returncode == 0
        and after_uninstall == ("", inherited),
        f"preview {'names' if named else 'does NOT name'} the inherited path; plain install exit "
        f"{refused.returncode}, then local/effective {after_refusal}; takeover exit "
        f"{taken.returncode}, then {after_takeover}; uninstall exit {removed.returncode}, then "
        f"{after_uninstall}",
    )


def lifecycle_cases(run: Run, clone: Path, work: Path) -> None:
    run.population = "lifecycle"
    env = isolated_git(work)
    for name, case in (
        ("settings", lambda: lifecycle_settings_case(run, clone, work, env)),
        ("push", lambda: lifecycle_push_case(run, clone, work, env)),
        ("helper", lambda: lifecycle_helper_case(run, clone, work, env)),
        ("hooks", lambda: lifecycle_hooks_case(run, clone, work)),
    ):
        try:
            case()
        except Exception:  # noqa: BLE001 - reported as a failed case, not swallowed
            run.case(f"lifecycle {name} case ran to completion", False, traceback.format_exc())


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
    parser.add_argument(
        "--population",
        choices=("all", *POPULATIONS),
        default="all",
        help="which cases to run: the original baseline 23, the lifecycle cases, or all",
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
    baseline = args.population in ("all", "baseline")
    try:
        cloned = sh(["git", "clone", "-q", "--no-hardlinks", str(REPO_ROOT), str(clone)], work)
        if baseline:
            if not run.case(
                "clone HEAD into a path with spaces", cloned.returncode == 0, cloned.stderr
            ):
                raise SystemExit(1)
        elif cloned.returncode:
            raise SystemExit(f"could not clone HEAD: {cloned.stderr}")
        target.mkdir()
        if baseline:
            suite = py("tools/test.py", cwd=clone, timeout=1200)
            run.case(
                "tools/test.py (unit tests, disclosure scan, demo) passes natively",
                suite.returncode == 0,
                # Whole, in the report: a platform's failures are the finding.
                "" if suite.returncode == 0 else (suite.stdout + suite.stderr).strip(),
            )
        # A section that crashes is a failed case with its traceback, and the rest still run.
        sections = []
        if baseline:
            sections += [
                ("policy", lambda: policy_cases(run, clone)),
                ("bootstrap", lambda: bootstrap_cases(run, clone)),
                ("adopt", lambda: adopt_cases(run, clone, target)),
                ("process", lambda: process_cases(run, clone, work)),
            ]
        if args.population in ("all", "lifecycle"):
            sections.append(("lifecycle", lambda: lifecycle_cases(run, clone, work)))
        for name, section in sections:
            try:
                section()
            except Exception:  # noqa: BLE001 - reported as a failed case, not swallowed
                run.case(f"{name} cases ran to completion", False, traceback.format_exc())
    finally:
        failed = sum(c["result"] == "FAIL" for c in run.cases)
        by_population = {
            name: {
                "passed": sum(c["population"] == name and c["result"] == "PASS" for c in run.cases),
                "failed": sum(c["population"] == name and c["result"] == "FAIL" for c in run.cases),
            }
            for name in POPULATIONS
            if any(c["population"] == name for c in run.cases)
        }
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
            "population": args.population,
            "passed": len(run.cases) - failed,
            "failed": failed,
            "by_population": by_population,
            "cases": run.cases,
        }
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        for name, counts in by_population.items():
            print(f"{name}: {counts['passed']} passed, {counts['failed']} failed")
        print(
            f"{result['passed']} passed, {failed} failed on {result['platform']}; report {report}"
        )
        if not args.keep:
            remove_tree(work)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
