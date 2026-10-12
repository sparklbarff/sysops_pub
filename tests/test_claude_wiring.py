from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import adopt

PLACEHOLDER = "${CLAUDE_PROJECT_DIR}"


def _hook_commands(settings: dict[str, object], event: str) -> dict[str, list[list[str]]]:
    """Every wired command for the event, keyed by its matcher, as (command, *args) lists."""
    hooks = settings["hooks"]
    assert isinstance(hooks, dict)
    entries = hooks[event]
    assert isinstance(entries, list)
    wired: dict[str, list[list[str]]] = {}
    for entry in entries:
        assert isinstance(entry, dict)
        matcher = entry["matcher"]
        assert isinstance(matcher, str)
        commands = entry["hooks"]
        assert isinstance(commands, list)
        for command in commands:
            assert isinstance(command, dict)
            value = command["command"]
            args = command["args"]
            assert isinstance(value, str) and isinstance(args, list)
            assert all(isinstance(item, str) for item in args)
            wired.setdefault(matcher, []).append([value, *args])
    return wired


def _expanded(command: list[str], project: Path) -> list[str]:
    return [argument.replace(PLACEHOLDER, str(project)) for argument in command]


def _bundle(directory: str, platform: str) -> tuple[Path, dict[str, object]]:
    target = Path(directory) / "bundle"
    result = adopt.main(
        ["--target", str(target), "--tool", "claude-code", "--platform", platform, "--execute"]
    )
    assert result == 0
    project = target / "claude-code"
    settings = json.loads((project / ".claude" / "settings.json").read_text(encoding="utf-8"))
    return project, settings


class ClaudeWiringTests(unittest.TestCase):
    """The adopted settings must reach real guards: each wired command is run as a process."""

    def run_wired(
        self, command: list[str], project: Path, payload: dict[str, object], state: Path
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["CLAUDE_PROJECT_DIR"] = str(project)
        environment["SYSOPS_PUB_GUARD_STATE"] = str(state)
        return subprocess.run(
            command,
            input=json.dumps({"session_id": "wiring-test", "cwd": str(project), **payload}),
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    @unittest.skipIf(os.name == "nt", "POSIX settings execute through a POSIX shell")
    def test_adopted_posix_settings_wire_the_scope_guard_with_a_block_and_admit_proof(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="claude-wiring-") as directory:
            project, settings = _bundle(directory, "posix")
            self.assertEqual(settings["permissions"]["deny"], ["Artifact"])
            wired = _hook_commands(settings, "PreToolUse")
            (command,) = wired["Write|Edit|NotebookEdit"]
            command = _expanded(command, project)
            state = Path(directory) / "state"
            admitted = self.run_wired(
                command,
                project,
                {"tool_name": "Write", "tool_input": {"file_path": str(project / "inside.md")}},
                state,
            )
            blocked = self.run_wired(
                command,
                project,
                {
                    "tool_name": "Write",
                    "tool_input": {"file_path": str(Path(directory) / "outside.md")},
                },
                state,
            )
            self.assertEqual(admitted.returncode, 0, admitted.stderr)
            self.assertEqual(blocked.returncode, 2, blocked.stdout)
            self.assertIn("BLOCKED", blocked.stderr)

    @unittest.skipIf(os.name == "nt", "POSIX settings execute through a POSIX shell")
    def test_adopted_posix_settings_wire_the_command_guard_for_bash_and_fetches(self) -> None:
        with tempfile.TemporaryDirectory(prefix="claude-wiring-") as directory:
            project, settings = _bundle(directory, "posix")
            wired = _hook_commands(settings, "PreToolUse")
            state = Path(directory) / "state"
            bash_commands = [_expanded(command, project) for command in wired["Bash"]]
            self.assertEqual(len(bash_commands), 2)
            guard = next(command for command in bash_commands if "command_guard.py" in command[1])
            blocked = self.run_wired(
                guard, project, {"tool_name": "Bash", "tool_input": {"command": "rm -rf x"}}, state
            )
            admitted = self.run_wired(
                guard, project, {"tool_name": "Bash", "tool_input": {"command": "ls"}}, state
            )
            self.assertEqual(blocked.returncode, 2, blocked.stdout)
            self.assertIn("dangerous command", blocked.stderr)
            self.assertEqual(admitted.returncode, 0, admitted.stderr)
            (fetch,) = wired["WebFetch"]
            fetch = _expanded(fetch, project)
            private = self.run_wired(
                fetch,
                project,
                {"tool_name": "WebFetch", "tool_input": {"url": "http://localhost/"}},
                state,
            )
            self.assertEqual(private.returncode, 2, private.stdout)
            self.assertIn("private address", private.stderr)

    @unittest.skipIf(os.name == "nt", "POSIX settings execute through a POSIX shell")
    def test_adopted_posix_settings_wire_the_read_guard_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory(prefix="claude-wiring-") as directory:
            project, settings = _bundle(directory, "posix")
            pre = _hook_commands(settings, "PreToolUse")
            post = _hook_commands(settings, "PostToolUse")
            state = Path(directory) / "state"
            (check,) = pre["Edit|NotebookEdit"]
            check = _expanded(check, project)
            (record,) = post["Read|Write|Edit|NotebookEdit"]
            record = _expanded(record, project)
            (shell,) = [
                _expanded(command, project)
                for command in pre["Bash"]
                if "read_guard.py" in command[1]
            ]
            target = project / "CLAUDE.md"
            edit = {"tool_name": "Edit", "tool_input": {"file_path": str(target)}}
            read = {"tool_name": "Read", "tool_input": {"file_path": str(target)}}
            unread = self.run_wired(check, project, edit, state)
            self.assertEqual(unread.returncode, 2, unread.stdout)
            self.assertIn("has not been read", unread.stderr)
            self.assertEqual(self.run_wired(record, project, read, state).returncode, 0)
            self.assertEqual(self.run_wired(check, project, edit, state).returncode, 0)
            target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            stale = self.run_wired(check, project, edit, state)
            self.assertEqual(stale.returncode, 2, stale.stdout)
            routed = self.run_wired(
                shell,
                project,
                {"tool_name": "Bash", "tool_input": {"command": "sed -i s/a/b/ CLAUDE.md"}},
                state,
            )
            self.assertEqual(routed.returncode, 2, routed.stdout)
            self.assertIn("pending stale-read block", routed.stderr)
            self.assertEqual(self.run_wired(record, project, read, state).returncode, 0)
            self.assertEqual(self.run_wired(check, project, edit, state).returncode, 0)

    def test_windows_bundle_has_design_level_hook_wiring(self) -> None:
        with tempfile.TemporaryDirectory(prefix="claude-wiring-") as directory:
            project, settings = _bundle(directory, "windows")
            self.assertEqual(settings["permissions"]["deny"], ["Artifact"])
            pre = _hook_commands(settings, "PreToolUse")
            post = _hook_commands(settings, "PostToolUse")
            self.assertEqual(
                set(pre), {"Write|Edit|NotebookEdit", "Edit|NotebookEdit", "Bash", "WebFetch"}
            )
            self.assertEqual(set(post), {"Read|Write|Edit|NotebookEdit"})
            for commands in [*pre.values(), *post.values()]:
                for command in commands:
                    with self.subTest(command=command):
                        self.assertEqual(command[:2], ["py", "-3"])
                        self.assertTrue(command[2].startswith(f"{PLACEHOLDER}/.agent-tools/"))
                        self.assertEqual(command[-1], "--claude-hook")
                        placed = project / ".agent-tools" / Path(command[2]).name
                        self.assertTrue(placed.is_file(), placed)


if __name__ == "__main__":
    unittest.main()
