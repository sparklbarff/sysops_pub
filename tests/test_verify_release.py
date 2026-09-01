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

import verify_release  # noqa: E402


class VerifyReleaseTests(unittest.TestCase):
    def test_release_check_invokes_bootstrap_wiring_check(self) -> None:
        with tempfile.TemporaryDirectory(prefix="verify-release-") as directory:
            root = Path(directory)
            hook = root / ".githooks" / "pre-push"
            hook.parent.mkdir()
            hook.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
            hook.chmod(0o755)
            completed = subprocess.CompletedProcess([], 0)
            stdout = io.StringIO()
            with (
                mock.patch.object(verify_release, "REPO_ROOT", root),
                mock.patch.object(verify_release.subprocess, "run", return_value=completed) as run,
                contextlib.redirect_stdout(stdout),
            ):
                self.assertTrue(verify_release._verify_hook_wiring())
            self.assertIn("is wired", stdout.getvalue())
            run.assert_called_once_with(
                [sys.executable, "tools/bootstrap.py", "--check"],
                cwd=root,
                check=False,
            )

    def test_release_check_rejects_failed_bootstrap_check(self) -> None:
        completed = subprocess.CompletedProcess([], 2)
        stderr = io.StringIO()
        with (
            mock.patch.object(verify_release.subprocess, "run", return_value=completed),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertFalse(verify_release._verify_hook_wiring())
        self.assertIn("not wired", stderr.getvalue())

    @unittest.skipIf(os.name == "nt", "POSIX executable mode is not used on Windows")
    def test_release_check_rejects_non_executable_hook(self) -> None:
        with tempfile.TemporaryDirectory(prefix="verify-release-") as directory:
            root = Path(directory)
            hook = root / ".githooks" / "pre-push"
            hook.parent.mkdir()
            hook.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
            hook.chmod(0o644)
            completed = subprocess.CompletedProcess([], 0)
            stderr = io.StringIO()
            with (
                mock.patch.object(verify_release, "REPO_ROOT", root),
                mock.patch.object(verify_release.subprocess, "run", return_value=completed),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertFalse(verify_release._verify_hook_wiring())
            self.assertIn("not executable", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
