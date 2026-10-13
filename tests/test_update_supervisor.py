from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import update_supervisor


class UpdateSupervisorTests(unittest.TestCase):
    def test_verification_reads_disk_instead_of_the_mutation_dictionary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-supervisor-") as directory:
            target = Path(directory) / "sandbox"
            update_supervisor.initialize(target, execute=True)
            original = (target / update_supervisor.STATE_NAME).read_bytes()
            writer = update_supervisor._write_json_atomic

            def dropped_write(path: Path, value: object) -> None:
                if path.name == update_supervisor.STATE_NAME:
                    path.write_bytes(original)
                else:
                    writer(path, value)

            with (
                mock.patch.object(update_supervisor, "_write_json_atomic", dropped_write),
                self.assertRaisesRegex(update_supervisor.UpdateError, "verification failed"),
            ):
                update_supervisor.apply(target, "cli-tools", execute=True)
            receipts = list((target / update_supervisor.RECEIPTS_NAME).glob("*.json"))
            self.assertEqual(len(receipts), 1)
            self.assertFalse(json.loads(receipts[0].read_text())["verification_passed"])

    def test_failed_update_persists_until_a_later_run_resolves_it(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-supervisor-") as directory:
            target = Path(directory) / "sandbox"
            update_supervisor.initialize(target, execute=True)
            original = (target / update_supervisor.STATE_NAME).read_bytes()
            writer = update_supervisor._write_json_atomic

            def dropped_write(path: Path, value: object) -> None:
                if path.name == update_supervisor.STATE_NAME:
                    path.write_bytes(original)
                else:
                    writer(path, value)

            first = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
            with (
                mock.patch.object(update_supervisor, "_write_json_atomic", dropped_write),
                self.assertRaisesRegex(update_supervisor.UpdateError, "verification failed"),
            ):
                update_supervisor.apply(target, "cli-tools", execute=True, clock=lambda: first)
            record = target / update_supervisor.UNRESOLVED_NAME
            self.assertEqual(json.loads(record.read_text()), {"cli-tools/formatter": "2.0.0"})
            # A plain check that changes nothing must not read as all-clear.
            with self.assertRaisesRegex(update_supervisor.UnresolvedError, "cli-tools/formatter"):
                update_supervisor.check(target)
            later = datetime(2026, 1, 2, 3, 4, 6, tzinfo=UTC)
            update_supervisor.apply(target, "cli-tools", execute=True, clock=lambda: later)
            self.assertEqual(json.loads(record.read_text()), {})
            update_supervisor.check(target)

    def test_pin_is_satisfied_by_the_catalog_current_version(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-supervisor-") as directory:
            target = Path(directory) / "sandbox"
            update_supervisor.initialize(target, execute=True)
            first = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
            update_supervisor.apply(target, "cli-tools", execute=True, clock=lambda: first)
            record = target / update_supervisor.UNRESOLVED_NAME
            # The failed run targeted 1.9.0; the catalog has since moved to 2.0.0, now installed.
            record.write_text(json.dumps({"cli-tools/formatter": "1.9.0"}), encoding="utf-8")
            update_supervisor.check(target)
            self.assertEqual(json.loads(record.read_text()), {"cli-tools/formatter": "1.9.0"})
            later = datetime(2026, 1, 2, 3, 4, 6, tzinfo=UTC)
            update_supervisor.apply(target, "cli-tools", execute=True, clock=lambda: later)
            self.assertEqual(json.loads(record.read_text()), {})

    def test_check_never_writes_the_record(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-supervisor-") as directory:
            target = Path(directory) / "sandbox"
            update_supervisor.initialize(target, execute=True)
            record = target / update_supervisor.UNRESOLVED_NAME
            update_supervisor.check(target)
            self.assertFalse(record.exists())
            for pins in ({"cli-tools/retriever": "3.1.0"}, {}):
                with self.subTest(pins=pins):
                    record.write_text(json.dumps(pins), encoding="utf-8")
                    before = (record.read_bytes(), record.stat().st_mtime_ns)
                    update_supervisor.check(target)
                    self.assertEqual((record.read_bytes(), record.stat().st_mtime_ns), before)

    def test_collateral_damage_survives_a_later_check_until_repaired(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-supervisor-") as directory:
            target = Path(directory) / "sandbox"
            update_supervisor.initialize(target, execute=True)
            writer = update_supervisor._write_json_atomic

            def collateral_write(path: Path, value: object) -> None:
                writer(path, value)
                if path.name == update_supervisor.STATE_NAME:
                    state = json.loads(path.read_text())
                    state["channels"]["desktop-apps"]["terminal"]["version"] = "unexpected"
                    writer(path, state)

            first = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
            with (
                mock.patch.object(update_supervisor, "_write_json_atomic", collateral_write),
                self.assertRaisesRegex(update_supervisor.UpdateError, "verification failed"),
            ):
                update_supervisor.apply(target, "cli-tools", execute=True, clock=lambda: first)
            record = target / update_supervisor.UNRESOLVED_NAME
            self.assertEqual(json.loads(record.read_text()), {"desktop-apps/terminal": "4.0.0"})
            with self.assertRaisesRegex(
                update_supervisor.UnresolvedError, "desktop-apps/terminal expected 4.0.0"
            ):
                update_supervisor.check(target)
            state_path = target / update_supervisor.STATE_NAME
            state = json.loads(state_path.read_text())
            state["channels"]["desktop-apps"]["terminal"]["version"] = "4.0.0"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            update_supervisor.check(target)
            self.assertEqual(json.loads(record.read_text()), {"desktop-apps/terminal": "4.0.0"})
            later = datetime(2026, 1, 2, 3, 4, 6, tzinfo=UTC)
            update_supervisor.apply(target, "cli-tools", execute=True, clock=lambda: later)
            self.assertEqual(json.loads(record.read_text()), {})

    def test_pin_still_fails_when_the_update_never_happened(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-supervisor-") as directory:
            target = Path(directory) / "sandbox"
            update_supervisor.initialize(target, execute=True)
            record = target / update_supervisor.UNRESOLVED_NAME
            record.write_text(json.dumps({"desktop-apps/model-runner": "1.5.0"}), encoding="utf-8")
            with self.assertRaisesRegex(update_supervisor.UnresolvedError, "observed 1.4.0"):
                update_supervisor.check(target)
            self.assertEqual(json.loads(record.read_text()), {"desktop-apps/model-runner": "1.5.0"})

    def test_verification_rejects_changes_to_an_unselected_channel(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-supervisor-") as directory:
            target = Path(directory) / "sandbox"
            update_supervisor.initialize(target, execute=True)
            writer = update_supervisor._write_json_atomic

            def collateral_write(path: Path, value: object) -> None:
                writer(path, value)
                if path.name == update_supervisor.STATE_NAME:
                    state = json.loads(path.read_text())
                    state["channels"]["desktop-apps"]["terminal"]["version"] = "unexpected"
                    writer(path, state)

            with (
                mock.patch.object(update_supervisor, "_write_json_atomic", collateral_write),
                self.assertRaisesRegex(update_supervisor.UpdateError, "verification failed"),
            ):
                update_supervisor.apply(target, "cli-tools", execute=True)

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

    def test_output_paths_that_leave_the_sandbox_are_refused_before_any_write(self) -> None:
        fixed_time = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        cases = ("receipts-symlink", "receipts-file", "unresolved-symlink", "receipt-symlink")
        for case in cases:
            with (
                self.subTest(case=case),
                tempfile.TemporaryDirectory(prefix="update-supervisor-") as directory,
            ):
                target = Path(directory) / "sandbox"
                outside = Path(directory) / "outside"
                outside.mkdir()
                victim = outside / "victim.json"
                victim.write_text("keep\n", encoding="utf-8")
                update_supervisor.initialize(target, execute=True)
                receipts = target / update_supervisor.RECEIPTS_NAME
                if case == "receipts-symlink":
                    receipts.symlink_to(outside, target_is_directory=True)
                elif case == "receipts-file":
                    receipts.write_text("not a directory\n", encoding="utf-8")
                elif case == "unresolved-symlink":
                    (target / update_supervisor.UNRESOLVED_NAME).symlink_to(victim)
                else:
                    receipts.mkdir()
                    (receipts / "update-20260102T030405Z.json").symlink_to(victim)
                state_path = target / update_supervisor.STATE_NAME
                before = state_path.read_bytes()
                with self.assertRaises(update_supervisor.UpdateError):
                    update_supervisor.apply(
                        target, "cli-tools", execute=True, clock=lambda: fixed_time
                    )
                self.assertEqual(state_path.read_bytes(), before)
                self.assertEqual(sorted(path.name for path in outside.iterdir()), ["victim.json"])
                self.assertEqual(victim.read_text(encoding="utf-8"), "keep\n")

    def test_planted_temporary_paths_are_never_written_through(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-supervisor-") as directory:
            target = Path(directory) / "sandbox"
            victim = Path(directory) / "victim.json"
            victim.write_text("keep\n", encoding="utf-8")
            update_supervisor.initialize(target, execute=True)
            receipts = target / update_supervisor.RECEIPTS_NAME
            receipts.mkdir()
            fixed_time = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
            for planted in (
                target / f".{update_supervisor.STATE_NAME}.tmp",
                target / f".{update_supervisor.UNRESOLVED_NAME}.tmp",
                receipts / ".update-20260102T030405Z.json.tmp",
            ):
                planted.symlink_to(victim)
            (target / update_supervisor.UNRESOLVED_NAME).write_text("{}", encoding="utf-8")
            receipt_path = update_supervisor.apply(
                target, "cli-tools", execute=True, clock=lambda: fixed_time
            )
            assert receipt_path is not None
            self.assertTrue(json.loads(receipt_path.read_text())["verification_passed"])
            self.assertEqual(victim.read_text(encoding="utf-8"), "keep\n")

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
