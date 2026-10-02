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


class PrePushTests(unittest.TestCase):
    def test_parser_returns_unique_non_deletion_shas(self) -> None:
        first = "1" * 40
        second = "2" * 40
        deleted = "0" * 40
        lines = [
            f"refs/heads/main {first} refs/heads/main {deleted}\n",
            f"refs/tags/example {first} refs/tags/example {deleted}\n",
            f"refs/heads/topic {second} refs/heads/topic {first}\n",
            f"(delete) {deleted} refs/heads/old {second}\n",
        ]
        self.assertEqual(pre_push.parse_outgoing_shas(lines), [first, second])

    def test_parser_rejects_malformed_protocol_line(self) -> None:
        with self.assertRaisesRegex(pre_push.PrePushError, "malformed"):
            pre_push.parse_outgoing_shas(["refs/heads/main too-few-fields\n"])

    def test_parser_rejects_invalid_outgoing_object_id(self) -> None:
        with self.assertRaisesRegex(pre_push.PrePushError, "invalid outgoing object ID"):
            pre_push.parse_outgoing_shas(
                [f"refs/heads/main not-a-sha refs/heads/main {'0' * 40}\n"]
            )

    def test_main_verifies_every_outgoing_sha(self) -> None:
        first = "1" * 40
        second = "2" * 40
        protocol = io.StringIO(
            f"refs/heads/main {first} refs/heads/main {'0' * 40}\n"
            f"refs/heads/topic {second} refs/heads/topic {first}\n"
        )
        with (
            mock.patch.object(pre_push.sys, "stdin", protocol),
            mock.patch.object(pre_push, "verify_outgoing_sha") as verify,
        ):
            self.assertEqual(pre_push.main([]), 0)
        self.assertEqual(verify.call_args_list, [mock.call(first), mock.call(second)])

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
