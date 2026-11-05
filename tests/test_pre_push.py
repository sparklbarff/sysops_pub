from __future__ import annotations

import io
import json
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

# A declared gate: passes only from a valid tree AND when handed the commit it is verifying.
DECLARED_CHECKER = """\
import subprocess
import sys
from pathlib import Path

head = subprocess.run(
    ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
).stdout.strip()
valid = Path("fixture.txt").read_text() == "valid\\n" and sys.argv[1] == head
raise SystemExit(0 if valid else 1)
"""

# A declared gate that judges the commit, not the files: its author must be a noreply address.
AUTHOR_CHECKER = """\
import subprocess
import sys

author = subprocess.run(
    ["git", "log", "-1", "--format=%ae", sys.argv[1]], check=True, capture_output=True, text=True
).stdout.strip()
raise SystemExit(0 if author.endswith("@users.noreply.github.com") else 1)
"""

# A declared gate that reads only the files.
TREE_CHECKER = """\
from pathlib import Path

raise SystemExit(0 if Path("fixture.txt").read_text() == "valid\\n" else 1)
"""

HOOK_ARGUMENTS = ["origin", "/nonexistent/destination.git"]
NOREPLY = "1+example-user" + "@" + "users.noreply.github.com"


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=repository, check=True, capture_output=True, text=True
    ).stdout.strip()


def _bare(directory: str, name: str) -> str:
    """A local bare repository in the test's own directory, as the push destination."""
    path = Path(directory) / name
    subprocess.run(["git", "init", "-q", "--bare", str(path)], check=True)
    return str(path)


def _repository(directory: str) -> Path:
    """A clone whose verifier passes only when fixture.txt reads "valid", with two local bare
    remotes, origin and mirror, both empty."""
    repository = Path(directory) / "repository"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.email", "test" + "@" + "example.invalid")
    _git(repository, "config", "user.name", "Test User")
    _git(repository, "config", "commit.gpgsign", "false")
    _git(repository, "remote", "add", "origin", _bare(directory, "origin.git"))
    _git(repository, "remote", "add", "mirror", _bare(directory, "mirror.git"))
    (repository / "tools").mkdir()
    (repository / "tools" / "verify_release.py").write_text(VERIFIER, encoding="utf-8")
    return repository


def _url(repository: Path, remote: str) -> str:
    return _git(repository, "remote", "get-url", "--push", remote)


def _publish(repository: Path, remote: str, sha: str, branch: str = "main") -> None:
    """Put a commit on a destination for real. The target must be a bare repository inside the
    test's own directory, so a fixture that goes wrong cannot push anywhere else."""
    target = Path(_url(repository, remote)).resolve()
    if not target.is_relative_to(repository.parent.resolve()):
        raise AssertionError(f"refusing to push outside the test directory: {target}")
    _git(repository, "push", "-q", remote, f"{sha}:refs/heads/{branch}")


class IsolatedGit(unittest.TestCase):
    """Git here reads only the repositories' own configuration: the machine's global hooks or
    settings can neither run during a test push nor change a result."""

    def setUp(self) -> None:
        config = tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-config-")
        self.addCleanup(config.cleanup)
        isolated = mock.patch.dict(
            os.environ,
            {"GIT_CONFIG_GLOBAL": str(Path(config.name) / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1"},
        )
        isolated.start()
        self.addCleanup(isolated.stop)


def _commit(repository: Path, fixture: str, message: str) -> str:
    (repository / "fixture.txt").write_text(fixture, encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-q", "--allow-empty", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


class PrePushTests(IsolatedGit):
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
            _publish(repository, "origin", published)
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
                self.assertEqual(pre_push.main(["origin", _url(repository, "origin")]), 2)
            self.assertIn(
                f"release verification failed for outgoing commit {broken}", stderr.getvalue()
            )

    def test_a_commit_another_remote_has_is_still_verified_for_this_destination(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = _repository(directory)
            published = _commit(repository, "valid\n", "already on origin")
            _publish(repository, "origin", published)
            mirrored = _commit(repository, "invalid\n", "only the mirror has this one")
            _publish(repository, "mirror", mirrored)
            tip = _commit(repository, "valid\n", "new tip")
            protocol = io.StringIO(f"refs/heads/main {tip} refs/heads/main {published}\n")
            stderr = io.StringIO()
            with (
                mock.patch.object(pre_push, "REPO_ROOT", repository),
                mock.patch.object(pre_push.sys, "stdin", protocol),
                mock.patch.object(pre_push.sys, "stderr", stderr),
                mock.patch.object(pre_push.sys, "stdout", io.StringIO()),
            ):
                self.assertEqual(pre_push.main(["origin", _url(repository, "origin")]), 2)
            self.assertIn(
                f"release verification failed for outgoing commit {mirrored}", stderr.getvalue()
            )

    def test_what_the_destination_holds_bounds_the_range(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = _repository(directory)
            on_origin = _commit(repository, "invalid\n", "origin already has this branch")
            _publish(repository, "origin", on_origin, "feature")
            new = _commit(repository, "valid\n", "new branch commit")
            origin, mirror = _url(repository, "origin"), _url(repository, "mirror")
            with mock.patch.object(pre_push, "REPO_ROOT", repository):
                self.assertEqual(
                    pre_push.outgoing_commits([(new, "0" * 40)], "origin", origin), [new]
                )
                self.assertEqual(
                    pre_push.outgoing_commits([(new, "0" * 40)], "mirror", mirror),
                    [on_origin, new],
                )

    def test_a_location_named_directly_is_read_like_any_other(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = _repository(directory)
            first = _commit(repository, "valid\n", "first")
            _publish(repository, "origin", first)
            second = _commit(repository, "valid\n", "second")
            elsewhere = _bare(directory, "elsewhere.git")
            origin = _url(repository, "origin")
            with mock.patch.object(pre_push, "REPO_ROOT", repository):
                self.assertEqual(
                    pre_push.outgoing_commits([(second, "0" * 40)], elsewhere, elsewhere),
                    [first, second],
                )
                self.assertEqual(
                    pre_push.outgoing_commits([(second, first)], elsewhere, elsewhere), [second]
                )
                self.assertEqual(
                    pre_push.outgoing_commits([(second, "0" * 40)], origin, origin), [second]
                )

    def test_a_separate_push_url_is_not_bounded_by_the_fetch_side(self) -> None:
        """Repair handoff 2026-11-03, Stage 1: with distinct fetch and push URLs, the fetch side's
        tracking refs held every commit and the hook selected none, though the push location had
        none of them."""
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = _repository(directory)
            fetch_side = _url(repository, "origin")
            first = _commit(repository, "invalid\n", "only the fetch side has this")
            tip = _commit(repository, "valid\n", "fetch side has this too")
            _publish(repository, "origin", tip)
            _git(repository, "fetch", "-q", "origin")
            push_side = _bare(directory, "push-only.git")
            _git(repository, "remote", "set-url", "--push", "origin", push_side)
            new_ref = [(tip, "0" * 40)]
            with mock.patch.object(pre_push, "REPO_ROOT", repository):
                self.assertEqual(
                    pre_push.outgoing_commits(new_ref, "origin", push_side), [first, tip]
                )
                # Control: a push to the fetch URL itself is bounded by what that location holds.
                self.assertEqual(pre_push.outgoing_commits(new_ref, "origin", fetch_side), [])
                # The destination's own ref value, which Git reads from the push location, still
                # bounds the range there.
                self.assertEqual(
                    pre_push.outgoing_commits([(tip, first)], "origin", push_side), [tip]
                )
            protocol = io.StringIO(f"refs/heads/main {tip} refs/heads/main {'0' * 40}\n")
            stderr = io.StringIO()
            with (
                mock.patch.object(pre_push, "REPO_ROOT", repository),
                mock.patch.object(pre_push.sys, "stdin", protocol),
                mock.patch.object(pre_push.sys, "stderr", stderr),
                mock.patch.object(pre_push.sys, "stdout", io.StringIO()),
            ):
                self.assertEqual(pre_push.main(["origin", push_side]), 2)
            self.assertIn(
                f"release verification failed for outgoing commit {first}", stderr.getvalue()
            )

    def test_a_repointed_remote_is_judged_by_its_new_destination(self) -> None:
        """Lifecycle audit 2026-11-05: origin was repointed to a new, empty repository while the
        old tracking refs remained; inspection through the name found nothing to verify and the
        same location named directly found the commit."""
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = _repository(directory)
            only = _commit(repository, "valid\n", "the one commit")
            _publish(repository, "origin", only)
            _git(repository, "fetch", "-q", "origin")
            self.assertEqual(_git(repository, "rev-parse", "refs/remotes/origin/main"), only)
            new = _bare(directory, "new.git")
            _git(repository, "remote", "set-url", "origin", new)
            new_ref = [(only, "0" * 40)]
            with mock.patch.object(pre_push, "REPO_ROOT", repository):
                self.assertEqual(pre_push.outgoing_commits(new_ref, "origin", new), [only])
                self.assertEqual(pre_push.outgoing_commits(new_ref, new, new), [only])

    def test_an_unreadable_destination_refuses_the_push(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = _repository(directory)
            tip = _commit(repository, "valid\n", "local")
            missing = str(Path(directory) / "missing.git")
            with (
                mock.patch.object(pre_push, "REPO_ROOT", repository),
                self.assertRaisesRegex(pre_push.PrePushError, "cannot read what .* already holds"),
            ):
                pre_push.outgoing_commits([(tip, "0" * 40)], missing, missing)

    def test_main_refuses_to_run_without_the_destination(self) -> None:
        stderr = io.StringIO()
        with mock.patch.object(pre_push.sys, "stderr", stderr):
            self.assertEqual(pre_push.main([]), 2)
            self.assertEqual(pre_push.main(["origin"]), 2)
        self.assertIn("destination remote's name and location", stderr.getvalue())

    def test_main_reports_the_number_of_commits_verified(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = _repository(directory)
            published = _commit(repository, "valid\n", "already on the remote")
            _publish(repository, "origin", published)
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
                mock.patch.object(pre_push, "verify_outgoing_sha", return_value=True) as verify,
            ):
                self.assertEqual(pre_push.main(["origin", _url(repository, "origin")]), 0)
            self.assertEqual(verify.call_args_list, [mock.call(first), mock.call(second)])
            self.assertIn("pre-push: verified 2 outgoing commit(s)", stdout.getvalue())

    def test_new_branch_excludes_commits_already_on_a_remote(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = _repository(directory)
            published = _commit(repository, "invalid\n", "already on the remote")
            _publish(repository, "origin", published)
            new = _commit(repository, "valid\n", "new branch commit")
            origin = _url(repository, "origin")
            with mock.patch.object(pre_push, "REPO_ROOT", repository):
                self.assertEqual(
                    pre_push.outgoing_commits([(new, "0" * 40)], "origin", origin), [new]
                )

    def test_unknown_remote_commit_refuses_the_push(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = _repository(directory)
            tip = _commit(repository, "valid\n", "local")
            origin = _url(repository, "origin")
            with (
                mock.patch.object(pre_push, "REPO_ROOT", repository),
                self.assertRaisesRegex(pre_push.PrePushError, "fetch before pushing"),
            ):
                pre_push.outgoing_commits([(tip, "3" * 40)], "origin", origin)

    def _declared_repository(
        self,
        directory: str,
        command: object,
        checker: str | None = DECLARED_CHECKER,
        memo: str | None = None,
    ) -> Path:
        """A clone whose pyproject declares its own gate and carries no verify_release.py."""
        repository = Path(directory) / "repository"
        repository.mkdir()
        _git(repository, "init", "-q")
        _git(repository, "config", "user.email", NOREPLY)
        _git(repository, "config", "user.name", "example-user")
        _git(repository, "config", "commit.gpgsign", "false")
        declaration = f"[tool.sysops_pub.gate]\ncommand = {json.dumps(command)}\n"
        if memo is not None:
            declaration += f"memo = {json.dumps(memo)}\n"
        (repository / "pyproject.toml").write_text(declaration, encoding="utf-8")
        if checker is not None:
            (repository / "check.py").write_text(checker, encoding="utf-8")
        return repository

    def test_declared_gate_runs_in_the_worktree_with_the_commit_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = self._declared_repository(directory, ["python3", "check.py", "{commit}"])
            good = _commit(repository, "valid\n", "passes its own gate")
            with (
                mock.patch.object(pre_push, "REPO_ROOT", repository),
                mock.patch.object(pre_push.sys, "stdout", io.StringIO()),
            ):
                self.assertTrue(pre_push.verify_outgoing_sha(good))
                bad = _commit(repository, "invalid\n", "fails its own gate")
                with self.assertRaisesRegex(pre_push.PrePushError, "release verification failed"):
                    pre_push.verify_outgoing_sha(bad)

    def test_declared_gate_whose_command_is_missing_refuses_the_push(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = self._declared_repository(
                directory, ["no-such-gate-tool-9f3c", "{commit}"], checker=None
            )
            sha = _commit(repository, "valid\n", "declares an absent tool")
            with (
                mock.patch.object(pre_push, "REPO_ROOT", repository),
                self.assertRaisesRegex(pre_push.PrePushError, "not available"),
            ):
                pre_push.verify_outgoing_sha(sha)

    def test_malformed_gate_declaration_refuses_the_push(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = self._declared_repository(directory, "python3 check.py")
            sha = _commit(repository, "valid\n", "declares a string, not a list")
            with (
                mock.patch.object(pre_push, "REPO_ROOT", repository),
                self.assertRaisesRegex(pre_push.PrePushError, "non-empty list"),
            ):
                pre_push.verify_outgoing_sha(sha)

    def test_a_verified_commit_is_not_verified_again_in_this_clone(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = _repository(directory)
            published = _commit(repository, "valid\n", "already on the remote")
            _publish(repository, "origin", published)
            tip = _commit(repository, "valid\n", "same tree as the published commit")
            stdout = io.StringIO()
            with (
                mock.patch.object(pre_push, "REPO_ROOT", repository),
                mock.patch.object(pre_push.sys, "stdout", stdout),
            ):
                self.assertTrue(pre_push.verify_outgoing_sha(tip))
                self.assertFalse(pre_push.verify_outgoing_sha(tip))
                (repository / "extra.txt").write_text("another file\n", encoding="utf-8")
                changed = _commit(repository, "valid\n", "a different tree")
                self.assertTrue(pre_push.verify_outgoing_sha(changed))
                protocol = io.StringIO(f"refs/heads/main {changed} refs/heads/main {published}\n")
                with mock.patch.object(pre_push.sys, "stdin", protocol):
                    self.assertEqual(pre_push.main(["origin", _url(repository, "origin")]), 0)
            output = stdout.getvalue()
            self.assertIn(f"commit {tip} already verified in this clone; skipping", output)
            self.assertIn("verified 0 outgoing commit(s), 2 already verified", output)
            memo = repository / ".git" / pre_push.MEMO_NAME
            self.assertEqual(len(memo.read_text(encoding="utf-8").splitlines()), 2)

    def test_a_same_tree_commit_is_judged_again_by_a_gate_that_reads_the_commit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = self._declared_repository(
                directory, ["python3", "check.py", "{commit}"], checker=AUTHOR_CHECKER
            )
            good = _commit(repository, "valid\n", "noreply author")
            _git(
                repository,
                "commit",
                "-q",
                "--amend",
                "--no-edit",
                "--author",
                "Someone <someone" + "@" + "example.invalid>",
            )
            amended = _git(repository, "rev-parse", "HEAD")
            self.assertEqual(
                _git(repository, "rev-parse", f"{good}^{{tree}}"),
                _git(repository, "rev-parse", f"{amended}^{{tree}}"),
            )
            with (
                mock.patch.object(pre_push, "REPO_ROOT", repository),
                mock.patch.object(pre_push.sys, "stdout", io.StringIO()),
            ):
                self.assertTrue(pre_push.verify_outgoing_sha(good))
                with self.assertRaisesRegex(
                    pre_push.PrePushError,
                    f"release verification failed for outgoing commit {amended}",
                ):
                    pre_push.verify_outgoing_sha(amended)

    def test_a_tree_scoped_gate_is_reused_across_commits_with_the_same_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = self._declared_repository(
                directory, ["python3", "check.py"], checker=TREE_CHECKER, memo="tree"
            )
            first = _commit(repository, "valid\n", "first")
            second = _commit(repository, "valid\n", "same files, new message")
            stdout = io.StringIO()
            with (
                mock.patch.object(pre_push, "REPO_ROOT", repository),
                mock.patch.object(pre_push.sys, "stdout", stdout),
            ):
                self.assertTrue(pre_push.verify_outgoing_sha(first))
                self.assertFalse(pre_push.verify_outgoing_sha(second))
                changed = _commit(repository, "invalid\n", "different files")
                with self.assertRaisesRegex(pre_push.PrePushError, "release verification failed"):
                    pre_push.verify_outgoing_sha(changed)
            self.assertIn(f"tree of {second} already verified", stdout.getvalue())

    def test_a_gate_that_receives_the_commit_cannot_declare_tree_scope(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = self._declared_repository(
                directory, ["python3", "check.py", "{commit}"], memo="tree"
            )
            sha = _commit(repository, "valid\n", "contradictory declaration")
            with (
                mock.patch.object(pre_push, "REPO_ROOT", repository),
                self.assertRaisesRegex(pre_push.PrePushError, "cannot declare memo"),
            ):
                pre_push.verify_outgoing_sha(sha)

    def test_an_unknown_memo_scope_refuses_the_push(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = self._declared_repository(
                directory, ["python3", "check.py"], checker=TREE_CHECKER, memo="forever"
            )
            sha = _commit(repository, "valid\n", "unknown scope")
            with (
                mock.patch.object(pre_push, "REPO_ROOT", repository),
                self.assertRaisesRegex(pre_push.PrePushError, "memo in .* must be one of"),
            ):
                pre_push.verify_outgoing_sha(sha)

    def test_memo_key_names_the_judged_subject_and_the_gate_command(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sysops-pub-pre-push-test-") as directory:
            repository = _repository(directory)
            first = _commit(repository, "valid\n", "first")
            second = _commit(repository, "valid\n", "second, same tree")
            gate = pre_push.DEFAULT_GATE
            with mock.patch.object(pre_push, "REPO_ROOT", repository):
                self.assertNotEqual(pre_push.memo_key(first, gate), pre_push.memo_key(second, gate))
                self.assertEqual(pre_push.memo_key(first, gate), pre_push.memo_key(first, gate))
                tree_first = pre_push.memo_key(first, ["make", "check"], "tree")
                self.assertEqual(tree_first, pre_push.memo_key(second, ["make", "check"], "tree"))
                self.assertNotEqual(tree_first, pre_push.memo_key(first, ["make", "test"], "tree"))

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
    def test_tracked_hook_reaches_pre_push_driver_with_destination_and_protocol(self) -> None:
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
                    import json
                    import sys
                    from pathlib import Path

                    record = {{"argv": sys.argv[1:], "stdin": sys.stdin.read()}}
                    Path({str(receipt)!r}).write_text(json.dumps(record), encoding="utf-8")
                    """),
                encoding="utf-8",
            )
            protocol = f"refs/heads/main {'1' * 40} refs/heads/main {'0' * 40}\n"
            result = subprocess.run(
                [str(hook), *HOOK_ARGUMENTS],
                cwd=repository,
                input=protocol,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            record = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(record, {"argv": HOOK_ARGUMENTS, "stdin": protocol})


if __name__ == "__main__":
    unittest.main()
