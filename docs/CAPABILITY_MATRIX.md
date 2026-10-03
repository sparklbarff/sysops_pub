# Capability Matrix

`sysops_pub` teaches the private system's control model. It is not intended to reproduce every
private capability or manage a collaborator's live workstation directly.

| Capability | Private sysops | `sysops_pub` | Adoption status |
|---|---|---|---|
| Component registry | Declares ordered apply, verify, and validation handlers for the live macOS controller | Declares synthetic file components and supported platforms | Portable reimplementation |
| Safe preview | Dry-runs real defaults, Dock, shell, theme, and application adapters | Plans and previews file changes inside a marked sandbox | Portable reimplementation |
| Scoped apply | Applies selected host components and qualifiers | Applies selected profile components only inside a marked sandbox | Portable reimplementation with a narrower subject |
| Independent verification | Reads the live system through separate verifier functions; reporter and gate modes are distinct | Recomputes desired hashes independently and returns nonzero on mismatch | Portable reimplementation |
| Drift semantics | Compares live state directly with declared state; snapshots are diagnostic observations only | Detects missing and drifted sandbox files directly from declarations | Portable reimplementation |
| Status reporting | Covers every registered verifier component and names failed components | Reports matched, missing, drifted, unsafe, and unmanaged files | Portable reimplementation |
| Configuration validation | Validates the registry plus selected defaults, Brew, and Dock declarations | Validates registry, profile, platform, path, overlap, marker, and symlink constraints | Portable reimplementation |
| Repository bootstrap | Installs workstation prerequisites and packages | Previews, installs, and verifies only this clone's mandatory pre-push gate | Deliberately narrower |
| Delivery gates | Local pre-commit and post-commit controls protect the private source and deployment loop | A tracked pre-push gate verifies each exact outgoing commit in an isolated worktree | Portable control pattern, different lifecycle |
| Claude Code integration | Live identity, hooks, policies, and deployment | Reviewable project policy, settings, and scope-guard examples | Sanitized adapter |
| Selective grounding advisory | A UserPromptSubmit classifier that injects bounded local grounding for broad, indexed-repo prompts and stays silent on narrow work, fail-open | An advisory broad-versus-narrow classifier example with CLI and Claude hook modes, keyed on scope nouns, fail-open | Sanitized adapter |
| Codex integration | Live instructions, named profiles, sandbox policy, and parity validation | Reviewable instructions, named-profile, and sandbox configuration examples | Sanitized adapter |
| Local retrieval | Real local indexes, refresh fan-out, policy, receipts, and operational grounding | Synthetic corpus, repository-to-index fan-out, and deterministic retrieval-contract exercises | Sanitized reimplementation |
| Retrieval outcome semantics | Separates missing context, generated refusal, and human answer usability; excludes evaluation reports from their own index | Records context count and size, generation state, not-found emission, policy digest, and exclusions without claiming a retrieval hit is an answer | Sanitized reimplementation |
| Retrieval evaluation | A frozen, human-ratified cohort question set judged against retrieved context, measured before adopting any retriever or corpus change | A synthetic frozen set with curated-in-corpus, coverage-gap, and absent-control cohorts; verdicts judged against retrieved text and bound to the retriever id | Sanitized reimplementation |
| Supervised updates | Checks Homebrew, npm, pipx, uv, and casks; requires scoped apply; defers running apps; verifies and receipts each run | Updates only marked synthetic state with check-only default, exact-channel apply, running-item deferral, and verified receipts | Portable control pattern, no package-manager adapter |
| Process ownership | Owns managed background suites through terminal state and prevents abandoned unscoped work | Foreground runner waits for its child, cleans up only its owned process on timeout, and writes a sanitized receipt | Portable reimplementation with documented Windows limits |
| Off-machine publication | Claude mechanically denies Artifact and shared rules prohibit unapproved upload paths | Claude examples deny Artifact and both tool policies prohibit unapproved publication | Sanitized adapter |
| Browser automation | Firefox-only dedicated Playwright MCP registration with matching managed browser build | Generic explicit-browser and MCP-owned-install guidance using Firefox as the example | Sanitized adapter |
| Agent status cockpit | Live lifecycle hooks publish a sanitized repository label and state to iTerm2 | Optional non-mutating iTerm2 user-variable publisher; lifecycle wiring remains local | macOS optional adapter |
| macOS management | Homebrew, defaults, Dock, shell, window management, LaunchAgents, themes, privacy, and password-store integration | Lifecycle guidance only; no operating-system mutation command | Design-only by policy |
| Windows and Linux | Not the private controller's host target | Dependency-free core and the new operations demos are designed for both; native execution evidence is not yet recorded | Design-level compatibility, native proof retained as future work |
| Workstation diagnostics | Reads real host processes, applications, services, logs, and configuration | No live host diagnostics | Deliberate omission |
| AI configuration deployment | Reconciles a managed-file set plus hybrid settings | No live home-directory deployment | Deliberate omission |
| Secrets and recovery | Encrypted private material and password-store operations exist outside the share boundary | Prohibited by the export manifest and disclosure scanner | Deliberate omission |
| Memories, logs, ledgers, and analytics | Private continuity and observability surfaces | Prohibited; examples use synthetic fixtures | Deliberate omission |
| Spectre and Eidolon | Real project governance and evidence history remain private | Recognizable, sanitized case studies and exercises | Sanitized case study |
| Live user installer | Private scripts target one reviewed workstation | Adoption tool builds a reviewable bundle and installs project-local starters into a named existing project directory (preview-first, non-overwriting, settings merged after backup); installing into live home or global tool configuration stays deferred | Project-scoped; home install deferred |

## Reading the matrix

- **Portable reimplementation** means the repository contains executable code and isolated tests for
  the underlying control pattern.
- **Sanitized adapter** means the repository provides a reviewable starter rather than a copy of live
  configuration.
- **Design-only** means the interface and safety requirements are documented without claiming native
  execution evidence.
- **Deliberate omission** means adding the private capability would violate the teaching or disclosure
  boundary.

`adopt.py --into <project>` installs project-local starters (agent instructions, a scope guard, and
a merged `.claude/settings.json`) into an existing project directory you name, previewing by default
and never overwriting an existing file. Installing into live home or global tool configuration stays
deferred: that would change `sysops_pub` from a teaching and bundle-building repository into a
workstation configuration product, which requires auto-discovery, ownership, rollback, and a support
contract this reference does not take on.
