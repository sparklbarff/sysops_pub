# Security boundary

`sysops_pub` is private for collaboration, but it is designed as though its contents could become
public later. Repository privacy is not a substitute for sanitization.

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
