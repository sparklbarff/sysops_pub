from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import eval_retrieval
import search_docs


class EvalRetrievalTests(unittest.TestCase):
    def test_frozen_set_scores_clean_by_cohort(self) -> None:
        report = eval_retrieval.evaluate(
            ROOT / "samples" / "rag" / "eval-questions.json",
            ROOT / "samples" / "rag" / "corpus",
        )
        # Every curated answer is reachable in the synthetic corpus, judged against the context.
        self.assertEqual(report["curated_recall"]["hit"], report["curated_recall"]["total"])
        self.assertGreater(report["curated_recall"]["total"], 0)
        # A control query whose answer is nowhere must not retrieve anything.
        self.assertEqual(report["absent_false_positives"], 0)
        # The coverage-gap cohort is tracked, never scored against recall.
        self.assertGreaterEqual(report["coverage_gap_tracked"], 1)
        # The shipped set is bound to the current retriever identity.
        self.assertFalse(report["retriever_drift"])
        self.assertEqual(report["live_retriever_id"], search_docs.RETRIEVER_ID)

    def test_retriever_identity_drift_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-eval-") as directory:
            spec = {
                "schema_version": 1,
                "retriever_id": "some-older-retriever-v0",
                "questions": [
                    {
                        "id": "q",
                        "prompt": "desired state",
                        "cohort": "curated-in-corpus",
                        "answer_token": "independently",
                    }
                ],
            }
            path = Path(directory) / "q.json"
            path.write_text(json.dumps(spec), encoding="utf-8")
            report = eval_retrieval.evaluate(path, ROOT / "samples" / "rag" / "corpus")
            self.assertTrue(report["retriever_drift"])

    def test_verdict_is_judged_against_context_not_filename(self) -> None:
        # A curated question whose answer_token is absent from the retrieved context is a miss even
        # when a topically named document is retrieved. Judging by filename would call it a hit.
        with tempfile.TemporaryDirectory(prefix="rag-eval-") as directory:
            spec = {
                "schema_version": 1,
                "retriever_id": search_docs.RETRIEVER_ID,
                "questions": [
                    {
                        "id": "q",
                        "prompt": "desired state verification",
                        "cohort": "curated-in-corpus",
                        "answer_token": "token-that-is-not-in-any-document",
                    }
                ],
            }
            path = Path(directory) / "q.json"
            path.write_text(json.dumps(spec), encoding="utf-8")
            report = eval_retrieval.evaluate(path, ROOT / "samples" / "rag" / "corpus")
            self.assertEqual(report["curated_recall"], {"hit": 0, "total": 1})


if __name__ == "__main__":
    unittest.main()
