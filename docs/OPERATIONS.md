# Operations

The private system has matured beyond one exclusive work token and a package list. These are
adaptation patterns, not additional host-management adapters in this reference repository.

## Runtime and package ownership

A package receipt, the command on PATH, the selected service package, and the executable loaded
by a running service are different subjects. Version strings alone do not establish that their
bytes or configuration agree.

For a shared coding-agent service, inspect the selected and loaded executable generations, native
update policy, and client compatibility without restarting it. A mismatch should produce a
restart-required notice. It must not silently disconnect other sessions. Coordinate binary
replacement and native service reconciliation in an explicitly approved closed-client window.
Keep the supervisor's ownership distinct from a vendor application's own updater.

Treat check failure, policy deferral, installation failure, and verification failure as separate
outcomes. A later passing general verifier does not resolve an earlier package-specific failure.
Retain the package error and verify the package's actual consumer, not only its installation
receipt. For example, an installed Python package can still import an older copy if linking failed.

The synthetic updater demonstrates independent verification by reopening the state it wrote and
checking both the expected update and preservation of unselected channels. Its version-2 receipt
separates expected state from observed state. A dropped or collateral write cannot earn VERIFIED.

## Validation admission

One blanket execution token serializes cheap checks with expensive work. Separate bounded checks,
ordinary validation, exclusive heavy work, and comparable benchmarks. Ordinary validations can
share explicit memory and worker pools; benchmarks should exclude competing managed work only
where comparable timing requires it. Keep separable correctness checks outside the benchmark lease.

Budget the actual called tool. A thread environment variable is not a universal CPU quota, and a
formatter may use a process pool unless its own worker setting is supplied. Preserve test
populations, assertions, and project-specific invocation contracts.

Current reclaimable memory and active swapping are useful admission observations. Allocated swap
alone is not proof of current pressure. A request waiting for memory or network retry must not hold
an execution token. Record the blocking owner, reason transitions, wait by cause, executed wall
time, and measured process-group memory. Missing samples mean unknown, never zero.

Scheduled validation and update jobs need the same resource accounting as interactive agents.
Otherwise a queue can protect its own callers while background jobs bypass it. The portable
managed-job example owns execution but does not implement resource admission; a real scheduler
remains an adopter-owned integration.

## Process ownership

On POSIX, the managed-job example checks its fresh process group after the leading process exits.
If a child remains, it terminates that owned group and returns an ownership failure instead of
success. Timeout cleanup also waits for descendants and escalates when a child ignores termination.
Version-2 receipts state whether the group is terminal. Zombie processes do not count as active work.

This is group ownership, not confinement of a child that deliberately creates another session.
Windows retains leading-process termination only; complete descendant ownership needs a native Job
Object adapter. The reference does not claim that missing adapter or native Windows execution proof.

## Cross-runtime continuity

Project history belongs to the repository, not the tool used in the current session. Search every
runtime store used by the project before declaring an approval or predecessor record unavailable.
Keep the owner message linked to the exact presented artifact and stage. Technical validity is not
creative acceptance, and a direction or animatic approval is not finished-production approval.

A retired or parked runtime does not establish a dormant project. Verify the repository, active
worktrees, current owner, and current artifacts before making that claim. Distinguish a rule that
exists, a runtime that loads it, a test that exercises it, and behavior observed in a real session.

## Adoption and recovery

Preserve an existing agent identity. Additional planning, coding, or research roles and workflow
gates are choices tied to real project artifacts, not default folders every repository needs.
The project installer preserves existing instructions and merges settings; it does not certify
that an incumbent agent follows new guidance or that every inherited gate fires.

Before a relocation, measure source files, directories, bytes, metadata, and hashes. Compare the
destination and recovery copy before changing the binding. A same-disk recovery copy is useful
rollback material, not an independent backup. Deletion and backup destination selection remain
separate owner decisions.
