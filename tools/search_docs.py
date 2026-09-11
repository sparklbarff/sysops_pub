#!/usr/bin/env python3
"""Deterministic retrieval-contract demo over a small synthetic Markdown corpus.

This is not an embedding model. It demonstrates explicit outcomes, corpus-state identity,
requirement identity, and cited source paths that a production local RAG wrapper should preserve.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = REPO_ROOT / "samples" / "rag" / "corpus"
TOKEN_RE = re.compile(r"[a-z0-9_]+")
RECEIPT_SCHEMA_VERSION = 2
RETRIEVER_ID = "token-overlap-set-v1"
POLICY_NAME = "corpus-policy.json"


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


def _corpus_files(corpus: Path) -> tuple[list[Path], list[str], str]:
    policy_path = corpus / POLICY_NAME
    patterns: list[str] = []
    if policy_path.exists():
        if policy_path.is_symlink() or not policy_path.is_file():
            raise ValueError("corpus policy must be a regular file inside the corpus")
        try:
            value = json.loads(policy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid corpus policy: {exc}") from exc
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != 1
            or set(value) != {"exclude_globs", "schema_version"}
            or not isinstance(value["exclude_globs"], list)
            or not all(isinstance(item, str) and item for item in value["exclude_globs"])
        ):
            raise ValueError("corpus policy must contain schema_version 1 and exclude_globs")
        patterns = value["exclude_globs"]
        policy_digest = hashlib.sha256(policy_path.read_bytes()).hexdigest()
    else:
        policy_digest = hashlib.sha256(b"no-corpus-policy").hexdigest()

    selected: list[Path] = []
    excluded: list[str] = []
    for path in sorted(corpus.glob("*.md")):
        if path.is_symlink():
            raise ValueError(f"corpus document must not be a symlink: {path.name}")
        if not path.is_file():
            continue
        if any(fnmatch.fnmatch(path.name, pattern) for pattern in patterns):
            excluded.append(path.name)
        else:
            selected.append(path)
    return selected, excluded, policy_digest


def retrieve(query: str, corpus: Path, limit: int = 3) -> dict[str, object]:
    files, excluded, policy_digest = _corpus_files(corpus)
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
        sources.append(
            {
                "characters": len(path.read_text(encoding="utf-8")),
                "path": str(cited_path),
                "score": score,
            }
        )
    return {
        "context_characters": sum(int(source["characters"]) for source in sources),
        "context_document_count": len(sources),
        "corpus_digest": _corpus_digest(files),
        "corpus_policy_digest": policy_digest,
        "excluded_files": excluded,
        "generation_attempted": False,
        "not_found_emitted": False,
        "receipt_schema_version": RECEIPT_SCHEMA_VERSION,
        "retriever_id": RETRIEVER_ID,
        "retrieval_outcome": "context_found" if sources else "no_context",
        "query": query,
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
    requirement_id = args.requirement_id.strip()
    if not requirement_id:
        print("search_docs: --requirement-id must not be blank", file=sys.stderr)
        return 2
    if not args.corpus.is_dir():
        print(f"search_docs: corpus not found: {args.corpus}", file=sys.stderr)
        return 2
    try:
        receipt = retrieve(args.query, args.corpus.resolve(), args.limit)
    except ValueError as exc:
        print(f"search_docs: {exc}", file=sys.stderr)
        return 2
    receipt["requirement_id"] = requirement_id
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["retrieval_outcome"] == "context_found" else 1


if __name__ == "__main__":
    raise SystemExit(main())
