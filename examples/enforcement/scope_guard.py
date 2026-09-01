#!/usr/bin/env python3
"""Minimal write-scope guard with CLI and Claude Code hook adapters."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path


def decision(root: Path, candidate: Path) -> tuple[bool, str]:
    resolved_root = root.expanduser().resolve()
    resolved_candidate = candidate.expanduser().resolve()
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError:
        return False, f"write path is outside the project root: {resolved_candidate}"
    return True, f"write path is inside the project root: {resolved_candidate}"


def _claude_path(payload: dict[str, object]) -> Path | None:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "notebook_path", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return Path(value)
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--path", type=Path)
    parser.add_argument("--claude-hook", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.claude_hook:
        try:
            payload = json.load(sys.stdin)
        except json.JSONDecodeError as exc:
            print(f"scope_guard: invalid hook JSON: {exc}", file=sys.stderr)
            return 2
        if not isinstance(payload, dict):
            print("scope_guard: hook payload must be an object", file=sys.stderr)
            return 2
        candidate = _claude_path(payload)
        if candidate is None:
            return 0
        root = args.root or Path(os.environ.get("CLAUDE_PROJECT_DIR", Path.cwd()))
    else:
        if args.root is None or args.path is None:
            print("scope_guard: --root and --path are required outside hook mode", file=sys.stderr)
            return 2
        root = args.root
        candidate = args.path

    allowed, reason = decision(root, candidate)
    if args.json:
        print(json.dumps({"decision": "allow" if allowed else "block", "reason": reason}))
    elif not allowed:
        print(f"BLOCKED: {reason}", file=sys.stderr)
    else:
        print(f"ALLOWED: {reason}")
    return 0 if allowed else 2


if __name__ == "__main__":
    raise SystemExit(main())
