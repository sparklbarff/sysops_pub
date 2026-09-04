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
