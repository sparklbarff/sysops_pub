#!/usr/bin/env python3
"""Score a frozen retrieval benchmark by cohort, judged against the retrieved context.

This demonstrates the retrieval-evaluation discipline the private system uses, over the synthetic
corpus: a frozen question set split into three cohorts, verdicts judged against the retrieved
CONTEXT text rather than the filename or the score, and results bound to the retriever identity so a
run is never compared across a changed retriever or corpus state.

It reuses tools/search_docs.py as the single retrieval path. It is not a second retriever, and it
bundles no model. The point it teaches: a retrieval "hit" is only a hit if the answer is in the text
the model was shown, recall on answers that genuinely live in the corpus is the metric that matters,
a question whose answer is outside the indexed surface is a coverage gap rather than a recall
failure, and a control query whose answer is nowhere must come back empty.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import search_docs

DEFAULT_QUESTIONS = REPO_ROOT / "samples" / "rag" / "eval-questions.json"
DEFAULT_CORPUS = REPO_ROOT / "samples" / "rag" / "corpus"
COHORTS = ("curated-in-corpus", "coverage-gap", "absent-control")


def _context_text(receipt: dict[str, object], corpus: Path) -> str:
    """The text the retrieval actually surfaced, lowercased.

    Resolve each cited source back to its bytes so a verdict is judged against the context the model
    would see, not the filename. Judging by filename manufactures hits: the right document can be
    retrieved while the window shown never contains the answer.
    """
    parts: list[str] = []
    for source in receipt["sources"]:  # type: ignore[union-attr]
        rel = str(source["path"])
        path = REPO_ROOT / rel
        if not path.is_file():
            path = corpus / Path(rel).name
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts).lower()


def judge(question: dict[str, object], receipt: dict[str, object], corpus: Path) -> str:
    cohort = str(question["cohort"])
    if cohort == "absent-control":
        return (
            "false-positive"
            if receipt["retrieval_outcome"] == "context_found"
            else "correct-rejection"
        )
    if cohort == "coverage-gap":
        # Expected miss: the answer exists only outside the indexed surface, so retrieval cannot
        # and should not surface it. Tracked, never counted against recall.
        return "coverage-gap"
    token = question.get("answer_token")
    if isinstance(token, str) and token and token.lower() in _context_text(receipt, corpus):
        return "hit"
    return "miss"


def evaluate(questions_path: Path, corpus: Path) -> dict[str, object]:
    spec = json.loads(questions_path.read_text(encoding="utf-8"))
    bound_retriever = str(spec.get("retriever_id", ""))
    results = []
    corpus_digest = ""
    for question in spec["questions"]:
        receipt = search_docs.retrieve(str(question["prompt"]), corpus)
        corpus_digest = str(receipt["corpus_digest"])
        results.append(
            {
                "id": question["id"],
                "cohort": question["cohort"],
                "verdict": judge(question, receipt, corpus),
            }
        )
    curated = [r for r in results if r["cohort"] == "curated-in-corpus"]
    absent = [r for r in results if r["cohort"] == "absent-control"]
    return {
        "bound_retriever_id": bound_retriever,
        "live_retriever_id": search_docs.RETRIEVER_ID,
        "retriever_drift": bound_retriever != search_docs.RETRIEVER_ID,
        "corpus_digest": corpus_digest,
        "curated_recall": {
            "hit": sum(r["verdict"] == "hit" for r in curated),
            "total": len(curated),
        },
        "absent_false_positives": sum(r["verdict"] == "false-positive" for r in absent),
        "coverage_gap_tracked": sum(r["cohort"] == "coverage-gap" for r in results),
        "results": results,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.questions.is_file():
        print(f"eval_retrieval: question set not found: {args.questions}", file=sys.stderr)
        return 2
    if not args.corpus.is_dir():
        print(f"eval_retrieval: corpus not found: {args.corpus}", file=sys.stderr)
        return 2
    report = evaluate(args.questions.resolve(), args.corpus.resolve())
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["retriever_drift"]:
        # The frozen verdicts were judged against a different retriever identity, so they no longer
        # describe this pipeline. Re-judge before trusting any score.
        print(
            "eval_retrieval: retriever identity changed since the set was frozen; re-judge before "
            "comparing scores",
            file=sys.stderr,
        )
        return 2
    return 1 if report["absent_false_positives"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
