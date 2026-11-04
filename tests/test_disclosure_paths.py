"""The disclosure allowlist judges Git's '/' paths the same on every platform (repair audit
2026-11-03: under Windows path semantics a valid entry was rejected)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path, PureWindowsPath
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import disclosure_scan

SHA = "0" * 64


def entry(path: str) -> list[dict[str, str]]:
    return [{"path": path, "sha256": SHA, "reason": "fixture"}]


class DisclosurePathTests(unittest.TestCase):
    def test_git_paths_are_accepted_under_either_path_flavour(self) -> None:
        for flavour in (Path, PureWindowsPath):
            with (
                self.subTest(flavour=flavour.__name__),
                mock.patch.object(disclosure_scan, "Path", flavour),
            ):
                accepted = disclosure_scan._hash_bound_entries(
                    entry("site/fonts/chivo.woff2"), "binary_files"
                )
                self.assertIn("site/fonts/chivo.woff2", accepted)

    def test_unsafe_or_windows_shaped_entries_are_refused(self) -> None:
        for path in ("site\\fonts\\chivo.woff2", "C:/site/x", "/abs/x", "../x", "a//b"):
            with self.subTest(path=path), self.assertRaises(disclosure_scan.ScanError):
                disclosure_scan._hash_bound_entries(entry(path), "binary_files")

    def test_a_windows_relative_path_is_compared_in_git_form(self) -> None:
        self.assertEqual(
            PureWindowsPath("site", "fonts", "chivo.woff2").as_posix(), "site/fonts/chivo.woff2"
        )


if __name__ == "__main__":
    unittest.main()
