#!/usr/bin/env python3
"""Advisory prompt classifier: when does a prompt benefit from one bounded grounding pass?

This is an ADVISORY UserPromptSubmit control, not a block. It recognizes broad, orientation-style
prompts that benefit from grounding against the project's own documents, and stays silent on narrow
file-level work. It fails open: on any error the session simply continues ungrounded, because an
advisory that can halt a prompt is worse than one that occasionally misses.

It classifies the PROMPT TEXT, not the work, so a narrow task phrased in broad language is an
accepted false positive. That is exactly why it is advisory and fail-open: a spurious fire costs one
bounded grounding query that a null result does not block, never a halted session. The cross-cutting
pattern triggers on a repo-scale scope noun rather than a bare preposition, so "compare the output
across two runs" (narrow) does not fire while "compare coverage across the codebase" (broad) does.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence

BROAD_PATTERNS = (
    (
        "state or history",
        re.compile(
            r"\bcurrent\b.{0,80}\b(?:state|status)\b"
            r"|\b(?:what remains|next steps|where (?:do we|are we) stand"
            r"|catch me up|project history)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "orientation",
        re.compile(
            r"\b(?:architecture|codebase|project|repository) "
            r"(?:overview|orientation|map|review|audit)\b"
            r"|\borient me\b|\bfrom the ground up\b",
            re.IGNORECASE,
        ),
    ),
    (
        "cross-cutting",
        re.compile(
            r"\b(?:reconcile|compare|trace|investigate)\b.*"
            r"\b(?:codebase|repo(?:sitory|sitories)?|projects?|system|architecture|everything)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "freshness",
        re.compile(
            r"\b(?:already (?:shipped|merged|implemented)|in[- ]flight"
            r"|has (?:this|it) (?:shipped|merged))\b",
            re.IGNORECASE,
        ),
    ),
)

GROUNDING_INSTRUCTION = (
    "This prompt reads as broad repository work. Run one bounded local grounding query over the "
    "project documents before broad reading or a web search; a null result does not block. Treat "
    "the result as orientation and verify exact claims against current source."
)


def classify(prompt: str) -> tuple[bool, str]:
    normalized = " ".join(prompt.split())
    if not normalized:
        return False, "empty prompt"
    for label, pattern in BROAD_PATTERNS:
        if pattern.search(normalized):
            return True, label
    return False, "narrow or operational prompt"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="?", help="prompt text to classify in cli mode")
    parser.add_argument("--hook", choices=("cli", "claude"), default="cli")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.hook == "claude":
            payload = json.load(sys.stdin)
            prompt = str(payload.get("prompt", "")) if isinstance(payload, dict) else ""
            required, _reason = classify(prompt)
            if required:
                print(
                    json.dumps(
                        {
                            "hookSpecificOutput": {
                                "hookEventName": "UserPromptSubmit",
                                "additionalContext": GROUNDING_INSTRUCTION,
                            }
                        },
                        separators=(",", ":"),
                    )
                )
            return 0
        if not args.prompt:
            print(
                "grounding_classifier: a prompt argument is required in cli mode", file=sys.stderr
            )
            return 2
        required, reason = classify(args.prompt)
        print(json.dumps({"reason": reason, "required": required}, sort_keys=True))
        return 0
    except Exception:  # noqa: BLE001
        # Advisory and fail-open: the broad catch is deliberate and load-bearing. Any error at all,
        # malformed input included, must exit cleanly so this control never prevents a session from
        # continuing. Narrowing the except could let an unforeseen error halt a prompt.
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
