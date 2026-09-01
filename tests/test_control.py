from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import control  # noqa: E402


class ControlLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="sysops-pub-test-")
        self.target = Path(self.temporary.name) / "sandbox"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_control(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = control.main(list(arguments))
        return result, stdout.getvalue(), stderr.getvalue()

    def initialize(self) -> None:
        result, _stdout, stderr = self.run_control("init", "--target", str(self.target))
        self.assertEqual(result, 0, stderr)

    def test_dry_run_does_not_write_managed_files(self) -> None:
        self.initialize()
        result, stdout, stderr = self.run_control("apply", "--target", str(self.target))
        self.assertEqual(result, 0, stderr)
        self.assertIn("dry-run only", stdout)
        self.assertFalse((self.target / ".config").exists())

    def test_execute_then_verify(self) -> None:
        self.initialize()
        result, _stdout, stderr = self.run_control(
            "apply", "--target", str(self.target), "--execute"
        )
        self.assertEqual(result, 0, stderr)
        result, stdout, stderr = self.run_control("verify", "--target", str(self.target))
        self.assertEqual(result, 0, stderr)
        self.assertIn("MATCH", stdout)

    def test_verification_detects_drift_and_scoped_apply_repairs_it(self) -> None:
        self.initialize()
        self.assertEqual(self.run_control("apply", "--target", str(self.target), "--execute")[0], 0)
        banner = self.target / ".config/sysops_pub/shell-banner/banner.txt"
        banner.write_text("changed\n", encoding="utf-8")

        result, stdout, _stderr = self.run_control("verify", "--target", str(self.target))
        self.assertEqual(result, 1)
        self.assertIn("DRIFT", stdout)

        result, _stdout, stderr = self.run_control(
            "--component",
            "shell-banner",
            "apply",
            "--target",
            str(self.target),
            "--execute",
        )
        self.assertEqual(result, 0, stderr)
        self.assertEqual(self.run_control("verify", "--target", str(self.target))[0], 0)

    def test_execute_refuses_unmarked_target(self) -> None:
        self.target.mkdir()
        result, _stdout, stderr = self.run_control(
            "apply", "--target", str(self.target), "--execute"
        )
        self.assertEqual(result, 2)
        self.assertIn("not a marked", stderr)

    def test_init_refuses_nonempty_directory(self) -> None:
        self.target.mkdir()
        (self.target / "existing.txt").write_text("keep\n", encoding="utf-8")
        result, _stdout, stderr = self.run_control("init", "--target", str(self.target))
        self.assertEqual(result, 2)
        self.assertIn("non-empty", stderr)
        self.assertEqual((self.target / "existing.txt").read_text(encoding="utf-8"), "keep\n")

    def test_registry_rejects_parent_traversal(self) -> None:
        registry = Path(self.temporary.name) / "bad-registry.json"
        profile = Path(self.temporary.name) / "bad-profile.json"
        registry.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "components": [
                        {
                            "name": "agent-policy",
                            "source": "../outside",
                            "destination": ".config/example",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        profile.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "name": "bad-registry-test",
                    "components": {"agent-policy": {"enabled": True}},
                }
            ),
            encoding="utf-8",
        )
        self.initialize()
        result, _stdout, stderr = self.run_control(
            "--registry",
            str(registry),
            "--profile",
            str(profile),
            "plan",
            "--target",
            str(self.target),
        )
        self.assertEqual(result, 2)
        self.assertIn("non-traversing", stderr)

    def test_report_json_is_machine_readable(self) -> None:
        self.initialize()
        result, stdout, stderr = self.run_control("report", "--target", str(self.target), "--json")
        self.assertEqual(result, 0, stderr)
        report = json.loads(stdout)
        self.assertEqual(report["summary"], {"missing": 2})
        self.assertEqual(len(report["files"]), 2)


if __name__ == "__main__":
    unittest.main()
