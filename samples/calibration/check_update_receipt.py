#!/usr/bin/env python3
"""Accept a synthetic update receipt only when its persisted state matches the expected state."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: check_update_receipt.py RECEIPT", file=sys.stderr)
        return 2
    receipt = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    if receipt.get("verification_passed") is not True:
        print("REJECT: receipt does not claim verification")
        return 1
    # The claim alone is not evidence: the regression this check exists for claimed success
    # after a dropped write. Compare what was read back with what was expected.
    if receipt.get("after") != receipt.get("expected_after"):
        print("REJECT: persisted state differs from expected")
        return 1
    print("ACCEPT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
