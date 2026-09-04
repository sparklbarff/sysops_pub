#!/usr/bin/env python3
"""Preview or build a reviewable Claude Code and Codex starter bundle."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class AdoptionError(RuntimeError):
    """Unsafe or incomplete adoption request."""


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _safe_target(raw: str) -> Path:
    target = Path(raw).expanduser().resolve()
    if target == Path(target.anchor) or target in {Path.home().resolve(), Path.cwd().resolve()}:
        raise AdoptionError(f"refusing unsafe bundle target: {target}")
    if _is_within(target, REPO_ROOT):
        raise AdoptionError("bundle target must be outside this repository")
    if _is_within(REPO_ROOT, target):
        raise AdoptionError("bundle target may not contain this repository")
    return target


def _sources(tool: str, platform: str) -> list[tuple[Path, Path]]:
    selected: list[tuple[Path, Path]] = []
    if tool in {"claude-code", "both"}:
        settings_name = (
            "settings.windows.json.example"
            if platform == "windows"
            else "settings.posix.json.example"
        )
        selected.extend(
            [
                (
                    REPO_ROOT / "examples" / "claude-code" / "CLAUDE.md.example",
                    Path("claude-code/CLAUDE.md"),
                ),
                (
                    REPO_ROOT / "examples" / "enforcement" / "scope_guard.py",
                    Path("claude-code/.agent-tools/scope_guard.py"),
                ),
                (
                    REPO_ROOT / "examples" / "claude-code" / settings_name,
                    Path("claude-code/.claude/settings.json"),
                ),
            ]
        )
    if tool in {"codex", "both"}:
        selected.extend(
            [
                (
                    REPO_ROOT / "examples" / "codex" / "AGENTS.md.example",
                    Path("codex/AGENTS.md"),
                ),
                (
                    REPO_ROOT / "examples" / "codex" / "config.toml.example",
                    Path("codex/config.toml.example"),
                ),
                (
                    REPO_ROOT / "examples" / "codex" / "config.sequential.toml.example",
                    Path("codex/config.sequential.toml.example"),
                ),
                (
                    REPO_ROOT / "examples" / "codex" / "review.config.toml.example",
                    Path("codex/review.config.toml.example"),
                ),
            ]
        )
    return selected


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_bundle(target: Path, sources: list[tuple[Path, Path]]) -> None:
    if target.exists():
        raise AdoptionError(f"execution requires a new target path: {target}")
    if not target.parent.is_dir():
        raise AdoptionError(f"target parent directory does not exist: {target.parent}")
    with tempfile.TemporaryDirectory(prefix=f".{target.name}-", dir=target.parent) as directory:
        staging = Path(directory)
        for source, relative in sources:
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)

        expected_paths = {relative for _source, relative in sources}
        actual_paths = {
            candidate.relative_to(staging)
            for candidate in staging.rglob("*")
            if candidate.is_file()
        }
        if actual_paths != expected_paths:
            raise AdoptionError("staged bundle file set does not match the declared sources")
        for source, relative in sources:
            if _sha256(source) != _sha256(staging / relative):
                raise AdoptionError(f"staged bundle hash mismatch: {relative}")
        staging.replace(target)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--tool", choices=("both", "claude-code", "codex"), default="both")
    parser.add_argument("--platform", choices=("auto", "posix", "windows"), default="auto")
    parser.add_argument("--execute", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if sys.version_info < (3, 11):
        print("adopt: Python 3.11 or newer is required", file=sys.stderr)
        return 2
    try:
        target = _safe_target(args.target)
        platform = (
            ("windows" if os.name == "nt" else "posix")
            if args.platform == "auto"
            else args.platform
        )
        sources = _sources(args.tool, platform)
        if not sources:
            raise AdoptionError("no adoption files were selected")
        missing = [
            str(source)
            for source, _destination in sources
            if not source.is_file() or source.is_symlink()
        ]
        if missing:
            raise AdoptionError("missing or unsafe source file(s): " + ", ".join(missing))

        for source, relative in sources:
            print(f"{'COPY' if args.execute else 'WOULD COPY':10} {relative}")
        if not args.execute:
            print("dry-run only: pass --execute to build the bundle")
        else:
            _build_bundle(target, sources)
            print(f"bundle created and hash-verified: {target}")
        return 0
    except (AdoptionError, OSError) as exc:
        print(f"adopt: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
