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
| Supervised update controller | `tools/update_supervisor.py`, `samples/updates/` | Reimplement | Preserve check, scope, deferral, receipt, and verify semantics without package managers or host inventory |
| Managed heavy-job wrapper | `tools/managed_job.py` | Reimplement | Preserve process ownership and sanitized receipt semantics without private commands or metrics |
| Acceptance calibration helper | `tools/calibrate_check.py`, `samples/calibration/` | Reimplement | Preserve rejection-for-the-stated-reason, input fingerprints and declared-case scope without private checkers or project artifacts |
| Assignment, acceptance and desktop-automation rules | Both project instruction examples | Rewrite | Preserve the disciplines without names, incidents or project history |
| Runtime reconciliation and validation admission | `docs/OPERATIONS.md` | Rewrite | Preserve ownership, budget and independent-evidence distinctions without exporting host services or queue state |
| Cross-runtime continuity | Both project instruction examples | Rewrite | Require complete runtime search and artifact-specific approval without exporting transcripts |
| iTerm2 agent cockpit | `examples/macos/iterm_agent_status.py` | Reimplement | Publish only sanitized label and state; omit hooks, paths, transcripts, and session data |
| macOS configuration lifecycle | `docs/MACOS_OPTIONAL.md` | Rewrite | Show the pattern, not the owner's Dock, packages, defaults, or LaunchAgents |
| Spectre governance incidents | `docs/case-studies/SPECTRE.md` | Rewrite | Named case study, no private project implementation |
| Eidolon evidence incidents | `docs/case-studies/EIDOLON.md` | Rewrite | Named case study, no private project implementation |

## Omission-only surfaces

The following must never be copied, even into a private GitHub repository:

- `secrets/` and all key, certificate, credential, token, vault, and recovery material
- Password-store contents and private key material
- User memories, session handoffs, transcripts, and task state
- Hook logs, analytics databases, test ledgers, receipts tied to real sessions, and generated reports
- Absolute personal paths, usernames, email addresses, hostnames, IP addresses, device identifiers,
  volume names, and backup targets
- Live MCP registrations, account identifiers, service endpoints, and private repository inventory
- Generated model indexes, model caches, and local data stores
- Personal package lists, Dock contents, application inventories, and system defaults
- Scripts that patch protected applications, modify recovery state, delete snapshots, or restore keys
- Git history from the private repository

Tracked files are UTF-8 text by default. A future binary requires an exact repository-relative
path, SHA-256, and non-empty reason in `scripts/disclosure_allowlist.json`. A changed hash, stale
entry, undecodable unlisted file, operational log/database/archive type, or omission-only path
fails the disclosure scan. A deliberately synthetic case fixture with an otherwise forbidden
operational filename requires the same exact path, hash, and reason binding.

Git commit metadata has one narrow exception: collaborators' GitHub account names, GitHub noreply
addresses, and cryptographic commit signatures may appear in author, committer, and signature
fields. They are repository provenance, not exported sysops data. The repository clone coordinate
is also allowed because it identifies this repository. Neither exception permits those identifiers
in tracked content, paths, examples, or operational data.

## Review gates

Before every push:

1. Run `python tools/verify_release.py --require-tools`.
2. Confirm the tracked-file disclosure scan and both current-tree and Git-history gitleaks scans
   pass. The disclosure scan also requires GitHub noreply author and committer addresses throughout
   repository history.
3. Confirm every tracked symlink remains inside the repository.
4. Confirm generated reports and demo sandboxes are absent or empty.
5. Review the complete candidate diff before committing and the complete outgoing commit range
   before pushing, not only the commit summary.
