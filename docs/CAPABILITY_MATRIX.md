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
| Codex integration | Live instructions, named profiles, sandbox policy, and parity validation | Reviewable instructions, named-profile, and sandbox configuration examples | Sanitized adapter |
| Local retrieval | Real local indexes, refresh fan-out, policy, receipts, and operational grounding | Synthetic corpus, repository-to-index fan-out, and deterministic retrieval-contract exercises | Sanitized reimplementation |
| macOS management | Homebrew, defaults, Dock, shell, window management, LaunchAgents, themes, privacy, and password-store integration | Lifecycle guidance only; no operating-system mutation command | Design-only by policy |
| Windows and Linux | Not the private controller's host target | Dependency-free core is designed for both; native execution evidence is not yet recorded | Design-level compatibility |
| Workstation diagnostics | Reads real host processes, applications, services, logs, and configuration | No live host diagnostics | Deliberate omission |
| AI configuration deployment | Reconciles 119 managed files plus hybrid settings | No live home-directory deployment | Deliberate omission |
| Secrets and recovery | Encrypted private material and password-store operations exist outside the share boundary | Prohibited by the export manifest and disclosure scanner | Deliberate omission |
| Memories, logs, ledgers, and analytics | Private continuity and observability surfaces | Prohibited; examples use synthetic fixtures | Deliberate omission |
| Spectre and Eidolon | Real project governance and evidence history remain private | Recognizable, sanitized case studies and exercises | Sanitized case study |
| Live user installer | Private scripts target one reviewed workstation | Adoption tool builds a new reviewable bundle but does not install it into live tool or home configuration | Deferred product-boundary decision |

## Reading the matrix

- **Portable reimplementation** means the repository contains executable code and isolated tests for
  the underlying control pattern.
- **Sanitized adapter** means the repository provides a reviewable starter rather than a copy of live
  configuration.
- **Design-only** means the interface and safety requirements are documented without claiming native
  execution evidence.
- **Deliberate omission** means adding the private capability would violate the teaching or disclosure
  boundary.

The live user installer remains deferred because it would change `sysops_pub` from a teaching and
bundle-building repository into a workstation configuration product. That choice requires an
explicit target, ownership, rollback, and support contract.
