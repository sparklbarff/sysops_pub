#!/usr/bin/env python3
"""Publish a sanitized project label and agent state as an iTerm2 user variable."""

from __future__ import annotations

import argparse
import base64
import re
from collections.abc import Sequence

STATES = {
    "idle": "Idle",
    "working": "Working",
    "waiting": "Waiting",
    "ended": "Ended",
}
VARIABLE_NAME = "agent_status"


def sanitize_label(raw: str) -> str:
    pieces = re.split(r"[\\/]", raw.strip())
    candidate = pieces[-1] if pieces else ""
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "_", candidate).strip("._-")
    return (candidate or "project")[:40]


def status_text(project: str, state: str) -> str:
    if state not in STATES:
        raise ValueError(f"unknown state: {state}")
    return f"{sanitize_label(project)} | {STATES[state]}"


def escape_sequence(project: str, state: str) -> str:
    encoded = base64.b64encode(status_text(project, state).encode("utf-8")).decode("ascii")
    return f"\033]1337;SetUserVar={VARIABLE_NAME}={encoded}\a"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--state", choices=sorted(STATES), required=True)
    parser.add_argument("--preview", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.preview:
        print(status_text(args.project, args.state))
    else:
        print(escape_sequence(args.project, args.state), end="", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
