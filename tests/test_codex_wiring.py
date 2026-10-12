from __future__ import annotations

import contextlib
import io
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


def _patch(*headers: str) -> str:
    return "*** Begin Patch\n" + "\n".join(headers) + "\n@@\n-old\n+new\n*** End Patch\n"


class CodexWiringTests(unittest.TestCase):
    """The adopted Codex hooks are shell strings; prove they reach the guards through a real shell."""

    @unittest.skipIf(os.name == "nt", "the Codex hook commands are POSIX shell strings")
    def test_adopted_codex_hooks_reach_the_guards_through_a_real_shell(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-wiring-") as directory:
            target = Path(directory) / "bundle"
            with contextlib.redirect_stdout(io.StringIO()):
                result = adopt.main(["--target", str(target), "--tool", "codex", "--execute"])
            self.assertEqual(result, 0)
            project = target / "codex"
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            hooks = json.loads((project / ".codex" / "hooks.json").read_text(encoding="utf-8"))
            commands = {
                entry["matcher"]: [handler["command"] for handler in entry["hooks"]]
                for entry in hooks["hooks"]["PreToolUse"]
            }
            self.assertEqual(set(commands), {"apply_patch", "Bash"})

            def run(command: str, payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    ["sh", "-c", command],
                    cwd=project,
                    input=json.dumps(
                        {"session_id": "codex-wiring", "cwd": str(project), **payload}
                    ),
                    check=False,
                    capture_output=True,
                    text=True,
                )

            (scope,) = commands["apply_patch"]
            inside = run(
                scope,
                {
                    "tool_name": "apply_patch",
                    "tool_input": {"command": _patch("*** Update File: AGENTS.md")},
                },
            )
            outside = run(
                scope,
                {
                    "tool_name": "apply_patch",
                    "tool_input": {"command": _patch("*** Add File: ../escape.md")},
                },
            )
            self.assertEqual(inside.returncode, 0, inside.stderr)
            self.assertIn("ALLOWED", inside.stdout)
            self.assertEqual(outside.returncode, 2, outside.stdout)
            self.assertIn("outside the project root", outside.stderr)

            (guard,) = commands["Bash"]
            blocked = run(guard, {"tool_name": "Bash", "tool_input": {"command": "rm -rf build"}})
            admitted = run(guard, {"tool_name": "Bash", "tool_input": {"command": "ls"}})
            self.assertEqual(blocked.returncode, 2, blocked.stdout)
            self.assertIn("dangerous command", blocked.stderr)
            self.assertEqual(admitted.returncode, 0, admitted.stderr)

    def test_into_places_codex_hooks_and_the_shared_guards_once(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-wiring-") as directory:
            project = Path(directory) / "proj"
            project.mkdir()
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = adopt.main(
                    ["--into", str(project), "--tool", "both", "--platform", "posix", "--execute"]
                )
            self.assertEqual(result, 0)
            self.assertTrue((project / ".codex" / "hooks.json").is_file())
            for name in ("scope_guard.py", "command_guard.py", "read_guard.py"):
                with self.subTest(name=name):
                    self.assertTrue((project / ".agent-tools" / name).is_file())
            self.assertEqual(stdout.getvalue().count("PLACED .agent-tools/scope_guard.py"), 1)
            self.assertEqual(stdout.getvalue().count("PLACED .agent-tools/command_guard.py"), 1)


if __name__ == "__main__":
    unittest.main()
