#!/usr/bin/env python3
"""Run the portable control-loop tour in a disposable sandbox."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTROL = REPO_ROOT / "tools" / "control.py"


class DemoError(RuntimeError):
    """A demo step produced an unexpected exit status."""


def _step(number: int, message: str) -> None:
    print(f"\n{number}. {message}", flush=True)


def _control(arguments: Sequence[str], expected: set[int] | None = None) -> int:
    accepted = expected or {0}
    command = [sys.executable, str(CONTROL), *arguments]
    result = subprocess.run(command, check=False)
    if result.returncode not in accepted:
        raise DemoError(
            f"control command returned {result.returncode}; expected {sorted(accepted)}"
        )
    return result.returncode


def main() -> int:

    try:
        with tempfile.TemporaryDirectory(prefix="sysops_pub-demo-") as directory:
            target = Path(directory)
            _step(1, "Initialize disposable sandbox")
            _control(["init", "--target", str(target)])

            _step(2, "Preview desired state")
            _control(["plan", "--target", str(target)])

            _step(3, "Prove apply defaults to dry-run")
            _control(["apply", "--target", str(target)])

            _step(4, "Apply explicitly and verify independently")
            _control(["apply", "--target", str(target), "--execute"])
            _control(["verify", "--target", str(target)])

            _step(5, "Introduce drift and prove verification fails")
            banner = target / ".config" / "sysops_pub" / "shell-banner" / "banner.txt"
            banner.write_text("locally changed\n", encoding="utf-8")
            _control(["verify", "--target", str(target)], expected={1})
            print("expected: drift was detected")

            _step(6, "Repair through the declared control path")
            _control(
                [
                    "--component",
                    "shell-banner",
                    "apply",
                    "--target",
                    str(target),
                    "--execute",
                ]
            )
            _control(["verify", "--target", str(target)])

            _step(7, "Report an unmanaged file without deleting it")
            unmanaged = target / ".config" / "sysops_pub" / "shell-banner" / "local.txt"
            unmanaged.write_text("unmanaged and preserved\n", encoding="utf-8")
            _control(["report", "--target", str(target)])
            if not unmanaged.is_file():
                raise DemoError("reporting unexpectedly removed an unmanaged file")
    except (DemoError, OSError) as exc:
        print(f"demo: {exc}", file=sys.stderr)
        return 1

    print("\ndemo: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
