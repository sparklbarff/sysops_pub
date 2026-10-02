from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import update_supervisor


class UpdateSupervisorTests(unittest.TestCase):
    def test_initialize_is_dry_run_by_default(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-supervisor-") as directory:
            target = Path(directory) / "sandbox"
            update_supervisor.initialize(target, execute=False)
            self.assertFalse(target.exists())

    def test_check_classifies_current_update_and_deferred(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-supervisor-") as directory:
            target = Path(directory) / "sandbox"
            update_supervisor.initialize(target, execute=True)
            entries = update_supervisor.check(target)
            statuses = {(entry["channel"], entry["name"]): entry["status"] for entry in entries}
            self.assertEqual(statuses[("cli-tools", "formatter")], "update")
            self.assertEqual(statuses[("cli-tools", "retriever")], "current")
            self.assertEqual(statuses[("desktop-apps", "model-runner")], "deferred")
            self.assertEqual(statuses[("desktop-apps", "terminal")], "update")

    def test_apply_preview_does_not_change_state_or_write_receipt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-supervisor-") as directory:
            target = Path(directory) / "sandbox"
            update_supervisor.initialize(target, execute=True)
            state_path = target / update_supervisor.STATE_NAME
            before = state_path.read_bytes()
            receipt = update_supervisor.apply(target, "cli-tools", execute=False)
            self.assertIsNone(receipt)
            self.assertEqual(state_path.read_bytes(), before)
            self.assertFalse((target / update_supervisor.RECEIPTS_NAME).exists())

    def test_apply_updates_one_channel_and_records_verified_receipt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-supervisor-") as directory:
            target = Path(directory) / "sandbox"
            update_supervisor.initialize(target, execute=True)
            before = json.loads((target / update_supervisor.STATE_NAME).read_text())
            fixed_time = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
            receipt_path = update_supervisor.apply(
                target,
                "cli-tools",
                execute=True,
                clock=lambda: fixed_time,
            )
            self.assertIsNotNone(receipt_path)
            assert receipt_path is not None
            self.assertEqual(receipt_path.name, "update-20260102T030405Z.json")
            receipt = json.loads(receipt_path.read_text())
            after = json.loads((target / update_supervisor.STATE_NAME).read_text())
            self.assertTrue(receipt["verification_passed"])
            self.assertEqual(after["channels"]["cli-tools"]["formatter"]["version"], "2.0.0")
            self.assertEqual(after["channels"]["desktop-apps"], before["channels"]["desktop-apps"])

    def test_running_application_is_deferred_while_sibling_updates(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-supervisor-") as directory:
            target = Path(directory) / "sandbox"
            update_supervisor.initialize(target, execute=True)
            receipt_path = update_supervisor.apply(target, "desktop-apps", execute=True)
            assert receipt_path is not None
            state = json.loads((target / update_supervisor.STATE_NAME).read_text())
            self.assertEqual(state["channels"]["desktop-apps"]["model-runner"]["version"], "1.4.0")
            self.assertEqual(state["channels"]["desktop-apps"]["terminal"]["version"], "4.2.0")
            receipt = json.loads(receipt_path.read_text())
            actions = {item["name"]: item["action"] for item in receipt["actions"]}
            self.assertEqual(actions["model-runner"], "deferred")
            self.assertEqual(actions["terminal"], "updated")

    def test_marker_is_required_and_unknown_channel_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-supervisor-") as directory:
            target = Path(directory) / "sandbox"
            target.mkdir()
            (target / update_supervisor.STATE_NAME).write_text("{}", encoding="utf-8")
            with self.assertRaises(update_supervisor.UpdateError):
                update_supervisor.check(target)

            other = Path(directory) / "other"
            update_supervisor.initialize(other, execute=True)
            with self.assertRaises(update_supervisor.UpdateError):
                update_supervisor.apply(other, "unknown", execute=False)

    def test_symlink_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-supervisor-") as directory:
            parent = Path(directory)
            real = parent / "real"
            real.mkdir()
            link = parent / "link"
            link.symlink_to(real, target_is_directory=True)
            with self.assertRaises(update_supervisor.UpdateError):
                update_supervisor.initialize(link, execute=True)

    def test_existing_receipt_is_not_overwritten_or_followed_by_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-supervisor-") as directory:
            target = Path(directory) / "sandbox"
            update_supervisor.initialize(target, execute=True)
            fixed_time = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
            update_supervisor.apply(target, "cli-tools", execute=True, clock=lambda: fixed_time)
            state_path = target / update_supervisor.STATE_NAME
            before = state_path.read_bytes()
            with self.assertRaises(update_supervisor.UpdateError):
                update_supervisor.apply(
                    target,
                    "desktop-apps",
                    execute=True,
                    clock=lambda: fixed_time,
                )
            self.assertEqual(state_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
