from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import managed_job

RUNNER = ROOT / "tools" / "managed_job.py"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for(predicate: object, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if callable(predicate) and predicate():
            return True
        time.sleep(0.05)
    return False


class ManagedJobTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "POSIX signal and process-group proof")
    def test_cancelling_the_runner_cleans_up_its_job_and_writes_the_receipt(self) -> None:
        leader = (
            "import subprocess,sys,pathlib,time; "
            "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
            "pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(30)"
        )
        for signum in (signal.SIGTERM, signal.SIGHUP):
            with (
                self.subTest(signal=signum.name),
                tempfile.TemporaryDirectory(prefix="managed-job-") as directory,
            ):
                pid_file = Path(directory) / "child.pid"
                receipt = Path(directory) / "cancelled.json"
                unrelated = subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
                )
                runner = subprocess.Popen(
                    [
                        sys.executable,
                        str(RUNNER),
                        "--receipt",
                        str(receipt),
                        "--",
                        sys.executable,
                        "-c",
                        leader,
                        str(pid_file),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                child_pid = None
                try:
                    self.assertTrue(_wait_for(pid_file.exists, 10), "job never started its child")
                    child_pid = pid = int(pid_file.read_text())
                    runner.send_signal(signum)
                    self.assertEqual(runner.wait(timeout=15), 128 + signum)
                    value = json.loads(receipt.read_text())
                    self.assertTrue(value["interrupted"])
                    self.assertTrue(value["owned_group_terminal"])
                    self.assertEqual(value["return_code"], 128 + signum)
                    self.assertTrue(
                        _wait_for(lambda pid=pid: not _alive(pid), 5),
                        "job child outlived the runner",
                    )
                    self.assertIsNone(unrelated.poll())
                finally:
                    if runner.poll() is None:
                        runner.kill()
                        runner.wait(timeout=5)
                    if child_pid is not None and _alive(child_pid):
                        os.kill(child_pid, signal.SIGKILL)
                    unrelated.terminate()
                    unrelated.wait(timeout=5)

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

    @unittest.skipUnless(os.name == "posix", "POSIX process-group proof")
    def test_ownership_verdict_survives_a_sandbox_that_refuses_to_spawn_ps(self) -> None:
        """A sandboxed runtime can refuse to exec ps; the probe must not depend on it."""
        with tempfile.TemporaryDirectory(prefix="managed-job-") as directory:
            receipt = Path(directory) / "sandboxed.json"
            refused = PermissionError("forbidden-exec-sugid")
            with mock.patch.object(managed_job.subprocess, "run", side_effect=refused):
                return_code = managed_job.run_managed(
                    [sys.executable, "-c", "raise SystemExit(0)"], receipt
                )
            self.assertEqual(return_code, 0)
            value = json.loads(receipt.read_text())
            self.assertTrue(value["owned_group_terminal"])
            self.assertFalse(value["leftover_children"])

    @unittest.skipUnless(os.name == "posix", "POSIX process-group proof")
    def test_child_that_exited_before_its_leader_is_not_a_leftover(self) -> None:
        with tempfile.TemporaryDirectory(prefix="managed-job-") as directory:
            receipt = Path(directory) / "reaped.json"
            code = (
                "import subprocess,sys,time; "
                "subprocess.Popen([sys.executable,'-c','pass']); time.sleep(0.2)"
            )
            return_code = managed_job.run_managed([sys.executable, "-c", code], receipt)
            self.assertEqual(return_code, 0)
            value = json.loads(receipt.read_text())
            self.assertFalse(value["leftover_children"])
            self.assertTrue(value["owned_group_terminal"])

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
