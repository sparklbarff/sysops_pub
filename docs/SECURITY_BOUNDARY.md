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
- Codex safety relies primarily on its sandbox and approval policy, not an imitation hook layer.

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
