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
        # Git here reads only the repository's configuration and a synthetic global file, so the
        # machine's own hooks setup can neither satisfy nor break a test.
        self.config = tempfile.TemporaryDirectory(prefix="sysops-pub-bootstrap-config-")
        self.addCleanup(self.config.cleanup)
        self.global_config = Path(self.config.name) / "gitconfig"
        isolated = mock.patch.dict(
            os.environ,
            {"GIT_CONFIG_GLOBAL": str(self.global_config), "GIT_CONFIG_NOSYSTEM": "1"},
        )
        isolated.start()
        self.addCleanup(isolated.stop)
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

    def test_declared_tools_replace_the_default_four(self) -> None:
        pyproject = self.repository / "pyproject.toml"
        hook = self.repository / ".githooks" / "pre-push"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(bootstrap, "REPO_ROOT", self.repository),
            mock.patch.object(bootstrap, "PRE_PUSH", hook),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            pyproject.write_text("[tool.sysops_pub.gate]\ntools = []\n", encoding="utf-8")
            self.assertEqual(bootstrap.release_tools(), ())
            self.assertEqual(bootstrap.main(["--execute"]), 0, stderr.getvalue())
            pyproject.write_text(
                '[tool.sysops_pub.gate]\ntools = ["no-such-gate-tool-9f3c"]\n', encoding="utf-8"
            )
            self.assertEqual(bootstrap.main(["--check"]), 2)
            pyproject.write_text('[tool.sysops_pub.gate]\ntools = "black"\n', encoding="utf-8")
            self.assertEqual(bootstrap.main(["--check"]), 2)
            pyproject.unlink()
            self.assertEqual(bootstrap.release_tools(), bootstrap.DEFAULT_RELEASE_TOOLS)
        self.assertIn("no-such-gate-tool-9f3c", stderr.getvalue())
        self.assertIn("list of command names", stderr.getvalue())
        self.assertEqual(self.configured_hooks_path(), ".githooks")

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

    def set_hooks_path(self, value: str) -> None:
        subprocess.run(
            ["git", "config", "--local", "core.hooksPath", value], cwd=self.repository, check=True
        )

    def test_an_existing_hooks_path_is_not_overwritten(self) -> None:
        """Repair audit 2026-11-03: bootstrap replaced .existing-hooks and exited 0."""
        self.set_hooks_path(".existing-hooks")
        result, stdout, stderr = self.run_bootstrap("--execute")
        self.assertEqual(result, 2)
        self.assertIn(
            "CONFLICT this clone's hooks run through core.hooksPath '.existing-hooks'", stdout
        )
        self.assertIn("--replace-existing-hooks", stderr)
        self.assertEqual(self.configured_hooks_path(), ".existing-hooks")

    def test_a_recorded_takeover_is_undone_exactly(self) -> None:
        self.set_hooks_path(".existing-hooks")
        result, _stdout, stderr = self.run_bootstrap("--execute", "--replace-existing-hooks")
        self.assertEqual(result, 0, stderr)
        self.assertEqual(self.configured_hooks_path(), ".githooks")
        record = self.repository / ".git" / bootstrap.RECORD_NAME
        self.assertIn('"previous_hooks_path": ".existing-hooks"', record.read_text())
        self.assertEqual(self.run_bootstrap("--uninstall")[0], 0)
        self.assertEqual(self.configured_hooks_path(), ".existing-hooks")
        self.assertFalse(record.exists())
        # A fresh install and removal leave core.hooksPath unset again.
        subprocess.run(
            ["git", "config", "--local", "--unset", "core.hooksPath"],
            cwd=self.repository,
            check=True,
        )
        self.assertEqual(self.run_bootstrap("--execute")[0], 0)
        self.assertEqual(self.run_bootstrap("--uninstall")[0], 0)
        self.assertEqual(self.configured_hooks_path(), "")

    def test_uninstall_leaves_a_later_owner_alone(self) -> None:
        self.assertEqual(self.run_bootstrap("--execute")[0], 0)
        self.set_hooks_path(".someone-else")
        result, _stdout, stderr = self.run_bootstrap("--uninstall")
        self.assertEqual(result, 2)
        self.assertIn("left alone", stderr)
        self.assertEqual(self.configured_hooks_path(), ".someone-else")
        self.assertEqual(self.run_bootstrap("--uninstall")[0], 2)

    @unittest.skipIf(os.name == "nt", "POSIX executable mode decides an active hook")
    def test_active_default_hooks_are_not_silently_disabled(self) -> None:
        hook = self.repository / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        hook.chmod(0o755)
        result, stdout, _stderr = self.run_bootstrap("--execute")
        self.assertEqual(result, 2)
        self.assertIn("the active hook(s) in .git/hooks (pre-commit)", stdout)
        self.assertEqual(self.configured_hooks_path(), "")
        self.assertEqual(self.run_bootstrap("--uninstall")[0], 2)

    def effective_hooks_path(self) -> str:
        result = subprocess.run(
            ["git", "config", "--get", "core.hooksPath"],
            cwd=self.repository,
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def test_an_inherited_hooks_path_is_previewed_and_preserved(self) -> None:
        """Lifecycle audit 2026-11-05: an inherited binding was overridden without a word."""
        inherited = (Path(self.config.name) / "owner hooks").as_posix()
        self.global_config.write_text(f'[core]\n\thooksPath = "{inherited}"\n', encoding="utf-8")
        result, stdout, _stderr = self.run_bootstrap()
        self.assertEqual(result, 0)
        self.assertIn(f"core.hooksPath '{inherited}', inherited from global configuration", stdout)
        result, _stdout, stderr = self.run_bootstrap("--execute")
        self.assertEqual(result, 2)
        self.assertIn("inherited from global configuration", stderr)
        self.assertEqual(self.configured_hooks_path(), "")
        self.assertEqual(self.effective_hooks_path(), inherited)

    def test_taking_over_an_inherited_hooks_path_is_explicit_and_undone(self) -> None:
        inherited = (Path(self.config.name) / "owner hooks").as_posix()
        self.global_config.write_text(f'[core]\n\thooksPath = "{inherited}"\n', encoding="utf-8")
        result, _stdout, stderr = self.run_bootstrap("--execute", "--replace-existing-hooks")
        self.assertEqual(result, 0, stderr)
        self.assertEqual(self.effective_hooks_path(), ".githooks")
        record = (self.repository / ".git" / bootstrap.RECORD_NAME).read_text(encoding="utf-8")
        self.assertIn(inherited, record)
        self.assertEqual(self.run_bootstrap("--uninstall")[0], 0)
        self.assertEqual(self.configured_hooks_path(), "")
        self.assertEqual(self.effective_hooks_path(), inherited)

    def test_an_inherited_hooks_path_that_is_already_ours_is_no_conflict(self) -> None:
        self.global_config.write_text('[core]\n\thooksPath = ".githooks"\n', encoding="utf-8")
        result, stdout, stderr = self.run_bootstrap("--execute")
        self.assertEqual(result, 0, stderr)
        self.assertNotIn("CONFLICT", stdout)


if __name__ == "__main__":
    unittest.main()
