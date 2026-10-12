#!/usr/bin/env python3
"""Block an edit of a file this session has not read, or that changed on disk since it was read.

Three modes, each a hook adapter and a direct command:

- record: after a Read, Write, Edit, or NotebookEdit succeeds, remember the file's content hash for
  this session (PostToolUse).
- check: before an Edit or NotebookEdit, require a record for the file and require the file to hash
  as it did when recorded; a mismatch leaves a pending stale block on the path (PreToolUse).
- shell: before a Bash command, block a command that names a path with a pending stale block, so the
  blocked edit cannot be routed through the shell; a fresh read clears it (PreToolUse).

Write is exempt: it supplies the whole content and needs no prior read. A windowed read counts as a
read; what the window covered is the agent's responsibility. State is one JSON file per session in
a directory outside the project, never in the project itself. It prevents an agent editing what it
has not seen; it is not a defense against a hostile one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

STATE_ENVIRONMENT = "SYSOPS_PUB_GUARD_STATE"
RECORDED_TOOLS = {"Read", "Write", "Edit", "NotebookEdit"}
CHECKED_TOOLS = {"Edit", "NotebookEdit"}


class GuardError(ValueError):
    """The input could not be judged, so it is not admitted."""


def _state_directory(explicit: str | None) -> Path:
    raw = explicit or os.environ.get(STATE_ENVIRONMENT)
    if raw:
        return Path(raw).expanduser()
    return Path(tempfile.gettempdir()) / "sysops-pub-read-guard"


def _state_path(directory: Path, session: str) -> Path:
    if not session or "/" in session or "\\" in session or session in {".", ".."}:
        raise GuardError("session identifier is missing or unsafe")
    return directory / f"{session}.json"


def _load_state(path: Path) -> dict[str, object]:
    if path.is_symlink():
        raise GuardError(f"state file is a symlink: {path}")
    if not path.is_file():
        return {"reads": {}, "stale": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardError(f"state file is unreadable: {exc}") from exc
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("reads"), dict)
        or not isinstance(value.get("stale"), list)
    ):
        raise GuardError(f"state file is malformed: {path}")
    return value


def _save_state(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolved(raw: str) -> str:
    try:
        return str(Path(raw).expanduser().resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        raise GuardError(f"path resolution failed: {exc}") from exc


def record(state_path: Path, file_path: str) -> str:
    """Remember the file as read; clear any stale block on it."""
    state = _load_state(state_path)
    key = _resolved(file_path)
    digest = _digest(Path(key))
    reads = state["reads"]
    stale = state["stale"]
    assert isinstance(reads, dict) and isinstance(stale, list)
    if digest is None:
        reads.pop(key, None)
        _save_state(state_path, state)
        return f"no file to record at {key}"
    reads[key] = digest
    state["stale"] = [entry for entry in stale if entry != key]
    _save_state(state_path, state)
    return f"recorded {key}"


def check(state_path: Path, file_path: str) -> tuple[bool, str]:
    """Allow the edit only if the file was read this session and is unchanged since."""
    state = _load_state(state_path)
    key = _resolved(file_path)
    reads = state["reads"]
    stale = state["stale"]
    assert isinstance(reads, dict) and isinstance(stale, list)
    recorded = reads.get(key)
    if recorded is None:
        return False, f"{key} has not been read this session; read it first"
    current = _digest(Path(key))
    if current is None:
        return False, f"{key} no longer exists"
    if current != recorded:
        if key not in stale:
            stale.append(key)
            _save_state(state_path, state)
        return False, f"{key} changed on disk since it was read; read it again"
    return True, f"{key} was read this session and is unchanged"


def shell(state_path: Path, command: str, cwd: str | None) -> tuple[bool, str]:
    """Block a command that names a path with a pending stale block."""
    state = _load_state(state_path)
    stale = state["stale"]
    assert isinstance(stale, list)
    for key in stale:
        names = {key}
        if cwd:
            try:
                names.add(str(Path(key).relative_to(Path(cwd).resolve())))
            except ValueError:
                pass
        if any(name in command for name in names):
            return False, f"{key} has a pending stale-read block; read it again before touching it"
    return True, "no pending stale-read block is named"


def _payload() -> dict[str, object]:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise GuardError(f"invalid hook JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise GuardError("hook payload must be an object")
    return payload


def _payload_path(payload: dict[str, object]) -> str:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        raise GuardError("hook payload has no tool_input object")
    for key in ("file_path", "notebook_path", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    raise GuardError("hook payload has no supported file path")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("mode", choices=("record", "check", "shell"), help="Which guard to run")
    parser.add_argument("--state-dir", help="Where session state lives (default: the temp dir)")
    parser.add_argument("--session", help="Session identifier in direct mode")
    parser.add_argument("--path", help="File path in direct record or check mode")
    parser.add_argument("--command", help="Shell command in direct shell mode")
    parser.add_argument("--cwd", help="Working directory for relative names in shell mode")
    parser.add_argument(
        "--claude-hook", action="store_true", help="Read a Claude Code hook payload from stdin"
    )
    parser.add_argument(
        "--codex-hook", action="store_true", help="Read a Codex hook payload from stdin"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.claude_hook or args.codex_hook:
            payload = _payload()
            session = str(payload.get("session_id") or "")
            tool_name = str(payload.get("tool_name") or "")
            cwd = payload.get("cwd")
            cwd = cwd if isinstance(cwd, str) else None
            if args.mode == "record" and tool_name not in RECORDED_TOOLS:
                print(f"read_guard: {tool_name} is not a recorded tool")
                return 0
            if args.mode == "check" and tool_name not in CHECKED_TOOLS:
                print(f"ALLOWED: {tool_name} is not a checked tool")
                return 0
            if args.mode == "shell":
                tool_input = payload.get("tool_input")
                subject = tool_input.get("command") if isinstance(tool_input, dict) else None
            else:
                subject = _payload_path(payload)
            if not isinstance(subject, str) or not subject:
                raise GuardError(f"hook payload has no subject for {args.mode}")
        else:
            session = args.session or ""
            cwd = args.cwd
            subject = args.command if args.mode == "shell" else args.path
            if not subject:
                raise GuardError(f"--{'command' if args.mode == 'shell' else 'path'} is required")
        state_path = _state_path(_state_directory(args.state_dir), session)
        if args.mode == "record":
            print(f"read_guard: {record(state_path, subject)}")
            return 0
        if args.mode == "check":
            allowed, reason = check(state_path, subject)
        else:
            allowed, reason = shell(state_path, subject, cwd)
    except GuardError as exc:
        if args.mode == "record":
            print(f"read_guard: could not record: {exc}", file=sys.stderr)
            return 0
        print(f"read_guard: BLOCKED: {exc}", file=sys.stderr)
        return 2
    if allowed:
        print(f"ALLOWED: {reason}")
        return 0
    print(f"BLOCKED: {reason}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
