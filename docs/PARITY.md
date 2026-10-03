# Parity state

This repository is a sanitized public reference for a private operations system (`sysops`). It is
re-audited for parity with that private system so it does not silently drift as the private design
evolves. The audit is a human judgment, sanitization and faithfulness cannot be automated, so this
file records when it last ran and what should trigger the next one. It makes staleness answerable
without re-reading the whole repository.

## Last audit

- Date: 2026-10-02
- Verified against private reference point: `sysops` commit `4f36545`
- Scope: a full-repository re-read, every capability-matrix row checked against both the private and
  public sides from primary sources, with a faithfulness pass on each reference.

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
