from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import search_docs  # noqa: E402


class SearchDocsTests(unittest.TestCase):
    def test_answer_has_corpus_digest_and_source(self) -> None:
        receipt = search_docs.retrieve(
            "desired state verification",
            ROOT / "samples" / "rag" / "corpus",
        )
        self.assertEqual(receipt["outcome"], "answered")
        self.assertEqual(len(receipt["corpus_digest"]), 64)
        self.assertTrue(receipt["sources"])
        self.assertIn("path", receipt["sources"][0])

    def test_no_overlap_is_explicit_not_found(self) -> None:
        receipt = search_docs.retrieve(
            "xylophone quasar",
            ROOT / "samples" / "rag" / "corpus",
        )
        self.assertEqual(receipt["outcome"], "not_found")
        self.assertEqual(receipt["sources"], [])

    def test_digest_changes_with_corpus_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-corpus-") as directory:
            corpus = Path(directory)
            document = corpus / "DOC.md"
            document.write_text("alpha state\n", encoding="utf-8")
            first = search_docs.retrieve("alpha", corpus)["corpus_digest"]
            document.write_text("alpha state changed\n", encoding="utf-8")
            second = search_docs.retrieve("alpha", corpus)["corpus_digest"]
            self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
