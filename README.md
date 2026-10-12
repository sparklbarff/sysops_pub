# sysops_pub

A sanitized, runnable reference implementation of a personal AI operations system: the control loop
one operator built to configure coding agents (Claude Code and Codex) and manage a workstation,
reduced to portable teaching code that carries no private data.

It exists to show a pattern, not to manage your machine. Everything tracked here is synthetic. The
private `sysops` system it mirrors is never exported: this repository has its own fresh history,
synthetic fixtures, and no credentials, paths, memories, or host configuration. What it keeps is the
shape of the system and the discipline behind it.

## Who it is for

One operator running several coding agents on one machine, across Claude Code and Codex, who wants
controls that are tested rather than asserted. It is not a drop-in rules pack and not a product.
Read the architecture, run the demo, then take one tier at a time from the use-scope table below:
run the tools that work as-is, copy the patterns, and read the demonstrations.

## What it demonstrates

- A declare-then-verify control loop that never trusts its own apply step.
- An evidence model that separates built, wired, fires, admits, and reaches, so a control that runs
  successfully against the wrong target is still caught.
- A boundary between a user-level operations agent and a project agent, so one long-lived session
  does not accumulate hidden authority.
- Supervised handling of long-running and machine-changing work: check without writing, require an
  explicit scope to act, defer a running application, and receipt every step.
- Independent update readback and terminal process-group ownership, including negative tests for
  dropped writes, collateral changes, and children that outlive their leading process.
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
the tour or the core tests. It is developed and verified on macOS. The Python-only design is written
to run on Linux and Windows too, but neither is tested, and the Windows commands in the quick start
guide are an untested design sketch.

```text
git clone https://github.com/sparklbarff/sysops_pub.git
cd sysops_pub
python3 tools/demo.py      # sandboxed tour: plan, apply, verify, introduce drift, repair, report
python3 tools/test.py      # the dependency-free test suite
```

The demo builds a temporary marked sandbox, exercises the whole loop against it, and removes it on
exit. It does not write to your home directory or change any operating-system setting.

See `docs/QUICKSTART.md` for the adoption-bundle builder, the supervised-update and managed-job
exercises, the untested Windows commands, and the platform evidence table.

## Adopt it

This repository is meant to be adapted, not only read. Run the demo, then take one component at a
time into your own configuration. `tools/adopt.py` either builds a reviewable starter bundle outside
this repository (`--target`, dry-run by default) or installs the project-local starters straight
into an existing project you name (`--into`, also preview-first and never overwriting an existing
file). It does not touch your live home or global tool configuration. `docs/ADAPTATION_GUIDE.md`
walks through adding a component, adopting the agent policy, and adopting retrieval.

## Repository map

- `registry/components.json`, `profiles/demo.json`: the single source of truth for demo components
  and the desired state that selects them.
- `tools/control.py`: plan, dry-run, scoped apply, independent verify, and report.
- `tools/adopt.py`: a dry-run-first tool that builds a reviewable Claude Code and Codex starter
  bundle (`--target`) or installs the project-local starters into a project you name (`--into`).
- `tools/update_supervisor.py`, `tools/managed_job.py`: supervised updates and foreground process
  ownership, each with sanitized receipts.
- `tools/calibrate_check.py`, `samples/calibration/`: proof that a checker rejects a preserved known
  failure for its stated reason and accepts valid cases.
- `tools/bootstrap.py`, `tools/verify_release.py`: the mandatory repository-local pre-push gate and
  the complete local release check.
- `examples/`: reviewable Claude Code, Codex, and enforcement starters, plus an optional macOS iTerm2
  status publisher.
- `samples/rag/`: a synthetic corpus, a deterministic retrieval-contract exercise, and a frozen
  cohort retrieval-evaluation benchmark.
- `docs/ARCHITECTURE.md`, `docs/CAPABILITY_MATRIX.md`, `docs/EXPORT_MANIFEST.md`,
  `docs/SECURITY_BOUNDARY.md`: the design, the exact private-to-reference coverage, and the rules for
  what may cross from the private system.
- `docs/OPERATIONS.md`: shared-runtime coordination, budgeted validation, cross-runtime continuity,
  preservation-first adoption, and recovery boundaries, with unimplemented adapters named explicitly.
- `docs/case-studies/`: two sanitized governance incidents, named Spectre and Eidolon.
- `tools/build_site.py`, `site/`: the reference-manual website, generated from these documents and
  from each tool's own argument parser; the build writes to the ignored `_site/`.

## Use scope

Not every tool here is meant to run against your project. Three tiers:

| Tier | Tools | What it means |
|---|---|---|
| Run it | `tools/managed_job.py`, `tools/calibrate_check.py` | Usable as-is from this checkout against any project today |
| Copy it | `tools/pre_push.py` with `tools/bootstrap.py` and `tools/verify_release.py`; `examples/enforcement/scope_guard.py`, `examples/enforcement/command_guard.py` and `examples/enforcement/read_guard.py` with the settings and instruction starters; `scripts/disclosure_scan.py` | Patterns to copy into your project: the gate is three files and runs whatever command your own pyproject declares, the guards install as-is through the adoption tool but see only what their hook events carry, and the scanner is rooted here |
| Read it | `tools/control.py`, `tools/demo.py`, `tools/update_supervisor.py`, `tools/search_docs.py`, `tools/eval_retrieval.py`, `tools/plan_index_refresh.py`, `tools/case_exercises.py`, `examples/enforcement/grounding_classifier.py`, `examples/macos/iterm_agent_status.py` | Demonstrations of a contract over sandboxes or synthetic inputs; the retrieval tools accept your own corpus but rank by token overlap |

`tools/adopt.py`, `tools/test.py` and `tools/build_site.py` are this repository's own installer,
suite runner and manual generator.

## Safety model

The demo controller refuses to initialize `/`, this repository, the current directory, or a real
home; writes only inside a directory carrying its sandbox marker; rejects absolute and
parent-traversing registry paths and managed symlinks; previews by default and requires `--execute`
to write; and reports unmanaged files without ever deleting them.

What the harness defends against is an agent's mistake: a write outside its scope, a publication
nobody authorized, a commit that reached a public history unverified, a process left running, or a
claim made without evidence. It does not resist a hostile model, a prompt injection, or a user
working around it, and it does not replace filesystem permissions or a sandbox.

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

The private system's local retrieval runs on a FAISS index and an Ollama model pipeline; this
reference reimplements the same retrieval contract over a synthetic corpus with no model or index
dependency, so the engine itself is not bundled (see the capability matrix).

## Support and versioning

This repository is unsupported. There is no compatibility promise: command-line flags, receipt
schemas and starter contents can change between the revisions listed in `CHANGELOG.md`. The one
guarantee is the release gate's: every published commit passed its own suite, disclosure scan and
secret scans. Issues are read; pull requests are not solicited. A defect that could disclose private
data or weaken a control is reported as described in `SECURITY.md`. It is built and verified by one
operator on macOS.

## License

MIT, see [LICENSE](LICENSE). The patterns here are meant to be copied and adapted into your own
configuration; the license is permissive so you can.
