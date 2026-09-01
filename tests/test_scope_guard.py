from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
