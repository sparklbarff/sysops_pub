from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import pre_push

VERIFIER = """\
from pathlib import Path

raise SystemExit(0 if Path("fixture.txt").read_text() == "valid\\n" else 1)
"""


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=repository, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repository(directory: str) -> Path:
    """A clone whose verifier passes only when fixture.txt reads "valid"."""
    repository = Path(directory) / "repository"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.email", "test" + "@" + "example.invalid")
    _git(repository, "config", "user.name", "Test User")
    _git(repository, "config", "commit.gpgsign", "false")
    (repository / "tools").mkdir()
    (repository / "tools" / "verify_release.py").write_text(VERIFIER, encoding="utf-8")
    return repository


def _commit(repository: Path, fixture: str, message: str) -> str:
    (repository / "fixture.txt").write_text(fixture, encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-q", "--allow-empty", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


class PrePushTests(unittest.TestCase):
    def test_parser_returns_unique_non_deletion_refs(self) -> None:
        first = "1" * 40
        second = "2" * 40
        deleted = "0" * 40
        lines = [
            f"refs/heads/main {first} refs/heads/main {deleted}\n",
            f"refs/heads/copy {first} refs/heads/copy {deleted}\n",
            f"refs/heads/topic {second} refs/heads/topic {first}\n",
            f"(delete) {deleted} refs/heads/old {second}\n",
        ]
        self.assertEqual(pre_push.parse_outgoing_refs(lines), [(first, deleted), (second, first)])

    def test_parser_rejects_malformed_protocol_line(self) -> None:
        with self.assertRaisesRegex(pre_push.PrePushError, "malformed"):
            pre_push.parse_outgoing_refs(["refs/heads/main too-few-fields\n"])

    def test_parser_rejects_invalid_outgoing_object_id(self) -> None:
        with self.assertRaisesRegex(pre_push.PrePushError, "invalid outgoing object ID"):
            pre_push.parse_outgoing_refs(
                [f"refs/heads/main not-a-sha refs/heads/main {'0' * 40}\n"]
            )

    def test_parser_rejects_invalid_remote_object_id(self) -> None:
        with self.assertRaisesRegex(pre_push.PrePushError, "invalid remote object ID"):
            pre_push.parse_outgoing_refs([f"refs/heads/main {'1' * 40} refs/heads/main nope\n"])

    def test_every_commit_in_the_range_is_verified_not_only_the_tip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = _repository(directory)
            published = _commit(repository, "valid\n", "already on the remote")
            _git(repository, "update-ref", "refs/remotes/origin/main", published)
            broken = _commit(repository, "invalid\n", "intermediate commit that fails")
            tip = _commit(repository, "valid\n", "tip that passes")
            protocol = io.StringIO(f"refs/heads/main {tip} refs/heads/main {published}\n")
            stderr = io.StringIO()
            with (
                mock.patch.object(pre_push, "REPO_ROOT", repository),
                mock.patch.object(pre_push.sys, "stdin", protocol),
                mock.patch.object(pre_push.sys, "stderr", stderr),
                mock.patch.object(pre_push.sys, "stdout", io.StringIO()),
            ):
                self.assertEqual(pre_push.main([]), 2)
            self.assertIn(
                f"release verification failed for outgoing commit {broken}", stderr.getvalue()
            )

    def test_main_reports_the_number_of_commits_verified(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = _repository(directory)
            published = _commit(repository, "valid\n", "already on the remote")
            _git(repository, "update-ref", "refs/remotes/origin/main", published)
            first = _commit(repository, "valid\n", "first")
            second = _commit(repository, "valid\n", "second")
            protocol = io.StringIO(
                f"refs/heads/main {second} refs/heads/main {published}\n"
                f"refs/heads/topic {second} refs/heads/topic {'0' * 40}\n"
            )
            stdout = io.StringIO()
            with (
                mock.patch.object(pre_push, "REPO_ROOT", repository),
                mock.patch.object(pre_push.sys, "stdin", protocol),
                mock.patch.object(pre_push.sys, "stdout", stdout),
                mock.patch.object(pre_push, "verify_outgoing_sha") as verify,
            ):
                self.assertEqual(pre_push.main([]), 0)
            self.assertEqual(verify.call_args_list, [mock.call(first), mock.call(second)])
            self.assertIn("pre-push: verified 2 outgoing commit(s)", stdout.getvalue())

    def test_new_branch_excludes_commits_already_on_a_remote(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = _repository(directory)
            published = _commit(repository, "invalid\n", "already on the remote")
            _git(repository, "update-ref", "refs/remotes/origin/main", published)
            new = _commit(repository, "valid\n", "new branch commit")
            with mock.patch.object(pre_push, "REPO_ROOT", repository):
                self.assertEqual(pre_push.outgoing_commits([(new, "0" * 40)]), [new])

    def test_unknown_remote_commit_refuses_the_push(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = _repository(directory)
            tip = _commit(repository, "valid\n", "local")
            with (
                mock.patch.object(pre_push, "REPO_ROOT", repository),
                self.assertRaisesRegex(pre_push.PrePushError, "fetch before pushing"),
            ):
                pre_push.outgoing_commits([(tip, "3" * 40)])

    def test_outgoing_commit_is_verified_instead_of_staged_worktree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = Path(directory) / "repository"
            repository.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test" + "@" + "example.invalid"],
                cwd=repository,
                check=True,
            )
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repository, check=True)
            subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repository, check=True)
            tools = repository / "tools"
            tools.mkdir()
            verifier = tools / "verify_release.py"
            verifier.write_text(
                textwrap.dedent("""\
                    from pathlib import Path
                    import sys

                    raise SystemExit(0 if Path("fixture.txt").read_text() == "valid\\n" else 1)
                    """),
                encoding="utf-8",
            )
            fixture = repository / "fixture.txt"
            fixture.write_text("invalid\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repository, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "invalid candidate"], cwd=repository, check=True
            )
            bad_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            fixture.write_text("valid\n", encoding="utf-8")
            subprocess.run(["git", "add", "fixture.txt"], cwd=repository, check=True)

            with (
                mock.patch.object(pre_push, "REPO_ROOT", repository),
                self.assertRaisesRegex(pre_push.PrePushError, "release verification failed"),
            ):
                pre_push.verify_outgoing_sha(bad_sha)

    @unittest.skipIf(os.name == "nt", "tracked hook launcher is POSIX shell")
    def test_tracked_hook_reaches_pre_push_driver_with_protocol_stdin(self) -> None:
        shell = shutil.which("sh")
        if shell is None:
            self.skipTest("POSIX sh is unavailable")
        with tempfile.TemporaryDirectory(prefix="sysops-pub-hook-fire-") as directory:
            repository = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            hook = repository / ".githooks" / "pre-push"
            hook.parent.mkdir()
            shutil.copy2(ROOT / ".githooks" / "pre-push", hook)
            hook.chmod(0o755)
            tools = repository / "tools"
            tools.mkdir()
            receipt = repository / "hook-receipt.txt"
            driver = tools / "pre_push.py"
            driver.write_text(
                textwrap.dedent(f"""\
                    import sys
                    from pathlib import Path

                    Path({str(receipt)!r}).write_text(sys.stdin.read(), encoding="utf-8")
                    """),
                encoding="utf-8",
            )
            protocol = f"refs/heads/main {'1' * 40} refs/heads/main {'0' * 40}\n"
            result = subprocess.run(
                [str(hook), "unused-origin", "unused-url"],
                cwd=repository,
                input=protocol,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(receipt.read_text(encoding="utf-8"), protocol)


if __name__ == "__main__":
    unittest.main()
