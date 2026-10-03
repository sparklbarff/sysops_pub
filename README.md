# sysops_pub

A sanitized, runnable reference implementation of a personal AI operations system: the control loop
one operator built to configure coding agents (Claude Code and Codex) and manage a workstation,
reduced to portable teaching code that carries no private data.

It exists to show a pattern, not to manage your machine. Everything tracked here is synthetic. The
private `sysops` system it mirrors is never exported: this repository has its own fresh history,
synthetic fixtures, and no credentials, paths, memories, or host configuration. What it keeps is the
shape of the system and the discipline behind it.

## What it demonstrates

- A declare-then-verify control loop that never trusts its own apply step.
- An evidence model that separates built, wired, fires, admits, and reaches, so a control that runs
  successfully against the wrong target is still caught.
- A boundary between a user-level operations agent and a project agent, so one long-lived session
  does not accumulate hidden authority.
- Supervised handling of long-running and machine-changing work: check without writing, require an
  explicit scope to act, defer a running application, and receipt every step.
- Retrieval that reports whether context was found and never claims that retrieving text is the same
  as answering a question.

The control loop:

```text
declared configuration
        |
        v
safe dry-run (preview by default)
        |
        v
scoped application (only inside a marked sandbox)
        |
        v
independent verification (recompute; do not trust the apply)
        |
        v
drift and status report
```

## Quick start

Requirements: Python 3.11 or newer. No third-party Python packages and no POSIX shell are needed for
the tour or the core tests. Use `python3` on macOS or Linux and `py -3` on Windows.

```text
git clone https://github.com/sparklbarff/sysops_pub.git
cd sysops_pub
python3 tools/demo.py      # sandboxed tour: plan, apply, verify, introduce drift, repair, report
python3 tools/test.py      # the dependency-free test suite
```

The demo builds a temporary marked sandbox, exercises the whole loop against it, and removes it on
exit. It does not write to your home directory or change any operating-system setting.

See `docs/QUICKSTART.md` for the Windows commands, the adoption-bundle builder, the supervised-update
and managed-job exercises, and the cross-platform evidence matrix.

## Repository map

- `registry/components.json`, `profiles/demo.json`: the single source of truth for demo components
  and the desired state that selects them.
- `tools/control.py`: plan, dry-run, scoped apply, independent verify, and report.
- `tools/adopt.py`: a dry-run-first builder for Claude Code and Codex starter bundles.
- `tools/update_supervisor.py`, `tools/managed_job.py`: supervised updates and foreground process
  ownership, each with sanitized receipts.
- `tools/bootstrap.py`, `tools/verify_release.py`: the mandatory repository-local pre-push gate and
  the complete local release check.
- `examples/`: reviewable Claude Code, Codex, and enforcement starters, plus an optional macOS iTerm2
  status publisher.
- `samples/rag/`: a synthetic corpus, a deterministic retrieval-contract exercise, and a frozen
  cohort retrieval-evaluation benchmark.
- `docs/ARCHITECTURE.md`, `docs/CAPABILITY_MATRIX.md`, `docs/EXPORT_MANIFEST.md`,
  `docs/SECURITY_BOUNDARY.md`: the design, the exact private-to-reference coverage, and the rules for
  what may cross from the private system.
- `docs/case-studies/`: two sanitized governance incidents, named Spectre and Eidolon.

## Safety model

The demo controller refuses to initialize `/`, this repository, the current directory, or a real
home; writes only inside a directory carrying its sandbox marker; rejects absolute and
parent-traversing registry paths and managed symlinks; previews by default and requires `--execute`
to write; and reports unmanaged files without ever deleting them.

Read `docs/SECURITY_BOUNDARY.md` before adapting any component to a real machine.

## What is intentionally absent

This repository teaches the control model; it is not a copy of the private system. It contains no
secrets, recovery material, password-store data, tokens, or credentials; no personal paths,
hostnames, IP addresses, email addresses, or device identifiers; no session memories, handoffs,
transcripts, metrics, ledgers, or generated reports; no live dispatches or private source; and no
destructive backup, privacy, theming, or operating-system mutation scripts. `docs/CAPABILITY_MATRIX.md`
records every capability, what the reference keeps, and what it deliberately omits.

Spectre and Eidolon appear only as recognizable, sanitized governance case studies, with no private
implementation.
