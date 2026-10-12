# Codex integration

Codex and Claude Code can share identity and workflow concepts, but their enforcement surfaces are
not interchangeable.

For Codex:

- Put global defaults in the user-level `AGENTS.md`.
- Put project identity and workflow in the nearest repository `AGENTS.md`.
- Use `workspace-write` or a stricter native sandbox as the durable write boundary.
- Keep approvals enabled for operations that leave the sandbox or alter external state.
- Use repository validators and Git hooks for acceptance evidence.
- Codex documents lifecycle hooks that can block: a `PreToolUse` hook denies a tool call with a
  deny decision or exit 2, configured in a hooks file or an inline hooks table in the config.
  Treat any hook event the runtime documents as advisory only as advisory.

`hooks.json.example` wires two of the guards from `examples/enforcement/` as project-local Codex
hooks: the scope guard on `apply_patch`, reading every file the patch names from its header lines
and requiring all of them to stay under the session's working directory, and the command guard on
`Bash`. The adoption tool places it at `.codex/hooks.json` beside the guards under `.agent-tools/`.
Codex runs each command string through a shell from the session's working directory, so the
example resolves the guard's path from the Git root rather than relying on a relative path. The
test suite runs the adopted commands through a real shell with apply_patch and Bash payloads and
proves both block and admit behavior. The read guard is not wired for Codex: Codex reads files
through the shell, so there is no read event to record against.

Hook trust is the human's. Codex records trust against each hook's hash, and a new or changed hook
is skipped until the human trusts it again. As observed on a current release, the record is also
keyed to the handler's position in its group: inserting a handler ahead of a trusted one shifts the
trusted handlers, every shifted handler stops running until re-trusted, and under non-interactive
execution nothing reports it. After placing or changing `.codex/hooks.json`, open `/hooks` in the
CLI and trust each handler yourself. Append new handlers after trusted ones, never insert ahead of
them, re-trust after every change, and never let an installer write trust entries; the adoption
tool here never touches them.

`config.toml.example` contains the sandbox and approval baseline, a quieter display preference, and
explicit analytics opt-out. These do not lower model effort or impose an answer-verbosity limit.
Current Codex configuration
documents `workspace-write` and `on-request` as supported values. Copy individual reviewed keys
into your own config rather than replacing a tool-managed configuration wholesale.

`config.sequential.toml.example` separately disables multi-agent tools through `[agents]`. That is
an optional workflow preference, not a sandbox security control.

`review.config.toml.example` demonstrates a named, read-only profile. Review it, save it beside
`config.toml` as `$CODEX_HOME/review.config.toml`, then select it explicitly:

```sh
codex --profile review
```

Keep profile files separate from `config.toml`. Do not translate them into inline
`[profiles.review]` tables. The profile uses `developer_instructions`; the similarly named
`instructions` key is reserved for future use.

`AGENTS.md.example` is a self-contained starter policy. Adapt its identity, scope, and repository
test command before use.

Some Codex surfaces advertise optional structured-input tools that are unavailable in the active
interaction mode. Treat that as a capability mismatch, not a reason to enable undocumented flags:
ask one concise question in normal conversation only when the answer materially changes the work,
then continue with stated assumptions when it does not.

For shared-service deployments, keep native thread identity separate from the service's startup
environment. Do not inject one-off configuration overrides merely to attach identity; some runtime
versions select embedded mode for such overrides. Inspect the installed runtime before changing
launch arguments, and never restart a shared service as an automatic drift repair.

Official reference: https://learn.chatgpt.com/docs/config-file/config-reference
