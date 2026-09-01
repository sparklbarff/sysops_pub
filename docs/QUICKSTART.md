# Quick start

This repository supports Windows, macOS, and Linux. The primary commands are Python programs, so a
POSIX shell is optional.

## Get the repository

After the repository owner adds you as a collaborator:

```text
git clone https://github.com/sparklbarff/sysops_pub.git
cd sysops_pub
```

Install Python 3.11 or newer. No Python packages are required for the tour or core tests.

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

The dependency-free suite works on every supported platform:

```text
python tools/test.py
```

The complete release verifier additionally runs Black, Ruff, gitleaks, and ShellCheck when they are
installed. The private repository maintainer runs it with `--require-tools` before pushing:

```text
python tools/verify_release.py --require-tools
```

The last release step remains human: review the complete staged diff.
