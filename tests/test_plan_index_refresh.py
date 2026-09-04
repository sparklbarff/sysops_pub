from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import plan_index_refresh  # noqa: E402


class PlanIndexRefreshTests(unittest.TestCase):
    def test_one_repository_fans_out_to_every_owned_index(self) -> None:
        plan = plan_index_refresh.plan_refresh(
            ROOT / "samples" / "rag" / "indexes.json", "sample-project"
        )

        self.assertEqual(plan["refresh_count"], 2)
        self.assertEqual(
            [entry["name"] for entry in plan["indexes"]],
            ["sample-project-briefs", "sample-project-docs"],
        )

    def test_unrelated_repository_index_is_not_scheduled(self) -> None:
        plan = plan_index_refresh.plan_refresh(
            ROOT / "samples" / "rag" / "indexes.json", "other-project"
        )

        self.assertEqual(plan["refresh_count"], 1)
        self.assertEqual(plan["indexes"][0]["name"], "other-project-docs")

    def test_unknown_repository_is_explicit_error(self) -> None:
        with self.assertRaisesRegex(
            plan_index_refresh.RefreshPlanError, "repository is not registered"
        ):
            plan_index_refresh.plan_refresh(
                ROOT / "samples" / "rag" / "indexes.json", "missing-project"
            )

    def test_duplicate_index_name_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-refresh-") as directory:
            registry = Path(directory) / "indexes.json"
            registry.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "indexes": [
                            {"name": "docs", "repository": "one", "source": "corpus"},
                            {"name": "docs", "repository": "two", "source": "corpus"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                plan_index_refresh.RefreshPlanError, "duplicate index name"
            ):
                plan_index_refresh.plan_refresh(registry, "one")


if __name__ == "__main__":
    unittest.main()
