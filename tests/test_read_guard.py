from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples" / "enforcement"))

import read_guard

SCRIPT = ROOT / "examples" / "enforcement" / "read_guard.py"
SESSION = "read-guard-test-session"


class ReadGuardTests(unittest.TestCase):
    def run_guard(
        self, state: Path, mode: str, payload: dict[str, object], *, codex: bool = False
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment[read_guard.STATE_ENVIRONMENT] = str(state)
        return subprocess.run(
            [sys.executable, str(SCRIPT), mode, "--codex-hook" if codex else "--claude-hook"],
            input=json.dumps({"session_id": SESSION, **payload}),
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def test_edit_needs_a_read_first_and_a_read_admits_it(self) -> None:
        with tempfile.TemporaryDirectory(prefix="read-guard-") as directory:
            state = Path(directory) / "state"
            target = Path(directory) / "notes.md"
            target.write_text("one\n", encoding="utf-8")
            edit = {"tool_name": "Edit", "tool_input": {"file_path": str(target)}}
            blocked = self.run_guard(state, "check", edit)
            self.assertEqual(blocked.returncode, 2, blocked.stdout)
            self.assertIn("has not been read this session", blocked.stderr)
            recorded = self.run_guard(
                state, "record", {"tool_name": "Read", "tool_input": {"file_path": str(target)}}
            )
            self.assertEqual(recorded.returncode, 0, recorded.stderr)
            admitted = self.run_guard(state, "check", edit)
            self.assertEqual(admitted.returncode, 0, admitted.stderr)
            self.assertIn("ALLOWED", admitted.stdout)
            self.assertEqual(list(state.iterdir()), [state / f"{SESSION}.json"])

    def test_a_file_changed_since_the_read_is_stale_until_read_again(self) -> None:
        with tempfile.TemporaryDirectory(prefix="read-guard-") as directory:
            state = Path(directory) / "state"
            target = Path(directory) / "notes.md"
            target.write_text("one\n", encoding="utf-8")
            read = {"tool_name": "Read", "tool_input": {"file_path": str(target)}}
            edit = {"tool_name": "Edit", "tool_input": {"file_path": str(target)}}
            self.run_guard(state, "record", read)
            target.write_text("two\n", encoding="utf-8")
            stale = self.run_guard(state, "check", edit)
            self.assertEqual(stale.returncode, 2, stale.stdout)
            self.assertIn("changed on disk since it was read", stale.stderr)
            shell = {
                "tool_name": "Bash",
                "tool_input": {"command": f"sed -i 's/two/three/' {target}"},
                "cwd": directory,
            }
            routed = self.run_guard(state, "shell", shell)
            self.assertEqual(routed.returncode, 2, routed.stdout)
            self.assertIn("pending stale-read block", routed.stderr)
            relative = {
                "tool_name": "Bash",
                "tool_input": {"command": "python3 -c \"open('notes.md','w')\""},
                "cwd": directory,
            }
            self.assertEqual(self.run_guard(state, "shell", relative).returncode, 2)
            unrelated = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": directory}
            self.assertEqual(self.run_guard(state, "shell", unrelated).returncode, 0)
            self.run_guard(state, "record", read)
            self.assertEqual(self.run_guard(state, "check", edit).returncode, 0)
            self.assertEqual(self.run_guard(state, "shell", shell).returncode, 0)

    def test_write_is_exempt_and_records_its_result(self) -> None:
        with tempfile.TemporaryDirectory(prefix="read-guard-") as directory:
            state = Path(directory) / "state"
            target = Path(directory) / "new.md"
            write = {"tool_name": "Write", "tool_input": {"file_path": str(target)}}
            self.assertEqual(self.run_guard(state, "check", write).returncode, 0)
            target.write_text("written\n", encoding="utf-8")
            self.assertEqual(self.run_guard(state, "record", write).returncode, 0)
            edit = {"tool_name": "Edit", "tool_input": {"file_path": str(target)}}
            self.assertEqual(self.run_guard(state, "check", edit).returncode, 0)

    def test_sessions_do_not_share_reads(self) -> None:
        with tempfile.TemporaryDirectory(prefix="read-guard-") as directory:
            state = Path(directory) / "state"
            target = Path(directory) / "notes.md"
            target.write_text("one\n", encoding="utf-8")
            self.run_guard(
                state, "record", {"tool_name": "Read", "tool_input": {"file_path": str(target)}}
            )
            environment = os.environ.copy()
            environment[read_guard.STATE_ENVIRONMENT] = str(state)
            other = subprocess.run(
                [sys.executable, str(SCRIPT), "check", "--claude-hook"],
                input=json.dumps(
                    {
                        "session_id": "another-session",
                        "tool_name": "Edit",
                        "tool_input": {"file_path": str(target)},
                    }
                ),
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(other.returncode, 2, other.stdout)

    def test_check_fails_closed_on_malformed_input(self) -> None:
        with tempfile.TemporaryDirectory(prefix="read-guard-") as directory:
            state = Path(directory) / "state"
            environment = os.environ.copy()
            environment[read_guard.STATE_ENVIRONMENT] = str(state)
            for payload in ("not-json", json.dumps({"tool_name": "Edit", "tool_input": {}})):
                with self.subTest(payload=payload):
                    result = subprocess.run(
                        [sys.executable, str(SCRIPT), "check", "--claude-hook"],
                        input=payload,
                        check=False,
                        capture_output=True,
                        text=True,
                        env=environment,
                    )
                    self.assertEqual(result.returncode, 2, result.stdout)
                    self.assertIn("BLOCKED", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
            missing_session = self.run_guard(
                state,
                "check",
                {"session_id": "", "tool_name": "Edit", "tool_input": {"file_path": "x"}},
            )
            self.assertEqual(missing_session.returncode, 2)
            self.assertIn("session identifier", missing_session.stderr)

    def test_record_never_blocks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="read-guard-") as directory:
            state = Path(directory) / "state"
            result = self.run_guard(state, "record", {"tool_name": "Read", "tool_input": {}})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("could not record", result.stderr)
            ignored = self.run_guard(
                state, "record", {"tool_name": "Bash", "tool_input": {"command": "ls"}}
            )
            self.assertEqual(ignored.returncode, 0)
            self.assertFalse(state.exists())

    def test_direct_mode_matches_the_hook_mode(self) -> None:
        with tempfile.TemporaryDirectory(prefix="read-guard-") as directory:
            state = Path(directory) / "state"
            target = Path(directory) / "notes.md"
            target.write_text("one\n", encoding="utf-8")
            common = ["--state-dir", str(state), "--session", SESSION]
            blocked = subprocess.run(
                [sys.executable, str(SCRIPT), "check", *common, "--path", str(target)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(blocked.returncode, 2, blocked.stdout)
            recorded = subprocess.run(
                [sys.executable, str(SCRIPT), "record", *common, "--path", str(target)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(recorded.returncode, 0, recorded.stderr)
            admitted = subprocess.run(
                [sys.executable, str(SCRIPT), "check", *common, "--path", str(target)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(admitted.returncode, 0, admitted.stderr)


if __name__ == "__main__":
    unittest.main()
