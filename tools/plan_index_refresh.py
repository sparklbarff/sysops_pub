#!/usr/bin/env python3
"""Plan every synthetic index refresh owned by one repository.

The tool demonstrates the post-commit fan-out contract without running a model, modifying Git
hooks, or writing queue state. Repository identities are symbolic so the fixture stays portable.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / "samples" / "rag" / "indexes.json"
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class RefreshPlanError(RuntimeError):
    """Invalid or unresolved refresh-plan request."""


def _load_registry(path: Path) -> list[dict[str, str]]:
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RefreshPlanError(f"could not read registry {path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise RefreshPlanError("registry schema_version must be 1")
    entries = raw.get("indexes")
    if not isinstance(entries, list):
        raise RefreshPlanError("registry indexes must be a list")

    indexes: list[dict[str, str]] = []
    names: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"name", "repository", "source"}:
            raise RefreshPlanError("each index needs only name, repository, and source")
        if not all(isinstance(entry[key], str) for key in entry):
            raise RefreshPlanError("index fields must be strings")
        name = entry["name"]
        repository = entry["repository"]
        source = entry["source"]
        if not SAFE_ID.fullmatch(name) or not SAFE_ID.fullmatch(repository):
            raise RefreshPlanError("index and repository names must be portable identifiers")
        source_path = Path(source)
        if source_path.is_absolute() or ".." in source_path.parts or not source_path.parts:
            raise RefreshPlanError(f"source must be a non-traversing relative path: {source!r}")
        if name in names:
            raise RefreshPlanError(f"duplicate index name: {name}")
        names.add(name)
        indexes.append({"name": name, "repository": repository, "source": source})
    return indexes


def plan_refresh(registry: Path, repository: str) -> dict[str, object]:
    if not SAFE_ID.fullmatch(repository):
        raise RefreshPlanError("repository must be a portable identifier")
    owned = sorted(
        (entry for entry in _load_registry(registry) if entry["repository"] == repository),
        key=lambda entry: entry["name"],
    )
    if not owned:
        raise RefreshPlanError(f"repository is not registered: {repository}")
    return {
        "schema_version": 1,
        "repository": repository,
        "refresh_count": len(owned),
        "indexes": owned,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", help="Symbolic repository identity to plan for")
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY,
        help="Index registry to read (default: samples/rag/indexes.json)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        plan = plan_refresh(args.registry.resolve(), args.repository)
    except RefreshPlanError as exc:
        print(f"plan_index_refresh: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
