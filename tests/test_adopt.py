from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import adopt


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

    def test_into_installs_into_a_fresh_project(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-into-") as directory:
            project = Path(directory) / "proj"
            project.mkdir()
            result, _stdout, stderr = self.run_adopt(
                "--into", str(project), "--platform", "posix", "--execute"
            )
            self.assertEqual(result, 0, stderr)
            self.assertTrue((project / "CLAUDE.md").is_file())
            self.assertTrue((project / ".agent-tools" / "scope_guard.py").is_file())
            self.assertTrue((project / "AGENTS.md").is_file())
            settings = json.loads((project / ".claude" / "settings.json").read_text("utf-8"))
            self.assertIn("Artifact", settings["permissions"]["deny"])
            self.assertIn("PreToolUse", settings["hooks"])

    def test_into_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-into-") as directory:
            project = Path(directory) / "proj"
            project.mkdir()
            result, stdout, stderr = self.run_adopt("--into", str(project))
            self.assertEqual(result, 0, stderr)
            self.assertIn("WOULD", stdout)
            self.assertEqual(list(project.iterdir()), [])

    def test_into_never_overwrites_an_existing_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-into-") as directory:
            project = Path(directory) / "proj"
            project.mkdir()
            existing = project / "CLAUDE.md"
            existing.write_text("my own instructions\n", encoding="utf-8")
            result, stdout, stderr = self.run_adopt(
                "--into", str(project), "--tool", "claude-code", "--execute"
            )
            self.assertEqual(result, 0, stderr)
            self.assertEqual(existing.read_text(encoding="utf-8"), "my own instructions\n")
            self.assertIn("PRESENT-DIFFERS-SKIP", stdout)

    def test_into_merges_settings_preserving_user_keys_and_backs_up(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-into-") as directory:
            project = Path(directory) / "proj"
            (project / ".claude").mkdir(parents=True)
            settings_path = project / ".claude" / "settings.json"
            settings_path.write_text(
                json.dumps({"permissions": {"deny": ["SomethingElse"]}, "model": "my-model"}),
                encoding="utf-8",
            )
            result, _stdout, stderr = self.run_adopt(
                "--into", str(project), "--tool", "claude-code", "--execute"
            )
            self.assertEqual(result, 0, stderr)
            merged = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertIn("SomethingElse", merged["permissions"]["deny"])
            self.assertIn("Artifact", merged["permissions"]["deny"])
            self.assertEqual(merged["model"], "my-model")
            self.assertIn("PreToolUse", merged["hooks"])
            backup = settings_path.with_name("settings.json.sysops-pub.bak")
            self.assertTrue(backup.is_file())
            self.assertEqual(
                json.loads(backup.read_text(encoding="utf-8"))["permissions"]["deny"],
                ["SomethingElse"],
            )

    def test_into_settings_merge_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-into-") as directory:
            project = Path(directory) / "proj"
            project.mkdir()
            self.run_adopt("--into", str(project), "--tool", "claude-code", "--execute")
            first = (project / ".claude" / "settings.json").read_text(encoding="utf-8")
            result, stdout, stderr = self.run_adopt(
                "--into", str(project), "--tool", "claude-code", "--execute"
            )
            self.assertEqual(result, 0, stderr)
            self.assertEqual(
                (project / ".claude" / "settings.json").read_text(encoding="utf-8"), first
            )
            self.assertIn("UNCHANGED", stdout)

    def test_merge_settings_never_removes_and_unions(self) -> None:
        existing = {"permissions": {"deny": ["Keep"]}, "hooks": {"PreToolUse": [{"a": 1}]}}
        addition = {"permissions": {"deny": ["Artifact"]}, "hooks": {"PreToolUse": [{"b": 2}]}}
        merged, changed = adopt._merge_settings(existing, addition)
        self.assertTrue(changed)
        self.assertEqual(merged["permissions"]["deny"], ["Keep", "Artifact"])
        self.assertEqual(merged["hooks"]["PreToolUse"], [{"a": 1}, {"b": 2}])
        merged_again, changed_again = adopt._merge_settings(merged, addition)
        self.assertFalse(changed_again)
        self.assertEqual(merged_again, merged)

    def test_refuses_target_that_contains_repository(self) -> None:
        result, _stdout, stderr = self.run_adopt("--target", str(ROOT.parent))
        self.assertEqual(result, 2)
        self.assertIn("may not contain", stderr)


if __name__ == "__main__":
    unittest.main()
