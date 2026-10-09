from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import managed_job


class ManagedJobTests(unittest.TestCase):
    def test_nonfinite_timeout_is_refused_before_launch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="managed-job-") as directory:
            for timeout in (float("inf"), float("nan"), 0, -1):
                with self.subTest(timeout=timeout), self.assertRaises(managed_job.ManagedJobError):
                    managed_job.run_managed(
                        [sys.executable, "-c", "raise SystemExit(0)"],
                        Path(directory) / "invalid.json",
                        timeout=timeout,
                    )

    @unittest.skipUnless(os.name == "posix", "POSIX process-group proof")
    def test_successful_leader_cannot_abandon_a_child(self) -> None:
        with tempfile.TemporaryDirectory(prefix="managed-job-") as directory:
            pid_file = Path(directory) / "child.pid"
            receipt = Path(directory) / "orphan.json"
            code = (
                "import subprocess,sys,pathlib; "
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
                "pathlib.Path(sys.argv[1]).write_text(str(p.pid))"
            )
            child_pid = None
            try:
                return_code = managed_job.run_managed(
                    [sys.executable, "-c", code, str(pid_file)], receipt, timeout=2
                )
                child_pid = int(pid_file.read_text())
                self.assertNotEqual(return_code, 0)
                value = json.loads(receipt.read_text())
                self.assertTrue(value["termination_attempted"])
                self.assertTrue(value["owned_group_terminal"])
            finally:
                if child_pid is None and pid_file.exists():
                    child_pid = int(pid_file.read_text())
                if child_pid is not None:
                    try:
                        os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    @unittest.skipUnless(os.name == "posix", "POSIX process-group proof")
    def test_timeout_cleans_child_that_ignores_term_and_leaves_unrelated_job_alone(self) -> None:
        with tempfile.TemporaryDirectory(prefix="managed-job-") as directory:
            pid_file = Path(directory) / "child.pid"
            receipt = Path(directory) / "descendant-timeout.json"
            child_code = (
                "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)"
            )
            leader_code = (
                "import subprocess,sys,pathlib,time; "
                "p=subprocess.Popen([sys.executable,'-c',sys.argv[2]]); "
                "pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(30)"
            )
            unrelated = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
            )
            child_pid = None
            try:
                return_code = managed_job.run_managed(
                    [sys.executable, "-c", leader_code, str(pid_file), child_code],
                    receipt,
                    timeout=0.5,
                )
                child_pid = int(pid_file.read_text())
                self.assertEqual(return_code, managed_job.TIMEOUT_RETURN_CODE)
                self.assertTrue(json.loads(receipt.read_text())["owned_group_terminal"])
                self.assertIsNone(unrelated.poll())
            finally:
                if child_pid is None and pid_file.exists():
                    child_pid = int(pid_file.read_text())
                if child_pid is not None:
                    try:
                        os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                unrelated.terminate()
                unrelated.wait(timeout=3)

    def test_success_is_waited_for_and_receipted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="managed-job-") as directory:
            receipt = Path(directory) / "success.json"
            return_code = managed_job.run_managed(
                [sys.executable, "-c", "raise SystemExit(0)"], receipt
            )
            self.assertEqual(return_code, 0)
            value = json.loads(receipt.read_text())
            self.assertEqual(value["return_code"], 0)
            self.assertFalse(value["timed_out"])
            self.assertIsInstance(value["process_id"], int)

    def test_failure_code_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory(prefix="managed-job-") as directory:
            receipt = Path(directory) / "failure.json"
            return_code = managed_job.run_managed(
                [sys.executable, "-c", "raise SystemExit(7)"], receipt
            )
            self.assertEqual(return_code, 7)
            self.assertEqual(json.loads(receipt.read_text())["return_code"], 7)

    def test_timeout_terminates_only_the_owned_process(self) -> None:
        with tempfile.TemporaryDirectory(prefix="managed-job-") as directory:
            receipt = Path(directory) / "timeout.json"
            return_code = managed_job.run_managed(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                receipt,
                timeout=0.05,
            )
            self.assertEqual(return_code, managed_job.TIMEOUT_RETURN_CODE)
            value = json.loads(receipt.read_text())
            self.assertTrue(value["timed_out"])
            self.assertTrue(value["termination_attempted"])

    def test_receipt_omits_command_arguments(self) -> None:
        with tempfile.TemporaryDirectory(prefix="managed-job-") as directory:
            receipt = Path(directory) / "sanitized.json"
            secret_argument = "synthetic-sensitive-argument"
            managed_job.run_managed(
                [sys.executable, "-c", "raise SystemExit(0)", secret_argument], receipt
            )
            text = receipt.read_text()
            self.assertNotIn(secret_argument, text)
            self.assertEqual(json.loads(text)["argument_count"], 3)

    def test_existing_receipt_is_refused(self) -> None:
        with tempfile.TemporaryDirectory(prefix="managed-job-") as directory:
            receipt = Path(directory) / "existing.json"
            receipt.write_text("do not replace", encoding="utf-8")
            with self.assertRaises(managed_job.ManagedJobError):
                managed_job.run_managed([sys.executable, "-c", "pass"], receipt)
            self.assertEqual(receipt.read_text(), "do not replace")

    def test_missing_command_is_rejected(self) -> None:
        with (
            tempfile.TemporaryDirectory(prefix="managed-job-") as directory,
            self.assertRaises(managed_job.ManagedJobError),
        ):
            managed_job.run_managed([], Path(directory) / "missing.json")

    def test_symlink_receipt_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="managed-job-") as directory:
            parent = Path(directory)
            destination = parent / "destination.json"
            destination.write_text("preserve", encoding="utf-8")
            receipt = parent / "receipt.json"
            receipt.symlink_to(destination)
            with self.assertRaises(managed_job.ManagedJobError):
                managed_job.run_managed([sys.executable, "-c", "pass"], receipt)
            self.assertEqual(destination.read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
