from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import control  # noqa: E402


class ControlLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="sysops-pub-test-")
        self.target = Path(self.temporary.name) / "sandbox"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_control(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = control.main(list(arguments))
        return result, stdout.getvalue(), stderr.getvalue()

    def initialize(self) -> None:
        result, _stdout, stderr = self.run_control("init", "--target", str(self.target))
        self.assertEqual(result, 0, stderr)

    def write_profile(self, components: dict[str, object]) -> Path:
        profile = Path(self.temporary.name) / "profile.json"
        profile.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "name": "test-profile",
                    "components": components,
                }
            ),
            encoding="utf-8",
        )
        return profile

    def test_dry_run_does_not_write_managed_files(self) -> None:
        self.initialize()
        result, stdout, stderr = self.run_control("apply", "--target", str(self.target))
        self.assertEqual(result, 0, stderr)
        self.assertIn("dry-run only", stdout)
        self.assertFalse((self.target / ".config").exists())

    def test_execute_then_verify(self) -> None:
        self.initialize()
        result, _stdout, stderr = self.run_control(
            "apply", "--target", str(self.target), "--execute"
        )
        self.assertEqual(result, 0, stderr)
        result, stdout, stderr = self.run_control("verify", "--target", str(self.target))
        self.assertEqual(result, 0, stderr)
        self.assertIn("MATCH", stdout)

    def test_verification_detects_drift_and_scoped_apply_repairs_it(self) -> None:
        self.initialize()
        self.assertEqual(self.run_control("apply", "--target", str(self.target), "--execute")[0], 0)
        banner = self.target / ".config/sysops_pub/shell-banner/banner.txt"
        banner.write_text("changed\n", encoding="utf-8")

        result, stdout, _stderr = self.run_control("verify", "--target", str(self.target))
        self.assertEqual(result, 1)
        self.assertIn("DRIFT", stdout)

        result, _stdout, stderr = self.run_control(
            "--component",
            "shell-banner",
            "apply",
            "--target",
            str(self.target),
            "--execute",
        )
        self.assertEqual(result, 0, stderr)
        self.assertEqual(self.run_control("verify", "--target", str(self.target))[0], 0)

    def test_execute_refuses_unmarked_target(self) -> None:
        self.target.mkdir()
        result, _stdout, stderr = self.run_control(
            "apply", "--target", str(self.target), "--execute"
        )
        self.assertEqual(result, 2)
        self.assertIn("not a marked", stderr)

    def test_init_refuses_nonempty_directory(self) -> None:
        self.target.mkdir()
        (self.target / "existing.txt").write_text("keep\n", encoding="utf-8")
        result, _stdout, stderr = self.run_control("init", "--target", str(self.target))
        self.assertEqual(result, 2)
        self.assertIn("non-empty", stderr)
        self.assertEqual((self.target / "existing.txt").read_text(encoding="utf-8"), "keep\n")

    def test_registry_rejects_parent_traversal(self) -> None:
        registry = Path(self.temporary.name) / "bad-registry.json"
        profile = Path(self.temporary.name) / "bad-profile.json"
        registry.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "components": [
                        {
                            "name": "agent-policy",
                            "source": "../outside",
                            "destination": ".config/example",
                            "platforms": ["any"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        profile.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "name": "bad-registry-test",
                    "components": {"agent-policy": {"enabled": True}},
                }
            ),
            encoding="utf-8",
        )
        self.initialize()
        result, _stdout, stderr = self.run_control(
            "--registry",
            str(registry),
            "--profile",
            str(profile),
            "plan",
            "--target",
            str(self.target),
        )
        self.assertEqual(result, 2)
        self.assertIn("non-traversing", stderr)

    def test_report_json_is_machine_readable(self) -> None:
        self.initialize()
        result, stdout, stderr = self.run_control("report", "--target", str(self.target), "--json")
        self.assertEqual(result, 0, stderr)
        report = json.loads(stdout)
        self.assertEqual(report["summary"], {"missing": 2})
        self.assertEqual(len(report["files"]), 2)

    def test_profile_rejects_non_boolean_enabled_value(self) -> None:
        profile = self.write_profile({"agent-policy": {"enabled": "true"}})
        self.initialize()
        result, _stdout, stderr = self.run_control(
            "--profile", str(profile), "verify", "--target", str(self.target)
        )
        self.assertEqual(result, 2)
        self.assertIn("enabled must be a boolean", stderr)

    def test_profile_rejects_zero_enabled_components(self) -> None:
        profile = self.write_profile({"agent-policy": {"enabled": False}})
        self.initialize()
        result, _stdout, stderr = self.run_control(
            "--profile", str(profile), "verify", "--target", str(self.target)
        )
        self.assertEqual(result, 2)
        self.assertIn("must enable at least one", stderr)

    def test_enabled_component_rejects_empty_source(self) -> None:
        fixture_root = Path(self.temporary.name) / "fixture-repository"
        source = fixture_root / "components" / "empty" / "desired"
        source.mkdir(parents=True)
        fixture_root = fixture_root.resolve()
        registry = fixture_root / "registry.json"
        registry.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "components": [
                        {
                            "name": "empty",
                            "source": "components/empty/desired",
                            "destination": ".config/empty",
                            "platforms": ["any"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        profile = self.write_profile({"empty": {"enabled": True}})
        self.initialize()
        with mock.patch.object(control, "REPO_ROOT", fixture_root):
            result, _stdout, stderr = self.run_control(
                "--registry",
                str(registry),
                "--profile",
                str(profile),
                "verify",
                "--target",
                str(self.target),
            )
        self.assertEqual(result, 2)
        self.assertIn("has no managed files", stderr)

    @unittest.skipIf(os.name == "nt", "symlink creation may require elevated Windows privileges")
    def test_component_rejects_symlink_declared_as_source_root(self) -> None:
        fixture_root = Path(self.temporary.name) / "fixture-repository"
        real_source = fixture_root / "components" / "real" / "desired"
        real_source.mkdir(parents=True)
        (real_source / "file.txt").write_text("synthetic\n", encoding="utf-8")
        linked_source = fixture_root / "components" / "linked"
        linked_source.symlink_to(real_source, target_is_directory=True)
        registry = fixture_root / "registry.json"
        registry.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "components": [
                        {
                            "name": "linked",
                            "source": "components/linked",
                            "destination": ".config/linked",
                            "platforms": ["any"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        profile = self.write_profile({"linked": {"enabled": True}})
        self.initialize()
        with mock.patch.object(control, "REPO_ROOT", fixture_root.resolve()):
            result, _stdout, stderr = self.run_control(
                "--registry",
                str(registry),
                "--profile",
                str(profile),
                "plan",
                "--target",
                str(self.target),
            )
        self.assertEqual(result, 2)
        self.assertIn("may not traverse a symlink", stderr)

    def test_directory_registry_returns_concise_control_error(self) -> None:
        self.initialize()
        result, _stdout, stderr = self.run_control(
            "--registry",
            self.temporary.name,
            "plan",
            "--target",
            str(self.target),
        )
        self.assertEqual(result, 2)
        self.assertIn("control: could not read configuration", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_report_discovers_unmanaged_files_without_failing_verify(self) -> None:
        self.initialize()
        self.assertEqual(self.run_control("apply", "--target", str(self.target), "--execute")[0], 0)
        unmanaged = self.target / ".config" / "sysops_pub" / "shell-banner" / "extra.txt"
        unmanaged.write_text("not declared\n", encoding="utf-8")

        verify_result, _stdout, stderr = self.run_control("verify", "--target", str(self.target))
        self.assertEqual(verify_result, 0, stderr)
        report_result, stdout, stderr = self.run_control(
            "report", "--target", str(self.target), "--json"
        )
        self.assertEqual(report_result, 0, stderr)
        report = json.loads(stdout)
        self.assertEqual(report["summary"], {"match": 2, "unmanaged": 1})
        unmanaged_rows = [row for row in report["files"] if row["status"] == "unmanaged"]
        self.assertEqual(len(unmanaged_rows), 1)
        self.assertEqual(
            unmanaged_rows[0]["path"],
            ".config/sysops_pub/shell-banner/extra.txt",
        )

    def test_dry_run_rejects_wrong_type_destination(self) -> None:
        self.initialize()
        wrong_type = self.target / ".config" / "sysops_pub" / "shell-banner" / "banner.txt"
        wrong_type.mkdir(parents=True)
        result, stdout, stderr = self.run_control("apply", "--target", str(self.target))
        self.assertEqual(result, 2)
        self.assertIn("WRONG-TYPE", stdout)
        self.assertIn("refusing unsafe destination", stderr)

    def test_selected_component_must_support_current_platform(self) -> None:
        registry = Path(self.temporary.name) / "platform-registry.json"
        registry.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "components": [
                        {
                            "name": "agent-policy",
                            "source": "components/agent-policy/desired",
                            "destination": ".config/example",
                            "platforms": ["linux"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        profile = self.write_profile({"agent-policy": {"enabled": True}})
        self.initialize()
        with mock.patch.object(control, "_current_platform", return_value="windows"):
            result, _stdout, stderr = self.run_control(
                "--registry",
                str(registry),
                "--profile",
                str(profile),
                "plan",
                "--target",
                str(self.target),
            )
        self.assertEqual(result, 2)
        self.assertIn("does not support platform windows", stderr)

    def test_registry_rejects_unknown_platform(self) -> None:
        registry = Path(self.temporary.name) / "platform-registry.json"
        registry.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "components": [
                        {
                            "name": "agent-policy",
                            "source": "components/agent-policy/desired",
                            "destination": ".config/example",
                            "platforms": ["plan9"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        profile = self.write_profile({"agent-policy": {"enabled": True}})
        self.initialize()
        result, _stdout, stderr = self.run_control(
            "--registry",
            str(registry),
            "--profile",
            str(profile),
            "plan",
            "--target",
            str(self.target),
        )
        self.assertEqual(result, 2)
        self.assertIn("unsupported platform", stderr)

    def test_overlapping_component_destination_roots_are_rejected(self) -> None:
        fixture_root = Path(self.temporary.name) / "fixture-repository"
        for name in ("outer", "inner"):
            source = fixture_root / "components" / name / "desired"
            source.mkdir(parents=True)
            (source / f"{name}.txt").write_text(f"{name}\n", encoding="utf-8")
        registry = fixture_root / "registry.json"
        registry.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "components": [
                        {
                            "name": "outer",
                            "source": "components/outer/desired",
                            "destination": "root",
                            "platforms": ["any"],
                        },
                        {
                            "name": "inner",
                            "source": "components/inner/desired",
                            "destination": "root/sub",
                            "platforms": ["any"],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        profile = self.write_profile({"outer": {"enabled": True}, "inner": {"enabled": True}})
        self.initialize()
        with mock.patch.object(control, "REPO_ROOT", fixture_root.resolve()):
            result, _stdout, stderr = self.run_control(
                "--registry",
                str(registry),
                "--profile",
                str(profile),
                "plan",
                "--target",
                str(self.target),
            )
        self.assertEqual(result, 2)
        self.assertIn("destination roots overlap", stderr)


if __name__ == "__main__":
    unittest.main()
