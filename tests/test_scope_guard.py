from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples" / "enforcement"))

import scope_guard  # noqa: E402


class ScopeGuardTests(unittest.TestCase):
    def test_admits_path_inside_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="scope-guard-") as directory:
            root = Path(directory)
            allowed, reason = scope_guard.decision(root, root / "docs" / "file.md")
            self.assertTrue(allowed)
            self.assertIn("inside", reason)

    def test_blocks_path_outside_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="scope-guard-") as directory:
            root = Path(directory) / "project"
            outside = Path(directory) / "other" / "file.md"
            allowed, reason = scope_guard.decision(root, outside)
            self.assertFalse(allowed)
            self.assertIn("outside", reason)

    def test_executable_fire_proof_blocks_and_admits(self) -> None:
        script = ROOT / "examples" / "enforcement" / "scope_guard.py"
        with tempfile.TemporaryDirectory(prefix="scope-guard-fire-") as directory:
            root = Path(directory) / "project"
            root.mkdir()
            admitted = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--root",
                    str(root),
                    "--path",
                    str(root / "inside.md"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            blocked = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--root",
                    str(root),
                    "--path",
                    str(Path(directory) / "outside.md"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(admitted.returncode, 0, admitted.stderr)
        self.assertIn("ALLOWED", admitted.stdout)
        self.assertEqual(blocked.returncode, 2, blocked.stdout)
        self.assertIn("BLOCKED", blocked.stderr)

    def run_hook(self, script: Path, root: Path, payload: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["CLAUDE_PROJECT_DIR"] = str(root)
        return subprocess.run(
            [sys.executable, str(script), "--claude-hook"],
            input=payload,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def test_hook_process_blocks_and_admits_real_payloads(self) -> None:
        script = ROOT / "examples" / "enforcement" / "scope_guard.py"
        with tempfile.TemporaryDirectory(prefix="scope-guard-hook-") as directory:
            root = Path(directory) / "project"
            root.mkdir()
            admitted = self.run_hook(
                script,
                root,
                json.dumps({"tool_input": {"file_path": str(root / "inside.md")}}),
            )
            blocked = self.run_hook(
                script,
                root,
                json.dumps({"tool_input": {"file_path": str(Path(directory) / "outside.md")}}),
            )
        self.assertEqual(admitted.returncode, 0, admitted.stderr)
        self.assertIn("ALLOWED", admitted.stdout)
        self.assertEqual(blocked.returncode, 2, blocked.stdout)
        self.assertIn("BLOCKED", blocked.stderr)

    def test_hook_process_fails_closed_without_path(self) -> None:
        script = ROOT / "examples" / "enforcement" / "scope_guard.py"
        with tempfile.TemporaryDirectory(prefix="scope-guard-hook-") as directory:
            result = self.run_hook(script, Path(directory), json.dumps({"tool_input": {}}))
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("no supported write path", result.stderr)

    def test_hook_process_fails_closed_on_invalid_json(self) -> None:
        script = ROOT / "examples" / "enforcement" / "scope_guard.py"
        with tempfile.TemporaryDirectory(prefix="scope-guard-hook-") as directory:
            result = self.run_hook(script, Path(directory), "not-json")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("invalid hook JSON", result.stderr)


if __name__ == "__main__":
    unittest.main()
