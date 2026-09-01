# sysops_pub

A sanitized reference implementation of a personal AI operations system.

This repository demonstrates a repeatable control loop for agent configuration and workstation
automation:

```text
declared configuration
        |
        v
safe dry-run
        |
        v
scoped application
        |
        v
independent verification
        |
        v
drift and status report
```

It is designed for two uses:

1. Read the architecture and case studies to understand the system.
2. Run the sandbox demo, then adapt selected pieces for Claude Code or Codex.

This is not a mirror of the live sysops repository. It has fresh history, synthetic fixtures, no
operational memories, and no machine-specific credentials or configuration.

## Five-minute tour

Requirements: Python 3.11 or newer and a POSIX shell.

```sh
./scripts/demo.sh
```

The demo creates a temporary marked sandbox, previews two declared components, applies them,
verifies the result, introduces drift, detects it, repairs it, and emits a final status report. It
does not write to your home directory or change operating-system settings.

Run the local test suite:

```sh
./scripts/test.sh
```

## Repository map

- `registry/components.json`: single source of truth for available demo components
- `profiles/demo.json`: selected desired state
- `tools/control.py`: plan, dry-run, scoped apply, verify, and report commands
- `examples/enforcement/scope_guard.py`: small executable allow/block proof
- `examples/claude-code/`: Claude Code identity and hook integration guidance
- `examples/codex/`: Codex identity and sandbox integration guidance
- `samples/rag/`: synthetic corpus and a deterministic retrieval-contract example
- `docs/case-studies/`: sanitized Spectre and Eidolon incidents
- `docs/EXPORT_MANIFEST.md`: what may and may not cross from the private system

## Safety model

The demo controller:

- refuses to initialize `/`, the repository itself, the current directory, or the real home;
- applies only inside a directory carrying its sandbox marker;
- rejects absolute and parent-traversing registry paths;
- refuses symlinks on managed source and destination paths;
- previews by default and requires `--execute` to write;
- never deletes unmanaged files.

Read `docs/SECURITY_BOUNDARY.md` before adapting it to a real machine.

## What is intentionally absent

- Secrets, encrypted recovery material, password-store data, tokens, and credentials
- Personal paths, hostnames, IP addresses, email addresses, and device identifiers
- Session memories, handoffs, transcripts, metrics, ledgers, logs, and generated reports
- Live project dispatches or private source code
- Destructive backup, privacy, theming, and operating-system mutation scripts

Spectre and Eidolon appear only as recognizable governance case studies.
