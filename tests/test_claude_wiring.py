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


def _hook_command(settings: dict[str, object]) -> tuple[str, list[str]]:
    hooks = settings["hooks"]
    assert isinstance(hooks, dict)
    pre_tool_use = hooks["PreToolUse"]
    assert isinstance(pre_tool_use, list)
    entry = pre_tool_use[0]
    assert isinstance(entry, dict)
    commands = entry["hooks"]
    assert isinstance(commands, list)
    command = commands[0]
    assert isinstance(command, dict)
    value = command["command"]
    assert isinstance(value, str)
    args = command["args"]
    assert isinstance(args, list)
    assert all(isinstance(item, str) for item in args)
    return value, args


def _expanded_hook_command(settings: dict[str, object], project: Path) -> list[str]:
    command, args = _hook_command(settings)
    placeholder = "${CLAUDE_PROJECT_DIR}"
    return [command, *(argument.replace(placeholder, str(project)) for argument in args)]


class ClaudeWiringTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "POSIX settings execute through a POSIX shell")
    def test_adopted_posix_settings_wire_a_real_block_and_admit_proof(self) -> None:
        with tempfile.TemporaryDirectory(prefix="claude-wiring-") as directory:
            target = Path(directory) / "bundle"
            self.assertEqual(
                adopt.main(
                    [
                        "--target",
                        str(target),
                        "--tool",
                        "claude-code",
                        "--platform",
                        "posix",
                        "--execute",
                    ]
                ),
                0,
            )
            project = target / "claude-code"
            settings = json.loads(
                (project / ".claude" / "settings.json").read_text(encoding="utf-8")
            )
            entry = settings["hooks"]["PreToolUse"][0]
            self.assertEqual(entry["matcher"], "Write|Edit")
            self.assertEqual(settings["permissions"]["deny"], ["Artifact"])
            command = _expanded_hook_command(settings, project)
            environment = os.environ.copy()
            environment["CLAUDE_PROJECT_DIR"] = str(project)

            admitted = subprocess.run(
                command,
                input=json.dumps({"tool_input": {"file_path": str(project / "inside.md")}}),
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            blocked = subprocess.run(
                command,
                input=json.dumps(
                    {"tool_input": {"file_path": str(Path(directory) / "outside.md")}}
                ),
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(admitted.returncode, 0, admitted.stderr)
            self.assertEqual(blocked.returncode, 2, blocked.stdout)
            self.assertIn("BLOCKED", blocked.stderr)

    def test_windows_bundle_has_design_level_hook_wiring(self) -> None:
        with tempfile.TemporaryDirectory(prefix="claude-wiring-") as directory:
            target = Path(directory) / "bundle"
            self.assertEqual(
                adopt.main(
                    [
                        "--target",
                        str(target),
                        "--tool",
                        "claude-code",
                        "--platform",
                        "windows",
                        "--execute",
                    ]
                ),
                0,
            )
            project = target / "claude-code"
            settings = json.loads(
                (project / ".claude" / "settings.json").read_text(encoding="utf-8")
            )
            entry = settings["hooks"]["PreToolUse"][0]
            self.assertEqual(entry["matcher"], "Write|Edit")
            self.assertEqual(settings["permissions"]["deny"], ["Artifact"])
            command, args = _hook_command(settings)
            self.assertEqual(command, "py")
            self.assertEqual(args[0], "-3")
            self.assertEqual(args[1], "${CLAUDE_PROJECT_DIR}/.agent-tools/scope_guard.py")
            self.assertEqual(args[2], "--claude-hook")
            self.assertTrue((project / ".agent-tools" / "scope_guard.py").is_file())


if __name__ == "__main__":
    unittest.main()
