# Quick start

This repository is designed for Windows, macOS, and Linux. The primary commands are Python
programs, so a POSIX shell is optional. Design compatibility is not a claim that every release was
natively executed on all three operating systems.

## Get the repository

After the repository owner adds you as a collaborator:

```text
git clone https://github.com/sparklbarff/sysops_pub.git
cd sysops_pub
```

Install Python 3.11 or newer. No Python packages are required for the tour or core tests.

Install the mandatory local pre-push gate after cloning. Preview first, then execute:

macOS or Linux:

```sh
python3 tools/bootstrap.py
python3 tools/bootstrap.py --execute
```

Windows:

```powershell
py -3 tools/bootstrap.py
py -3 tools/bootstrap.py --execute
```

This writes only the clone-local `core.hooksPath` setting. The tracked hook runs the complete local
release verifier before Git sends a push. It does not configure hosted CI.

## Choose a path

For a conceptual tour, read `README.md`, `docs/ARCHITECTURE.md`, and the two files under
`docs/case-studies/`.

For an executable tour on macOS or Linux:

```sh
python3 tools/demo.py
python3 tools/test.py
```

For an executable tour on Windows:

```powershell
py -3 tools/demo.py
py -3 tools/test.py
```

The demo writes only to a temporary marked sandbox and removes it on exit.

## Build an adoption bundle

The adoption tool does not edit Claude Code, Codex, or home-directory configuration. It previews a
starter bundle in a directory you choose.

macOS or Linux:

```sh
python3 tools/adopt.py --target ../sysops-starter --tool both
python3 tools/adopt.py --target ../sysops-starter --tool both --execute
```

Windows:

```powershell
py -3 tools/adopt.py --target ../sysops-starter --tool both
py -3 tools/adopt.py --target ../sysops-starter --tool both --execute
```

Review the generated `claude-code/` and `codex/` directories independently. They demonstrate the
same policy concepts through different enforcement mechanisms. Do not replace an existing settings
file wholesale.

## Platform notes

- Windows Claude Code runs through WSL or Git for Windows. The generated native Windows example
  uses Git Bash environment expansion and the `py -3` launcher.
- macOS and Linux examples use `python3`.
- The Codex example contains only reviewed sandbox and approval keys. Disabling multi-agent tools is
  offered separately as an optional workflow preference.
- The optional macOS document explains a lifecycle pattern but includes no system mutation command.

## Maintainer verification

The dependency-free suite is the portable compatibility contract:

```text
python tools/test.py
```

The complete release verifier requires Black, Ruff, gitleaks, and ShellCheck in maintainer mode. It
also verifies that the tracked local pre-push hook is wired, scans both the current tree and Git
history with gitleaks, and runs automatically on push:

```text
python tools/verify_release.py --require-tools
```

The last release step remains human: review the complete staged diff.
