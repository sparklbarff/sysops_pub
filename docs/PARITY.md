# Parity state

This repository is a sanitized public reference for a private operations system (`sysops`). It is
re-audited for parity with that private system so it does not silently drift as the private design
evolves. The audit is a human judgment, sanitization and faithfulness cannot be automated, so this
file records when it last ran and what should trigger the next one. It makes staleness answerable
without re-reading the whole repository.

## Last audit

- Date: 2026-10-10
- Private operations reference: changes after the October 9 audit, namely the shared behavioral
  rules (assignment preservation, outcome-specific acceptance, desktop-automation targeting), the
  acceptance-calibration helper, and the updater's package-health and unresolved-failure handling.
- Scope: the capability matrix, both instruction starters, supervised updates, acceptance
  calibration, the export manifest, and the operations and quickstart guides. Runtime-specific
  service changes in the same period (daemon startup directory, workspace trust, a client version
  update) stay out of scope: this reference claims no service adapter. It does not claim native
  execution on Windows or Linux.

## Evidence and changes

| Subject | Public source and executable evidence | Parity conclusion |
|---|---|---|
| Registry, preview, scoped apply, independent verification and drift | `tools/control.py`, `tests/test_control.py`, isolated demo tests | Synthetic file controller, not a live workstation adapter |
| Bootstrap and delivery | `tools/bootstrap.py`, `tools/pre_push.py`, `.githooks/pre-push`, their tests | Exact outgoing commits remain the delivery unit; no global installation |
| Agent policy and browser selection | `examples/claude-code/`, `examples/codex/`, `tests/test_policy_examples.py` | Starters preserve publication boundaries, cross-runtime evidence, explicit browser choice, readable output, the user's assignment, outcome-specific acceptance and targeted desktop automation |
| Scope and grounding advisories | `examples/enforcement/`, their tests | Advice and blocking controls are distinct; installing policy is not behavioral proof |
| Local retrieval and evaluation | `tools/search_docs.py`, `tools/plan_index_refresh.py`, `tools/eval_retrieval.py`, their tests and `tools/case_exercises.py` | Synthetic retrieval evidence remains separate from answer quality |
| Supervised updates | `tools/update_supervisor.py`, `tests/test_update_supervisor.py` | Verification reopens persisted state and checks the complete expected state, including unselected channels; a failed update persists in `unresolved.json` until a later run reaches its target or the catalog's current version |
| Acceptance calibration | `tools/calibrate_check.py`, `samples/calibration/`, `tests/test_calibrate_check.py` | Rejection must carry the declared code and diagnostic; claim-trusting, syntax-error, input-changing and hanging checkers fail; declared cases only |
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

The October 10 refresh followed the same discipline. Each new update test failed against the
previous code on behavior, not on a missing name: no record was written, an outdated record never
cleared, and an update that never happened raised nothing. The calibration tests were first run
against an always-pass stub, which seven of eight rejected; the eighth checks the valid path and
is indifferent to that stub by design. The private updater repair that motivated the record rule
came from a real case where a pinned target could never be met after a newer release installed.

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
