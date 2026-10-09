# Architecture

## Two control planes

The system separates portable policy from tool-specific integration.

```text
portable policy
  identity, scope, desired state, evidence rules
        |
        +---------------------+
        |                     |
        v                     v
Claude Code adapter       Codex adapter
hooks and context         instructions and sandbox
        |                     |
        +----------+----------+
                   |
                   v
          repository-local gates
```

Tool adapters are useful, but repository-local tests and version-control gates are the durable
evidence boundary. Advisory context should fail open. Safety controls responsible for preventing a
write should fail closed and carry an executable block/admit proof.

## The configuration loop

`registry/components.json` declares available components. A profile selects desired components.
The controller then exposes separate phases:

1. `plan`: compare desired files to the target without writing.
2. `apply`: preview by default; `--execute` writes only inside a marked sandbox.
3. `verify`: independently recompute expected hashes and compare the target.
4. `report`: summarize matched, missing, drifted, and unmanaged state.

Application and verification deliberately use separate functions. An apply function reporting
success is not proof that the intended state exists.

## Agent boundaries

A user-level operations agent owns shared AI configuration and workstation diagnostics. A project
agent owns project planning, implementation sequencing, and acceptance. The operations agent may
maintain shared enforcement used by a project, but it does not silently become that project's
planning agent.

This prevents one long-lived session from accumulating incompatible identities and hidden authority.

## Evidence model

For every important control, distinguish:

- Built: source exists.
- Wired: the runtime references it.
- Fires: a controlled bad input is blocked.
- Admits: a controlled good input passes.
- Reaches: the control observes the actual subject it claims to protect.

The last distinction catches controls that run successfully against a stale path, wrong process,
or unrelated executable.

Derived state also needs explicit ownership. A repository event can invalidate several indexes, so
refresh planning maps one repository identity to every owned index. Treating that relationship as
one-to-one can leave a secondary index stale while the refresh hook itself appears healthy.

The tracked pre-push control applies this model literally. It consumes Git's outgoing ref records,
materializes each outgoing commit in a temporary detached worktree, and runs the verifier contained
in that commit. Unit tests separately prove that the tracked shell launcher reaches this driver.

## Supervised operations

Long-running and machine-changing work needs a control loop of its own.

The synthetic update supervisor separates four concerns:

1. Check every declared channel without writing.
2. Require one explicitly named channel for apply.
3. Defer a running application instead of force-quitting it.
4. Reopen the persisted state and compare it with the complete expected result, including unselected
   channels, then receipt the expected and observed states separately.

The example changes only a marked synthetic state directory. Real package-manager adapters are an
adoption boundary because each platform needs its own discovery, rollback, privilege, and process
detection rules.

The managed-job runner addresses process ownership separately. It starts one foreground child,
waits through completion, and terminates only the process group it created on timeout or interrupt.
On POSIX it also checks the group after the leading process exits: surviving children force cleanup
and a nonzero ownership result. A leading process's success alone cannot certify terminal ownership.
Its receipt records the executable name and argument count but not raw arguments, which may contain
tokens or private paths. A runner cannot make an arbitrary command resource-safe, so worker limits
remain part of the called tool's reviewed invocation contract.

Budgeted concurrency, shared-daemon reconciliation and scheduled-job resource integration are
documented adaptation boundaries in `docs/OPERATIONS.md`, not implemented host adapters here.

## Retrieval claims

Retrieving context is not the same thing as answering a question. The synthetic retrieval receipt
therefore records `context_found` or `no_context`, context size, whether generation ran, and whether
a generator emitted a not-found marker. It never labels overlapping source text as an answer.

Corpus policy is also evidence. Evaluation and review reports are excluded from the example corpus,
and the receipt binds both the policy digest and excluded filenames. This prevents an evaluation
report from becoming evidence for its own question.
