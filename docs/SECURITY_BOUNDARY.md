# Security boundary

`sysops_pub` is a public reference implementation. It contains only sanitized, synthetic teaching
material; nothing is exported here from the private sysops system it mirrors. Publication is exactly
why sanitization, not repository privacy, is the real boundary. Once a commit is public, clones,
forks, and caches make any disclosure permanent and impossible to recall, so every tracked file is
treated as already published the moment it is committed.

## Trust assumptions

- Tracked examples contain synthetic data only.
- The demo target is disposable and marked by the controller.
- No tracked script requires elevated privileges.
- No default command changes the host operating system.
- Claude Code hooks are advisory or narrowly scoped examples.
- Codex safety relies primarily on its sandbox and approval policy. Its hooks can block, but trust
  in each hook is granted by the human, never written by an installer.

## Threat model

The controls here defend against an agent's mistakes: a write outside the project, a publication
nobody authorized, a commit that reaches public history without its own verification, a process
left running after its leader exits, and a claim of success without evidence. They assume a model
that follows instructions imperfectly, not one that works against them.

They do not resist a hostile model, prompt injection carried in repository content, or a user who
routes around a hook. A shell command can still write a file the path guard never sees, and a hook
runs with the user's own privileges. Filesystem permissions, the runtime's sandbox, and the
repository gate remain the boundary; the hooks narrow the room for error inside it.

## Operating scope

One operator, one machine, several agents across two runtimes. Nothing here addresses two people
sharing an adopted project, shared credentials, or a hosted service. The pre-push gate is per clone,
and each clone installs it for itself.

## Adaptation boundary

Before using any component against a real home directory:

1. Copy the component into a separate private configuration repository.
2. Replace synthetic desired state with reviewed local values.
3. Add a component-specific validator.
4. Add an isolated block/admit or apply/verify test.
5. Keep dry-run as the default.
6. Require an explicit flag for mutation.
7. Make backups recoverable and scoped.

Do not turn this teaching repository itself into a secrets store.
