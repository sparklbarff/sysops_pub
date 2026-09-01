#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

python3 -m unittest discover -s tests -v
python3 scripts/disclosure_scan.py
./scripts/demo.sh >/dev/null
printf '%s\n' "test suite: pass"
