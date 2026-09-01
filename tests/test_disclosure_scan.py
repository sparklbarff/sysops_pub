from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import disclosure_scan  # noqa: E402


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
                        "schema_version": 2,
                        "findings": [],
                        "binary_files": binary_files or [],
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
        samples = {
            "Windows user path": "C:\\Users\\sample-user\\settings.json",
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

    def test_scanner_includes_its_own_tracked_source(self) -> None:
        tracked = disclosure_scan._tracked_files()
        self.assertIn(
            Path(disclosure_scan.__file__).resolve(), [path.resolve() for path in tracked]
        )

    def test_omission_only_operational_artifacts_are_rejected(self) -> None:
        for relative in (
            "handoff.md",
            "session.log",
            "metrics.duckdb",
            "transcript.jsonl",
            "logs/receipt.txt",
        ):
            with self.subTest(relative=relative):
                findings = self.scan_fixture({relative: b"synthetic\n"})
                self.assertTrue(any("omission-only" in finding for finding in findings))

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


if __name__ == "__main__":
    unittest.main()
