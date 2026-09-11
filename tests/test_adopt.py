from __future__ import annotations

import contextlib
import hashlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import adopt  # noqa: E402


class AdoptionTests(unittest.TestCase):
    def run_adopt(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = adopt.main(list(arguments))
        return result, stdout.getvalue(), stderr.getvalue()

    def test_dry_run_does_not_create_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-adopt-") as directory:
            target = Path(directory) / "bundle"
            result, stdout, stderr = self.run_adopt("--target", str(target))
            self.assertEqual(result, 0, stderr)
            self.assertIn("WOULD COPY", stdout)
            self.assertFalse(target.exists())

    def test_execute_builds_both_posix_bundles(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-adopt-") as directory:
            target = Path(directory) / "bundle"
            result, _stdout, stderr = self.run_adopt(
                "--target", str(target), "--platform", "posix", "--execute"
            )
            self.assertEqual(result, 0, stderr)
            self.assertTrue((target / "claude-code" / "CLAUDE.md").is_file())
            self.assertTrue((target / "claude-code" / "PLAYWRIGHT.md").is_file())
            self.assertTrue((target / "claude-code" / ".agent-tools" / "scope_guard.py").is_file())
            self.assertTrue((target / "claude-code" / ".claude" / "settings.json").is_file())
            self.assertTrue((target / "codex" / "AGENTS.md").is_file())
            self.assertTrue((target / "codex" / "review.config.toml.example").is_file())
            self.assertEqual(
                hashlib.sha256((target / "claude-code" / "CLAUDE.md").read_bytes()).hexdigest(),
                hashlib.sha256(
                    (ROOT / "examples" / "claude-code" / "CLAUDE.md.example").read_bytes()
                ).hexdigest(),
            )
            claude_instructions = (target / "claude-code" / "CLAUDE.md").read_text(encoding="utf-8")
            codex_instructions = (target / "codex" / "AGENTS.md").read_text(encoding="utf-8")
            codex_review_profile = (target / "codex" / "review.config.toml.example").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("Read `AGENTS.md`", claude_instructions)
            self.assertNotIn("tools/test.py", codex_instructions)
            self.assertIn('sandbox_mode = "read-only"', codex_review_profile)
            self.assertIn("developer_instructions", codex_review_profile)
            settings = (target / "claude-code" / ".claude" / "settings.json").read_text(
                encoding="utf-8"
            )
            self.assertIn("python3", settings)
            self.assertIn('"Artifact"', settings)

    def test_windows_bundle_selects_python_launcher(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-adopt-") as directory:
            target = Path(directory) / "bundle"
            result, _stdout, stderr = self.run_adopt(
                "--target",
                str(target),
                "--tool",
                "claude-code",
                "--platform",
                "windows",
                "--execute",
            )
            self.assertEqual(result, 0, stderr)
            settings = (target / "claude-code" / ".claude" / "settings.json").read_text(
                encoding="utf-8"
            )
            self.assertIn('"command": "py"', settings)
            self.assertIn('"-3"', settings)
            self.assertIn('"Artifact"', settings)

    def test_execute_refuses_any_existing_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-adopt-") as directory:
            target = Path(directory) / "bundle"
            target.mkdir()
            result, _stdout, stderr = self.run_adopt("--target", str(target), "--execute")
            self.assertEqual(result, 2)
            self.assertIn("new target path", stderr)

    def test_copy_failure_leaves_no_partial_target_or_staging_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-adopt-") as directory:
            parent = Path(directory)
            target = parent / "bundle"
            real_copy = adopt.shutil.copyfile
            calls = 0

            def fail_second_copy(source: Path, destination: Path) -> str:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("synthetic copy failure")
                return str(real_copy(source, destination))

            with mock.patch.object(adopt.shutil, "copyfile", side_effect=fail_second_copy):
                result, _stdout, stderr = self.run_adopt(
                    "--target", str(target), "--platform", "posix", "--execute"
                )
            self.assertEqual(result, 2)
            self.assertIn("synthetic copy failure", stderr)
            self.assertFalse(target.exists())
            self.assertEqual(
                [path for path in parent.iterdir() if path.name.startswith(".bundle-")], []
            )

    def test_refuses_target_that_contains_repository(self) -> None:
        result, _stdout, stderr = self.run_adopt("--target", str(ROOT.parent))
        self.assertEqual(result, 2)
        self.assertIn("may not contain", stderr)


if __name__ == "__main__":
    unittest.main()
