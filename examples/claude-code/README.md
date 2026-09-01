# Claude Code integration

Claude Code can combine repository instructions with lifecycle hooks.

1. Keep durable project identity in the repository's `CLAUDE.md` or configured instruction file.
2. Keep shared concepts mirrored in `AGENTS.md` for other agents.
3. Use hooks for narrow events with clear input and output contracts.
4. Give every blocking hook an executable test proving both block and admit behavior.
5. Keep Git hooks and repository validators as independent acceptance evidence.

`settings.json.example` wires the sample scope guard to `PreToolUse` for `Write` and `Edit`. The
guard exits 2 when a file path resolves outside `CLAUDE_PROJECT_DIR`.

This is a teaching example, not a complete security boundary. Shell commands can write files
without using `Write` or `Edit`, so a production configuration also needs command controls,
filesystem permissions, and repository gates.
