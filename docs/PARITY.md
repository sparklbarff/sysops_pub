# Parity state

This repository is a sanitized public reference for a private operations system (`sysops`). It is
re-audited for parity with that private system so it does not silently drift as the private design
evolves. The audit is a human judgment, sanitization and faithfulness cannot be automated, so this
file records when it last ran and what should trigger the next one. It makes staleness answerable
without re-reading the whole repository.

## Last audit

- Date: 2026-10-09
- Private operations reference: October 9 source and deployed-control audit.
- Scope: the capability matrix, public instruction/configuration starters, control and delivery
  mechanisms, retrieval contracts, adoption boundary, and process/update receipts. The review
  distinguishes executable public controls from design-only operational guidance and deliberate
  omissions. It does not claim native execution on Windows or Linux.

## Evidence and changes

| Subject | Public source and executable evidence | Parity conclusion |
|---|---|---|
| Registry, preview, scoped apply, independent verification and drift | `tools/control.py`, `tests/test_control.py`, isolated demo tests | Synthetic file controller, not a live workstation adapter |
| Bootstrap and delivery | `tools/bootstrap.py`, `tools/pre_push.py`, `.githooks/pre-push`, their tests | Exact outgoing commits remain the delivery unit; no global installation |
| Agent policy and browser selection | `examples/claude-code/`, `examples/codex/`, `tests/test_policy_examples.py` | Starters preserve publication boundaries, cross-runtime evidence, explicit browser choice and readable output |
| Scope and grounding advisories | `examples/enforcement/`, their tests | Advice and blocking controls are distinct; installing policy is not behavioral proof |
| Local retrieval and evaluation | `tools/search_docs.py`, `tools/plan_index_refresh.py`, `tools/eval_retrieval.py`, their tests and `tools/case_exercises.py` | Synthetic retrieval evidence remains separate from answer quality |
| Supervised updates | `tools/update_supervisor.py`, `tests/test_update_supervisor.py` | Verification now reopens persisted state and checks the complete expected state, including unselected channels |
| Process ownership | `tools/managed_job.py`, `tests/test_managed_job.py` | POSIX group termination is verified independently of leader exit; surviving children cannot produce a success receipt |
| Runtime reconciliation and validation admission | `docs/OPERATIONS.md`, `docs/CAPABILITY_MATRIX.md` | Current operating disciplines are documented; no public daemon adapter, scheduler or memory sampler is claimed |
| Adoption | `tools/adopt.py`, `tests/test_adopt.py`, `docs/ADAPTATION_GUIDE.md` | Explicit, project-scoped and non-overwriting; existing identity and governance take precedence |
| Disclosure and case studies | `docs/EXPORT_MANIFEST.md`, `tools/disclosure_scan.py`, synthetic case exercises | No workstation data, credentials, transcripts or private operational receipts are exported |

Two operational regressions were demonstrated before their repairs. Dropping a synthetic update's disk write
still produced a successful verifier; changing an unselected channel also passed. A successful
leading process could leave its child alive, and timeout handling could miss a child ignoring TERM.
The repaired tests require persisted readback and terminal group ownership, and preserve an unrelated
process as a non-interference control. Receipt schema 2 exposes the new evidence explicitly.

Adoption also rejects symlinked roots and destination parents before any project write. The fixture
checks preview and execution with external `.claude` and `.agent-tools` links, preserving both the
project's instructions and the outside directory. Existing non-symlink project installation remains
an admitted control.

The complete local release verifier covers dependency-free tests, case exercises, JSON/TOML syntax,
tree cleanliness, formatting, linting, secret scans and mandatory hook wiring. These checks are
release evidence, not proof of creative quality, live agent compliance or every native platform.
Private runtime and resource-admission adapters remain out of this reference's executable scope.

## Re-audit trigger

Re-audit when either holds:

- Cadence: at least quarterly.
- Change-driven: whenever the private system's AI surface changes materially, its behavioral rules,
  its environment and hosting conventions, its retrieval tooling, or its enforcement hooks, because
  those are what the capability matrix represents. A material change there is the signal that a row
  may now misrepresent the private system, or that a matured discipline is missing from this mirror.

## How the audit runs

Read the subject's purpose first, from its own documents. Enumerate the capability matrix as the
parity contract. Verify each row against both sides from primary sources. Run a shape-versus-substance
faithfulness pass on every reference, a reference can reproduce a mechanism's form while misteaching
its substance. Cite the source behind every claim, so a skimmed audit shows up as uncited assertions.
