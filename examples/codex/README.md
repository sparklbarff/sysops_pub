# Codex integration

Codex and Claude Code can share identity and workflow concepts, but their enforcement surfaces are
not interchangeable.

For Codex:

- Put global defaults in the user-level `AGENTS.md`.
- Put project identity and workflow in the nearest repository `AGENTS.md`.
- Use `workspace-write` or a stricter native sandbox as the durable write boundary.
- Keep approvals enabled for operations that leave the sandbox or alter external state.
- Use repository validators and Git hooks for acceptance evidence.
- Treat lifecycle context hooks as advisory unless the runtime documents a durable block contract.

`config.toml.example` contains only the sandbox and approval baseline. Current Codex configuration
documents `workspace-write` and `on-request` as supported values. Copy individual reviewed keys
into your own config rather than replacing a tool-managed configuration wholesale.

`config.sequential.toml.example` separately disables multi-agent tools through `[agents]`. That is
an optional workflow preference, not a sandbox security control.

`AGENTS.md.example` is a self-contained starter policy. Adapt its identity, scope, and repository
test command before use.

Official reference: https://learn.chatgpt.com/docs/config-file/config-reference
