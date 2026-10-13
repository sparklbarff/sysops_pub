from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import disclosure_scan


class DisclosureScanTests(unittest.TestCase):
    def scan_fixture(
        self,
        files: dict[str, bytes],
        binary_files: list[dict[str, str]] | None = None,
    ) -> list[str]:
        with tempfile.TemporaryDirectory(prefix="disclosure-scan-") as directory:
            root = Path(directory)
            tracked = []
            for relative, content in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                tracked.append(path)
            allowlist = root / "allowlist.json"
            allowlist.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "findings": [],
                        "binary_files": binary_files or [],
                        "omission_files": [],
                    }
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.object(disclosure_scan, "ROOT", root),
                mock.patch.object(disclosure_scan, "ALLOWLIST_PATH", allowlist),
                mock.patch.object(disclosure_scan, "_tracked_files", return_value=tracked),
            ):
                return disclosure_scan.scan()

    def test_declared_identifier_categories_have_executable_patterns(self) -> None:
        windows_path = "C:" + "\\" + "Users" + "\\" + "sample-user\\settings.json"
        samples = {
            "Windows user path": windows_path,
            "email address": "sample-user" + "@" + "invalid.test",
            "IPv4 address": "192." + "0.2.44",
            "MAC address": "02:00:5e" + ":10:00:00",
            "UUID-like device identifier": "123e4567-e89b-12d3" + "-a456-426614174000",
            "local hostname": "sample-host" + ".local",
            "hostname declaration": "hostname" + " = sample-host",
        }
        for label, sample in samples.items():
            with self.subTest(label=label):
                self.assertIsNotNone(disclosure_scan.TEXT_PATTERNS[label].search(sample))

    def test_windows_pattern_catches_serialized_and_forward_slash_paths(self) -> None:
        pattern = disclosure_scan.TEXT_PATTERNS["Windows user path"]
        serialized = '{"path":"C:' + "\\\\" + "Users" + "\\\\" + 'sample-user\\\\file"}'
        forward = "C:" + "/" + "Users/sample-user/file"
        self.assertIsNotNone(pattern.search(serialized))
        self.assertIsNotNone(pattern.search(forward))

    def test_scanner_includes_its_own_tracked_source(self) -> None:
        tracked = disclosure_scan._tracked_files()
        self.assertIn(
            Path(disclosure_scan.__file__).resolve(), [path.resolve() for path in tracked]
        )

    def test_omission_only_operational_artifacts_are_rejected(self) -> None:
        for relative in (
            "handoff.md",
            "handoff-2026.md",
            "ledger.csv",
            "generated-report.md",
            "session.log",
            "session-notes.md",
            "task-state.md",
            "metrics.duckdb",
            "transcript.jsonl",
            "logs/receipt.txt",
        ):
            with self.subTest(relative=relative):
                findings = self.scan_fixture({relative: b"synthetic\n"})
                self.assertTrue(any("omission-only" in finding for finding in findings))

    def test_history_metadata_allows_github_noreply_collaborator_identity(self) -> None:
        output = (
            "a" * 40
            + "\x1fexample-user\x1f123+example-user"
            + "@"
            + "users.noreply.github.com"
            + "\x1fexample-user\x1fexample-user"
            + "@"
            + "users.noreply.github.com\x1e\n"
        )
        completed = subprocess.CompletedProcess([], 0, stdout=output, stderr="")
        with mock.patch.object(disclosure_scan.subprocess, "run", return_value=completed):
            self.assertEqual(disclosure_scan._history_metadata_findings(), [])

    def test_history_metadata_rejects_ordinary_email(self) -> None:
        output = (
            "b" * 40
            + "\x1fExample User\x1fexample"
            + "@"
            + "example.test"
            + "\x1fExample User\x1fexample"
            + "@"
            + "example.test\x1e\n"
        )
        completed = subprocess.CompletedProcess([], 0, stdout=output, stderr="")
        with mock.patch.object(disclosure_scan.subprocess, "run", return_value=completed):
            findings = disclosure_scan._history_metadata_findings()
        self.assertEqual(len(findings), 2)
        self.assertTrue(all("not GitHub noreply" in finding for finding in findings))

    def test_non_text_file_requires_exact_hash_bound_exception(self) -> None:
        content = b"\xff\x00fixture"
        findings = self.scan_fixture({"asset.dat": content})
        self.assertIn("asset.dat: non-text file is not binary-allowlisted", findings)

        import hashlib

        allowed = self.scan_fixture(
            {"asset.dat": content},
            [
                {
                    "path": "asset.dat",
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "reason": "Synthetic test asset",
                }
            ],
        )
        self.assertEqual(allowed, [])

    def test_utf8_control_bytes_are_not_mistaken_for_text(self) -> None:
        findings = self.scan_fixture({"nul.dat": b"valid-utf8\x00content"})
        self.assertIn("nul.dat: non-text file is not binary-allowlisted", findings)

    def test_binary_exception_rejects_hash_drift(self) -> None:
        findings = self.scan_fixture(
            {"asset.dat": b"\xffchanged"},
            [
                {
                    "path": "asset.dat",
                    "sha256": "0" * 64,
                    "reason": "Synthetic test asset",
                }
            ],
        )
        self.assertIn("asset.dat: binary allowlist SHA-256 mismatch", findings)

    def test_omission_exception_requires_exact_hash_and_reason(self) -> None:
        content = b"synthetic ledger\n"
        import hashlib

        with tempfile.TemporaryDirectory(prefix="disclosure-scan-") as directory:
            root = Path(directory)
            path = root / "samples" / "synthetic-ledger.json"
            path.parent.mkdir(parents=True)
            path.write_bytes(content)
            allowlist = root / "allowlist.json"
            allowlist.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "findings": [],
                        "binary_files": [],
                        "omission_files": [
                            {
                                "path": "samples/synthetic-ledger.json",
                                "sha256": hashlib.sha256(content).hexdigest(),
                                "reason": "Synthetic fixture",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.object(disclosure_scan, "ROOT", root),
                mock.patch.object(disclosure_scan, "ALLOWLIST_PATH", allowlist),
                mock.patch.object(disclosure_scan, "_tracked_files", return_value=[path]),
            ):
                self.assertEqual(disclosure_scan.scan(), [])
                path.write_bytes(b"changed\n")
                self.assertIn(
                    "samples/synthetic-ledger.json: omission allowlist SHA-256 mismatch",
                    disclosure_scan.scan(),
                )

    def _history_fixture(self, directory: str) -> tuple[Path, str, str]:
        """A repository that added an identifier in one commit and removed it in the next."""
        repository = Path(directory) / "repository"
        repository.mkdir()

        def git(*arguments: str) -> str:
            return subprocess.run(
                ["git", *arguments],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

        git("init", "-q")
        git("config", "user.email", "123+example-user" + "@" + "users.noreply.github.com")
        git("config", "user.name", "example-user")
        git("config", "commit.gpgsign", "false")
        note = repository / "note.md"
        note.write_text("contact sample-user" + "@" + "invalid.test\n", encoding="utf-8")
        git("add", "note.md")
        git("commit", "-q", "-m", "add an identifier")
        added = git("rev-parse", "HEAD")
        note.write_text("contact removed\n", encoding="utf-8")
        git("add", "note.md")
        git("commit", "-q", "-m", "remove it again")
        removed = git("rev-parse", "HEAD")
        return repository, added, removed

    def _history_findings(self, repository: Path, history: list[str]) -> list[str]:
        allowlist = repository.parent / "allowlist.json"
        allowlist.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "findings": [],
                    "binary_files": [],
                    "omission_files": [],
                    "history_findings": history,
                }
            ),
            encoding="utf-8",
        )
        with (
            mock.patch.object(disclosure_scan, "ROOT", repository),
            mock.patch.object(disclosure_scan, "ALLOWLIST_PATH", allowlist),
        ):
            return disclosure_scan._history_content_findings()

    def test_history_content_flags_an_identifier_a_later_commit_removed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="disclosure-scan-") as directory:
            repository, added, removed = self._history_fixture(directory)
            findings = self._history_findings(repository, [])
            self.assertEqual(findings, [f"{added}:note.md: email address"])
            self.assertFalse(any(removed in finding for finding in findings))

    def test_history_allowlist_entry_is_exact_and_goes_stale(self) -> None:
        with tempfile.TemporaryDirectory(prefix="disclosure-scan-") as directory:
            repository, added, removed = self._history_fixture(directory)
            exact = f"{added}:note.md: email address"
            self.assertEqual(self._history_findings(repository, [exact]), [])
            stale = f"{removed}:note.md: email address"
            self.assertEqual(
                self._history_findings(repository, [stale]),
                [exact, f"history allowlist entry is stale: {stale}"],
            )

    def test_main_fails_on_an_identifier_only_the_history_contains(self) -> None:
        """The current tree is clean and every commit identity is noreply; history alone fails."""
        with tempfile.TemporaryDirectory(prefix="disclosure-scan-") as directory:
            repository, added, _removed = self._history_fixture(directory)
            allowlist = repository.parent / "allowlist.json"
            allowlist.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "findings": [],
                        "binary_files": [],
                        "omission_files": [],
                    }
                ),
                encoding="utf-8",
            )
            stderr = io.StringIO()
            with (
                mock.patch.object(disclosure_scan, "ROOT", repository),
                mock.patch.object(disclosure_scan, "ALLOWLIST_PATH", allowlist),
                contextlib.redirect_stderr(stderr),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(disclosure_scan.scan(), [])
                self.assertEqual(disclosure_scan.main(), 1)
            self.assertIn(f"{added}:note.md: email address", stderr.getvalue())

    def test_merge_only_text_is_found_under_the_merge_and_branch_text_is_not_repeated(
        self,
    ) -> None:
        """A merge's own additions are found; lines a parent carried stay with that parent."""
        with tempfile.TemporaryDirectory(prefix="disclosure-scan-") as directory:
            repository = Path(directory) / "repository"
            repository.mkdir()

            def git(*arguments: str) -> str:
                return subprocess.run(
                    ["git", *arguments],
                    cwd=repository,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()

            def write(name: str, text: str) -> None:
                (repository / name).write_text(text, encoding="utf-8")

            git("init", "-q", "-b", "main")
            git("config", "user.email", "123+example-user" + "@" + "users.noreply.github.com")
            git("config", "user.name", "example-user")
            git("config", "commit.gpgsign", "false")
            write("base.txt", "base\n")
            git("add", "-A")
            git("commit", "-q", "-m", "base")
            git("checkout", "-q", "-b", "side")
            write("side.txt", "branch contact side-user" + "@" + "invalid.test\n")
            git("add", "-A")
            git("commit", "-q", "-m", "side branch adds an identifier")
            side = git("rev-parse", "HEAD")
            git("checkout", "-q", "main")
            write("main.txt", "main\n")
            git("add", "-A")
            git("commit", "-q", "-m", "main moves on")
            git("merge", "-q", "--no-commit", "side")
            write("base.txt", "base\nmerge contact merge-user" + "@" + "invalid.test\n")
            write("merge_only.txt", "address " + "192." + "0.2.44\n")
            git("add", "-A")
            git("commit", "-q", "-m", "merge that adds text of its own")
            merge = git("rev-parse", "HEAD")
            write("base.txt", "base\n")
            git("rm", "-q", "merge_only.txt", "side.txt")
            git("add", "-A")
            git("commit", "-q", "-m", "remove everything again")
            findings = self._history_findings(repository, [])
            self.assertEqual(
                sorted(findings),
                sorted(
                    [
                        f"{side}:side.txt: email address",
                        f"{merge}:base.txt: email address",
                        f"{merge}:merge_only.txt: IPv4 address",
                    ]
                ),
            )

    def test_history_allowlist_rejects_abbreviated_commits(self) -> None:
        with tempfile.TemporaryDirectory(prefix="disclosure-scan-") as directory:
            repository, added, _removed = self._history_fixture(directory)
            with self.assertRaisesRegex(disclosure_scan.ScanError, "history_findings"):
                self._history_findings(repository, [f"{added[:7]}:note.md: email address"])


if __name__ == "__main__":
    unittest.main()
