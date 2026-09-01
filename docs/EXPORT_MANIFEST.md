# Clean-room export manifest

This manifest is the safety contract between the private sysops system and this reference
repository. Nothing crosses merely because it is tracked or technically reusable.

## Dispositions

| Private source surface | Reference destination | Disposition | Reason |
|---|---|---|---|
| Root identity and scope instructions | `AGENTS.md`, `CLAUDE.md` | Rewrite | Preserve role boundaries without personal identity, paths, or fleet inventory |
| Three-tier agent policy | `docs/ARCHITECTURE.md` | Rewrite | Preserve separation of user operations and project ownership |
| Component registry | `registry/components.json` | Reimplement | Demonstrate one source of truth with synthetic components |
| Apply, verify, drift, and report orchestration | `tools/control.py` | Reimplement | Keep the control loop while removing host assumptions and mutation risk |
| Validation libraries and mocks | `tools/`, `tests/` | Reimplement | Provide executable proofs using only temporary fixtures |
| Enforcement hooks and wiring checks | `examples/enforcement/` | Reimplement | Show block/admit behavior without private paths or commands |
| Claude Code configuration | `examples/claude-code/` | Rewrite | Explain hooks and identity without copying live settings |
| Codex configuration | `examples/codex/` | Rewrite | Explain sandbox and instructions without copying live config |
| Local RAG policy and receipts | `samples/rag/` | Reimplement | Demonstrate the contract over a synthetic corpus; make Ollama optional |
| macOS configuration lifecycle | `docs/MACOS_OPTIONAL.md` | Rewrite | Show the pattern, not the owner's Dock, packages, defaults, or LaunchAgents |
| Spectre governance incidents | `docs/case-studies/SPECTRE.md` | Rewrite | Named case study, no private project implementation |
| Eidolon evidence incidents | `docs/case-studies/EIDOLON.md` | Rewrite | Named case study, no private project implementation |

## Omission-only surfaces

The following must never be copied, even into a private GitHub repository:

- `secrets/` and all key, certificate, credential, token, vault, and recovery material
- Password-store contents and GPG identifiers
- User memories, session handoffs, transcripts, and task state
- Hook logs, analytics databases, test ledgers, receipts tied to real sessions, and generated reports
- Absolute personal paths, usernames, email addresses, hostnames, IP addresses, device identifiers,
  volume names, and backup targets
- Live MCP registrations, account identifiers, service endpoints, and private repository inventory
- Generated model indexes, model caches, and local data stores
- Personal package lists, Dock contents, application inventories, and system defaults
- Scripts that patch protected applications, modify recovery state, delete snapshots, or restore keys
- Git history from the private repository

## Review gates

Before every push:

1. Run the local tests.
2. Search tracked content for personal paths and identifiers.
3. Run a secret scanner when available.
4. Inspect every tracked symlink and reject links outside this repository.
5. Confirm generated reports and demo sandboxes are untracked.
6. Review the complete staged diff, not only the commit summary.
