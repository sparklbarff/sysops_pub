"""The managed-job receipt never follows a planted symlink and never overwrites a receipt (repair
audit 2026-11-03: the fixed `.name.tmp` path overwrote the sentinel a symlink there pointed at)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import managed_job


class ReceiptSafetyTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "symlink creation needs privileges on Windows")
    def test_a_planted_temporary_symlink_is_not_followed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="managed-receipt-") as directory:
            root = Path(directory)
            sentinel = root / "sentinel.txt"
            sentinel.write_text("keep me\n", encoding="utf-8")
            receipt = root / "receipt.json"
            (root / ".receipt.json.tmp").symlink_to(sentinel)
            code = managed_job.run_managed([sys.executable, "-c", "pass"], receipt)
            self.assertEqual(code, 0)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep me\n")
            self.assertFalse(receipt.is_symlink())
            self.assertIn('"return_code": 0', receipt.read_text(encoding="utf-8"))
            leftovers = [p.name for p in root.iterdir() if p.name.startswith(".receipt.json.")]
            self.assertEqual(leftovers, [".receipt.json.tmp"])  # only the planted one

    def test_a_receipt_appearing_after_the_check_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory(prefix="managed-receipt-") as directory:
            receipt = Path(directory) / "receipt.json"
            receipt.write_text("someone else's\n", encoding="utf-8")
            with self.assertRaises(managed_job.ManagedJobError):
                managed_job._write_receipt(receipt, {"return_code": 0})
            self.assertEqual(receipt.read_text(encoding="utf-8"), "someone else's\n")


if __name__ == "__main__":
    unittest.main()
