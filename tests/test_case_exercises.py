from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import case_exercises


class CaseExerciseTests(unittest.TestCase):
    def test_spectre_artifact_is_not_accepted(self) -> None:
        result = case_exercises.spectre_result()
        self.assertTrue(result["artifact_created"])
        self.assertFalse(result["accepted"])
        self.assertEqual(result["classification"], "failed_diagnostic_artifact")

    def test_eidolon_fixture_rejects_both_naive_heuristics(self) -> None:
        result = case_exercises.eidolon_result()
        self.assertEqual(len(result["substring_mismatches"]), 2)
        self.assertEqual(len(result["head_word_mismatches"]), 1)


if __name__ == "__main__":
    unittest.main()
