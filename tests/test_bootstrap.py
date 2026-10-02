from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import bootstrap


class BootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="sysops-pub-bootstrap-")
        self.repository = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repository, check=True)
        hook = self.repository / ".githooks" / "pre-push"
        hook.parent.mkdir()
        hook.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
        hook.chmod(0o755)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_bootstrap(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        hook = self.repository / ".githooks" / "pre-push"
        with (
            mock.patch.object(bootstrap, "REPO_ROOT", self.repository),
            mock.patch.object(bootstrap, "PRE_PUSH", hook),
            mock.patch.object(bootstrap, "_missing_release_tools", return_value=[]),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            result = bootstrap.main(list(arguments))
        return result, stdout.getvalue(), stderr.getvalue()

    def configured_hooks_path(self) -> str:
        result = subprocess.run(
            ["git", "config", "--local", "--get", "core.hooksPath"],
            cwd=self.repository,
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def test_dry_run_does_not_write_git_config(self) -> None:
        result, stdout, stderr = self.run_bootstrap()
        self.assertEqual(result, 0, stderr)
        self.assertIn("dry-run only", stdout)
        self.assertEqual(self.configured_hooks_path(), "")

    def test_execute_wires_and_verifies_hook(self) -> None:
        result, stdout, stderr = self.run_bootstrap("--execute")
        self.assertEqual(result, 0, stderr)
        self.assertIn("installed and verified", stdout)
        self.assertEqual(self.configured_hooks_path(), ".githooks")
        self.assertEqual(self.run_bootstrap("--check")[0], 0)

    @unittest.skipIf(os.name == "nt", "POSIX executable mode is not used on Windows")
    def test_check_rejects_non_executable_hook(self) -> None:
        self.assertEqual(self.run_bootstrap("--execute")[0], 0)
        (self.repository / ".githooks" / "pre-push").chmod(0o644)
        result, _stdout, stderr = self.run_bootstrap("--check")
        self.assertEqual(result, 2)
        self.assertIn("not executable", stderr)

    def test_execute_reports_missing_release_tools_before_wiring(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        hook = self.repository / ".githooks" / "pre-push"
        with (
            mock.patch.object(bootstrap, "REPO_ROOT", self.repository),
            mock.patch.object(bootstrap, "PRE_PUSH", hook),
            mock.patch.object(
                bootstrap, "_missing_release_tools", return_value=["gitleaks", "shellcheck"]
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            result = bootstrap.main(["--execute"])
        self.assertEqual(result, 2)
        self.assertIn("install the mandatory release tools", stderr.getvalue())
        self.assertEqual(self.configured_hooks_path(), "")


if __name__ == "__main__":
    unittest.main()
