#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
demo_root=$(mktemp -d "${TMPDIR:-/tmp}/sysops_pub-demo.XXXXXX")

cleanup() {
  find "$demo_root" -mindepth 1 -delete
  rmdir "$demo_root"
}
trap cleanup EXIT INT TERM

control="$repo_root/tools/control.py"

printf '%s\n' "1. Initialize disposable sandbox"
python3 "$control" init --target "$demo_root"

printf '\n%s\n' "2. Preview desired state"
python3 "$control" plan --target "$demo_root"

printf '\n%s\n' "3. Prove apply defaults to dry-run"
python3 "$control" apply --target "$demo_root"

printf '\n%s\n' "4. Apply explicitly and verify independently"
python3 "$control" apply --target "$demo_root" --execute
python3 "$control" verify --target "$demo_root"

printf '\n%s\n' "5. Introduce drift and prove verification fails"
printf '%s\n' "locally changed" > "$demo_root/.config/sysops_pub/shell-banner/banner.txt"
if python3 "$control" verify --target "$demo_root"; then
  printf '%s\n' "ERROR: verification accepted drift" >&2
  exit 1
else
  printf '%s\n' "expected: drift was detected"
fi

printf '\n%s\n' "6. Repair through the declared control path"
python3 "$control" --component shell-banner apply --target "$demo_root" --execute
python3 "$control" verify --target "$demo_root"

printf '\n%s\n' "7. Emit final report"
python3 "$control" report --target "$demo_root"
