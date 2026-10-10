from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import calibrate_check

SAMPLES = ROOT / "samples" / "calibration"
DIAGNOSTIC = "persisted state differs from expected"


def _cases(directory: Path) -> dict[str, Path]:
    return {
        "known_failure": directory / "known-failure.json",
        "valid": directory / "valid.json",
        "allowed_variation": directory / "allowed-variation.json",
    }


class CalibrateCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="calibrate-check-")
        self.directory = Path(self._temporary.name)
        for path in SAMPLES.iterdir():
            if path.is_file():
                shutil.copy2(path, self.directory / path.name)
        self.cases = _cases(self.directory)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _checker(self, name: str, body: str) -> Path:
        path = self.directory / name
        path.write_text(body, encoding="utf-8")
        return path

    def _run(self, checker: Path, **kwargs: Any) -> dict[str, Any]:
        command = [sys.executable, str(checker), "{case}"]
        return calibrate_check.calibrate(checker, self.cases, command, DIAGNOSTIC, **kwargs)

    def test_sample_checker_discriminates_the_declared_cases(self) -> None:
        result = self._run(self.directory / "check_update_receipt.py")
        self.assertEqual(result["status"], "calibration-verified")
        self.assertTrue(result["inputs_unchanged"])
        self.assertEqual(
            set(result["inputs"]), {"checker", "known_failure", "valid", "allowed_variation"}
        )
        self.assertIn("not product acceptance", str(result["scope"]))

    def test_checker_that_trusts_the_claim_fails_calibration(self) -> None:
        weak = self._checker(
            "weak.py",
            "import json, sys\n"
            "receipt = json.load(open(sys.argv[1]))\n"
            "sys.exit(0 if receipt.get('verification_passed') is True else 1)\n",
        )
        result = self._run(weak)
        self.assertEqual(result["status"], "calibration-failed")
        rows = {row["role"]: row for row in result["cases"]}
        self.assertFalse(rows["known_failure"]["matches"])
        self.assertEqual(rows["known_failure"]["exit_code"], 0)

    def test_syntax_error_is_not_a_successful_rejection(self) -> None:
        broken = self._checker("broken.py", "def main(:\n")
        result = self._run(broken)
        self.assertEqual(result["status"], "calibration-failed")
        rows = {row["role"]: row for row in result["cases"]}
        self.assertEqual(rows["known_failure"]["exit_code"], 1)
        self.assertFalse(rows["known_failure"]["rejection_diagnostic"])

    def test_checker_that_changes_an_input_stops_calibration(self) -> None:
        mutating = self._checker(
            "mutating.py",
            "import sys\n"
            "open(sys.argv[1], 'a').write(' ')\n"
            "print('REJECT: persisted state differs from expected')\n"
            "sys.exit(1)\n",
        )
        result = self._run(mutating)
        self.assertEqual(result["status"], "calibration-failed")
        self.assertFalse(result["inputs_unchanged"])
        self.assertEqual(len(result["cases"]), 1)

    def test_hanging_checker_times_out_and_fails(self) -> None:
        hanging = self._checker("hanging.py", "import time\ntime.sleep(30)\n")
        result = self._run(hanging, timeout=0.5)
        self.assertEqual(result["status"], "calibration-failed")
        self.assertTrue(result["cases"][0]["timed_out"])

    def test_command_must_invoke_the_fingerprinted_checker(self) -> None:
        checker = self.directory / "check_update_receipt.py"
        other = self._checker("other.py", "import sys\nsys.exit(0)\n")
        with self.assertRaisesRegex(calibrate_check.CalibrationError, "fingerprinted checker"):
            calibrate_check.calibrate(
                checker, self.cases, [sys.executable, str(other), "{case}"], DIAGNOSTIC
            )

    def test_cases_must_have_distinct_bytes(self) -> None:
        shutil.copy2(self.cases["valid"], self.cases["allowed_variation"])
        with self.assertRaisesRegex(calibrate_check.CalibrationError, "distinct bytes"):
            self._run(self.directory / "check_update_receipt.py")

    def test_main_reports_verified_failed_and_invalid_requests(self) -> None:
        def argv(checker: Path, diagnostic: str = DIAGNOSTIC) -> list[str]:
            return [
                "--checker",
                str(checker),
                "--known-failure",
                str(self.cases["known_failure"]),
                "--valid",
                str(self.cases["valid"]),
                "--allowed-variation",
                str(self.cases["allowed_variation"]),
                "--diagnostic",
                diagnostic,
                "--",
                sys.executable,
                str(checker),
                "{case}",
            ]

        good = self.directory / "check_update_receipt.py"
        self.assertEqual(calibrate_check.main(argv(good)), 0)
        self.assertEqual(calibrate_check.main(argv(good, "unrelated diagnostic")), 1)
        self.assertEqual(calibrate_check.main(argv(good, "x")), 2)
        receipt = json.loads((self.directory / "known-failure.json").read_text())
        self.assertTrue(receipt["verification_passed"])


if __name__ == "__main__":
    unittest.main()
