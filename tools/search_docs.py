#!/usr/bin/env python3
"""Deterministic retrieval-contract demo over a small synthetic Markdown corpus.

This is not an embedding model. It demonstrates explicit outcomes, corpus-state identity,
requirement identity, and cited source paths that a production local RAG wrapper should preserve.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = REPO_ROOT / "samples" / "rag" / "corpus"
TOKEN_RE = re.compile(r"[a-z0-9_]+")


def _tokens(text: str) -> set[str]:
    return set(TOKEN_RE.findall(text.lower()))


def _corpus_digest(files: Sequence[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def retrieve(query: str, corpus: Path, limit: int = 3) -> dict[str, object]:
    files = sorted(path for path in corpus.glob("*.md") if path.is_file())
    query_tokens = _tokens(query)
    ranked: list[tuple[int, str, Path]] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        score = len(query_tokens & _tokens(text))
        if score:
            ranked.append((score, path.name, path))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    sources = []
    for score, _name, path in ranked[:limit]:
        try:
            cited_path = path.relative_to(REPO_ROOT)
        except ValueError:
            cited_path = path.relative_to(corpus)
        sources.append({"path": str(cited_path), "score": score})
    return {
        "query": query,
        "outcome": "answered" if sources else "not_found",
        "corpus_digest": _corpus_digest(files),
        "sources": sources,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument(
        "--requirement-id",
        required=True,
        help="Stable identifier for the requirement that caused this retrieval",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.limit < 1:
        print("search_docs: --limit must be positive", file=sys.stderr)
        return 2
    if not args.corpus.is_dir():
        print(f"search_docs: corpus not found: {args.corpus}", file=sys.stderr)
        return 2
    receipt = retrieve(args.query, args.corpus.resolve(), args.limit)
    receipt["requirement_id"] = args.requirement_id
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["outcome"] == "answered" else 1


if __name__ == "__main__":
    raise SystemExit(main())
