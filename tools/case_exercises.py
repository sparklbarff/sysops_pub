#!/usr/bin/env python3
"""Run synthetic exercises derived from the Spectre and Eidolon case studies."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CASE_ROOT = REPO_ROOT / "samples" / "cases"


def _load(name: str) -> dict[str, Any]:
    value = json.loads((CASE_ROOT / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"case fixture must be an object: {name}")
    return value


def spectre_result() -> dict[str, object]:
    case = _load("spectre-cohort.json")
    fail_cells = int(case["fail_cells"])
    budget = int(case["budget_fail_cells"])
    red_members = int(case["red_members"])
    accepted = fail_cells <= budget and red_members == 0
    return {
        "accepted": accepted,
        "artifact_created": bool(case["artifact_created"]),
        "classification": "accepted" if accepted else "failed_diagnostic_artifact",
        "reason": f"{fail_cells} fail cells against budget {budget}; {red_members} red members",
    }


def eidolon_result() -> dict[str, object]:
    case = _load("eidolon-ledger.json")
    runner = str(case["runner_name"])
    rows = case["rows"]
    if not isinstance(rows, list):
        raise TypeError("eidolon rows must be a list")
    substring_mismatches: list[str] = []
    head_word_mismatches: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("each eidolon row must be an object")
        command = str(row["command"])
        expected = bool(row["is_test_run"])
        substring_guess = runner in command
        head_word_guess = command.split(maxsplit=1)[0].removeprefix("./") == runner
        if substring_guess != expected:
            substring_mismatches.append(command)
        if head_word_guess != expected:
            head_word_mismatches.append(command)
    return {
        "head_word_mismatches": head_word_mismatches,
        "lesson": "neither substring matching nor head-word filtering is a safe parser",
        "substring_mismatches": substring_mismatches,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=("all", "eidolon", "spectre"), default="all", nargs="?")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        results: dict[str, object] = {}
        if args.case in {"all", "spectre"}:
            spectre = spectre_result()
            results["spectre"] = spectre
            if spectre["accepted"]:
                return 1
        if args.case in {"all", "eidolon"}:
            eidolon = eidolon_result()
            results["eidolon"] = eidolon
            if not eidolon["substring_mismatches"] or not eidolon["head_word_mismatches"]:
                return 1
        print(json.dumps(results, indent=2, sort_keys=True))
        return 0
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(f"case exercise: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
