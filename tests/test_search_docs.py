from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import search_docs  # noqa: E402


class SearchDocsTests(unittest.TestCase):
    def test_context_receipt_has_corpus_digest_and_source(self) -> None:
        receipt = search_docs.retrieve(
            "desired state verification",
            ROOT / "samples" / "rag" / "corpus",
        )
        self.assertEqual(receipt["retrieval_outcome"], "context_found")
        self.assertEqual(receipt["receipt_schema_version"], 2)
        self.assertEqual(receipt["retriever_id"], "token-overlap-set-v1")
        self.assertEqual(len(receipt["corpus_digest"]), 64)
        self.assertTrue(receipt["sources"])
        self.assertIn("path", receipt["sources"][0])
        self.assertEqual(receipt["context_document_count"], len(receipt["sources"]))
        self.assertGreater(receipt["context_characters"], 0)
        self.assertFalse(receipt["generation_attempted"])
        self.assertFalse(receipt["not_found_emitted"])

    def test_no_overlap_is_explicit_not_found(self) -> None:
        receipt = search_docs.retrieve(
            "xylophone quasar",
            ROOT / "samples" / "rag" / "corpus",
        )
        self.assertEqual(receipt["retrieval_outcome"], "no_context")
        self.assertEqual(receipt["sources"], [])
        self.assertEqual(receipt["context_document_count"], 0)
        self.assertEqual(receipt["context_characters"], 0)

    def test_digest_changes_with_corpus_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-corpus-") as directory:
            corpus = Path(directory)
            document = corpus / "DOC.md"
            document.write_text("alpha state\n", encoding="utf-8")
            first = search_docs.retrieve("alpha", corpus)["corpus_digest"]
            document.write_text("alpha state changed\n", encoding="utf-8")
            second = search_docs.retrieve("alpha", corpus)["corpus_digest"]
            self.assertNotEqual(first, second)

    def test_evaluation_report_is_excluded_from_its_own_corpus(self) -> None:
        corpus = ROOT / "samples" / "rag" / "corpus"
        receipt = search_docs.retrieve("impossible self-evaluation sentinel", corpus)
        self.assertEqual(receipt["retrieval_outcome"], "no_context")
        self.assertIn("synthetic-evaluation.md", receipt["excluded_files"])
        self.assertEqual(len(receipt["corpus_policy_digest"]), 64)

    def test_invalid_corpus_policy_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-corpus-") as directory:
            corpus = Path(directory)
            (corpus / "DOC.md").write_text("alpha", encoding="utf-8")
            (corpus / search_docs.POLICY_NAME).write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                search_docs.retrieve("alpha", corpus)

    def test_symlink_document_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-corpus-") as directory:
            corpus = Path(directory) / "corpus"
            corpus.mkdir()
            outside = Path(directory) / "outside.md"
            outside.write_text("private alpha", encoding="utf-8")
            (corpus / "linked.md").symlink_to(outside)
            with self.assertRaises(ValueError):
                search_docs.retrieve("alpha", corpus)

    def test_cli_requires_and_records_requirement_identity(self) -> None:
        script = ROOT / "tools" / "search_docs.py"
        missing = subprocess.run(
            [sys.executable, str(script), "desired state"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(missing.returncode, 2)
        self.assertIn("--requirement-id", missing.stderr)

        recorded = subprocess.run(
            [
                sys.executable,
                str(script),
                "desired state",
                "--requirement-id",
                "test-requirement-001",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        self.assertEqual(json.loads(recorded.stdout)["requirement_id"], "test-requirement-001")

        blank = subprocess.run(
            [
                sys.executable,
                str(script),
                "desired state",
                "--requirement-id",
                "   ",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(blank.returncode, 2)
        self.assertIn("must not be blank", blank.stderr)


if __name__ == "__main__":
    unittest.main()
