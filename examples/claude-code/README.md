# Claude Code integration

Claude Code can combine repository instructions with lifecycle hooks.

1. Keep durable project identity in the repository's `CLAUDE.md` or configured instruction file.
2. Keep shared concepts mirrored in `AGENTS.md` for other agents.
3. Use hooks for narrow events with clear input and output contracts.
4. Give every blocking hook an executable test proving both block and admit behavior.
5. Keep Git hooks and repository validators as independent acceptance evidence.

The POSIX and Windows settings examples wire three guards from `examples/enforcement/`. The scope
guard runs on `PreToolUse` for `Write`, `Edit` and `NotebookEdit` and exits 2 when a file path
resolves outside `CLAUDE_PROJECT_DIR`, when the project root is unavailable, or when hook input is
malformed or lacks a supported path. The command guard runs on `PreToolUse` for `Bash` and
`WebFetch` and blocks credential reads and writes, recursive deletes and pipe-to-shell commands, a
pipe after `git push`, and fetches of private addresses. The read guard records every `Read`,
`Write`, `Edit` and `NotebookEdit` on `PostToolUse`, blocks an `Edit` or `NotebookEdit` of a file
not read this session or changed since, and blocks a `Bash` command that names a path with a
pending stale block. The test suite feeds real JSON through stdin to each guard and runs the
adopted settings' commands end to end, proving both block and admit behavior.

Both settings examples also deny the named `Artifact` tool. This is a narrow mechanical control for
one known publication path. The accompanying project instructions state the broader rule because a
tool-name deny cannot recognize every gist, paste service, upload command, or newly configured
remote.

Use `settings.posix.json.example` with `python3` on macOS, Linux, WSL, or Git Bash. Use
`settings.windows.json.example` with the Windows `py -3` launcher. Both use structured `command`
and `args` fields, so path placeholder expansion does not depend on POSIX, Git Bash, or PowerShell
quoting rules. The adoption bundle places the guard under `.agent-tools/`, which is the path used
by both examples.

`CLAUDE.md.example` is a self-contained starter policy. Adapt its identity, scope, and repository
test command before use.

This is a teaching example, not a complete security boundary. Shell commands can write files
without using `Write` or `Edit`, so a production configuration also needs command controls,
filesystem permissions, and repository gates. The guard narrows an agent's mistakes; it is not a
defense against a hostile agent or against prompt injection, and it runs with the user's own
privileges.

Read `PLAYWRIGHT.md.example` before enabling browser automation. It requires explicit browser
selection, an automation-only browser build, and verification of the process actually launched.
