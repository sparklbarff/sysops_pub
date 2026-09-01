from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import disclosure_scan  # noqa: E402


class DisclosureScanTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
