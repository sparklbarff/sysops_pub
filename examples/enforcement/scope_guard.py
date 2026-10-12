#!/usr/bin/env python3
"""Minimal write-scope guard with CLI, Claude Code hook, and Codex hook adapters.

Claude Code sends the write path in the tool input. Codex reports file edits as the apply_patch
tool and sends the patch text, so the Codex adapter reads every file the patch names from its
header lines and requires all of them to stay under the project root, which Codex supplies as the
session's working directory.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

PATCH_FILE_LINE = re.compile(
    r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+?)\s*$", re.MULTILINE
)


def decision(root: Path, candidate: Path) -> tuple[bool, str]:
    try:
        resolved_root = root.expanduser().resolve()
        resolved_candidate = candidate.expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        return False, f"path resolution failed: {exc}"
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


def _codex_paths(payload: dict[str, object], cwd: Path) -> list[Path]:
    """Every file an apply_patch payload names, resolved against the session's working directory."""
    if payload.get("tool_name") != "apply_patch":
        path = _claude_path(payload)
        return [path] if path is not None else []
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return []
    patch = tool_input.get("command")
    if not isinstance(patch, str):
        return []
    return [cwd / match.group(1) for match in PATCH_FILE_LINE.finditer(patch)]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--root", type=Path, help="Project root; required outside hook mode")
    parser.add_argument("--path", type=Path, help="Write path to judge in direct mode")
    parser.add_argument(
        "--claude-hook", action="store_true", help="Read a Claude Code PreToolUse payload"
    )
    parser.add_argument(
        "--codex-hook",
        action="store_true",
        help="Read a Codex PreToolUse payload; apply_patch paths come from the patch header",
    )
    parser.add_argument("--json", action="store_true", help="Print the decision as JSON")
    return parser


def _hook_payload() -> dict[str, object] | None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"scope_guard: invalid hook JSON: {exc}", file=sys.stderr)
        return None
    if not isinstance(payload, dict):
        print("scope_guard: hook payload must be an object", file=sys.stderr)
        return None
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    candidates: list[Path]
    if args.claude_hook or args.codex_hook:
        payload = _hook_payload()
        if payload is None:
            return 2
        if args.codex_hook:
            cwd = payload.get("cwd")
            if args.root is not None:
                root = args.root
            elif isinstance(cwd, str) and cwd:
                root = Path(cwd)
            else:
                print("scope_guard: cwd is required in Codex hook mode", file=sys.stderr)
                return 2
            candidates = _codex_paths(payload, root)
        else:
            if args.root is not None:
                root = args.root
            else:
                project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
                if not project_dir:
                    print(
                        "scope_guard: CLAUDE_PROJECT_DIR is required in hook mode", file=sys.stderr
                    )
                    return 2
                root = Path(project_dir)
            candidate = _claude_path(payload)
            candidates = [candidate] if candidate is not None else []
        if not candidates:
            print("scope_guard: hook payload has no supported write path", file=sys.stderr)
            return 2
    else:
        if args.root is None or args.path is None:
            print("scope_guard: --root and --path are required outside hook mode", file=sys.stderr)
            return 2
        root = args.root
        candidates = [args.path]

    allowed, reason = True, "no write path"
    for candidate in candidates:
        allowed, reason = decision(root, candidate)
        if not allowed:
            break
    if args.json:
        print(json.dumps({"decision": "allow" if allowed else "block", "reason": reason}))
    elif not allowed:
        print(f"BLOCKED: {reason}", file=sys.stderr)
    else:
        print(f"ALLOWED: {reason}")
    return 0 if allowed else 2


if __name__ == "__main__":
    raise SystemExit(main())
