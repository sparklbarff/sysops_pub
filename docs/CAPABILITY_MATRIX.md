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
| Repository bootstrap | Installs workstation prerequisites and packages | Previews, installs, verifies and removes only this clone's mandatory pre-push gate; reads the hooks path Git actually uses, local or inherited, and takes over an existing binding only when told, restoring it on removal | Deliberately narrower |
| Delivery gates | Local pre-commit and post-commit controls protect the private source and deployment loop | A tracked pre-push gate verifies each exact outgoing commit in an isolated worktree, bounded by what the receiving location reports it holds, never by tracking refs or the remote's name | Portable control pattern, different lifecycle |
| Claude Code integration | Live identity, hooks, policies, and deployment | Reviewable project policy, settings, and three wired guards with block-and-admit proofs | Sanitized adapter |
| Command guard | A multi-tool guard blocks credential reads and writes, dangerous commands, pipe-masked pushes and private-address fetches, by parsed command structure | `examples/enforcement/command_guard.py`: the same five classes over synthetic commands, top-level structure only, unparsable input blocked | Portable reimplementation; substitutions and interpreter strings are documented blind spots |
| Edit freshness guard | Blocks an Edit of a file not fully read this session or changed on disk since, and a shell write to a path with a pending stale block | `examples/enforcement/read_guard.py`: record, check and shell modes keyed by session, state outside the project, Write exempt | Portable reimplementation; a windowed read counts as a read |
| Selective grounding advisory | A UserPromptSubmit classifier that injects bounded local grounding for broad, indexed-repo prompts and stays silent on narrow work, fail-open | An advisory broad-versus-narrow classifier example with CLI and Claude hook modes, keyed on scope nouns, fail-open | Sanitized adapter |
| Codex integration | Live instructions, named profiles, sandbox policy, blocking hooks with human-granted trust, and parity validation | Reviewable instructions, named-profile and sandbox configuration examples, and a project hooks file that wires the scope guard on apply_patch and the command guard on Bash, proven through a real shell; trust stays the human's | Sanitized adapter |
| Local retrieval | Real local indexes, refresh fan-out, policy, receipts, and operational grounding | Synthetic corpus, repository-to-index fan-out, and deterministic retrieval-contract exercises | Sanitized reimplementation |
| Retrieval outcome semantics | Separates missing context, generated refusal, and human answer usability; excludes evaluation reports from their own index | Records context count and size, generation state, not-found emission, policy digest, and exclusions without claiming a retrieval hit is an answer | Sanitized reimplementation |
| Retrieval evaluation | A frozen, human-ratified cohort question set judged against retrieved context, measured before adopting any retriever or corpus change | A synthetic frozen set with curated-in-corpus, coverage-gap, and absent-control cohorts; verdicts judged against retrieved text and bound to the retriever id | Sanitized reimplementation |
| Supervised updates | Checks Homebrew, npm, pipx, uv, and casks; requires scoped apply; defers running apps; verifies each package's selected version, link and consumer; persists unresolved failures until a later run proves them resolved | Updates marked synthetic state with check-only default, exact-channel apply, running-item deferral, independent disk readback, expected-versus-observed receipts, and a persisted unresolved-failure record that a plain check cannot hide; a recorded target clears at that target or the catalog's current version | Portable control pattern, no package-manager adapter |
| Shared runtime reconciliation | Passively compares client, selected package, loaded executable and native update policy; coordinated replacement must preserve live sessions | Ownership and restart-required notice pattern in `docs/OPERATIONS.md`; no service adapter | Design-only |
| Validation admission | Separate bounded checks, budgeted ordinary validation, exclusive heavy work and isolated benchmarks, with current-memory evidence and measured receipts | Resource-contract and scheduled-job integration guidance in `docs/OPERATIONS.md`; no queue or memory sampler | Design-only |
| Process ownership | Owns managed background suites through terminal state and prevents abandoned unscoped work | POSIX runner verifies its group is terminal even after leader exit, cleans up surviving children, fails unknown ownership, and writes a sanitized receipt | Portable reimplementation with documented Windows and escaped-session limits |
| Acceptance calibration | An owner-local helper proves a repaired checker rejects a preserved known failure for its stated reason and accepts a valid case and an allowed variation, keeping checker and fixture hashes | `tools/calibrate_check.py` with a synthetic receipt checker and preserved failure; tests reject a claim-trusting checker, a syntax error, an input-changing checker and a hang | Portable reimplementation; declared cases only, not approval |
| Cross-runtime continuity | Repository evidence can span runtime-specific session stores; claims require the owner's artifact-specific evidence | Both instruction starters require searching every used runtime store; no private transcript exporter | Sanitized policy |
| Assignment and automation discipline | Shared rules keep the operator's instruction as the assignment, separate engineering validity from user outcome and approval, and require targeted, restored desktop automation | Both instruction starters carry the same three rules; nothing in this reference enforces them mechanically | Sanitized policy |
| Off-machine publication | Claude mechanically denies Artifact and shared rules prohibit unapproved upload paths | Claude examples deny Artifact and both tool policies prohibit unapproved publication | Sanitized adapter |
| Browser automation | Firefox-only dedicated Playwright MCP registration with matching managed browser build | Generic explicit-browser and MCP-owned-install guidance using Firefox as the example | Sanitized adapter |
| Agent status cockpit | Live lifecycle hooks publish a sanitized repository label and state to iTerm2 | Optional non-mutating iTerm2 user-variable publisher; lifecycle wiring remains local | macOS optional adapter |
| macOS management | Homebrew, defaults, Dock, shell, window management, LaunchAgents, themes, privacy, and password-store integration | Lifecycle guidance only; no operating-system mutation command | Design-only by policy |
| Windows and Linux | Not the private controller's host target | The 23-case baseline install-lifecycle acceptance passed natively on Linux and Windows 11 as well as macOS; the four lifecycle cases added on 2026-11-05 have a recorded run on macOS only. Claude Code and Codex hooks were not run inside either agent on Linux or Windows | Baseline natively accepted on all three; lifecycle cases macOS only (see Native acceptance) |
| Workstation diagnostics | Reads real host processes, applications, services, logs, and configuration | No live host diagnostics | Deliberate omission |
| AI configuration deployment | Reconciles a managed-file set plus hybrid settings | No live home-directory deployment | Deliberate omission |
| Secrets and recovery | Encrypted private material and password-store operations exist outside the share boundary | Prohibited by the export manifest and disclosure scanner | Deliberate omission |
| Memories, logs, ledgers, and analytics | Private continuity and observability surfaces | Prohibited; examples use synthetic fixtures | Deliberate omission |
| Spectre and Eidolon | Real project governance and evidence history remain private | Recognizable, sanitized case studies and exercises | Sanitized case study |
| Live user installer | Private scripts target one reviewed workstation | Adoption tool builds a reviewable bundle and installs project-local starters into a named existing project directory (preview-first, non-overwriting, settings merged after backup); it records what it wrote, keeps settings edits made after adoption through re-adoption, update and uninstall, and checks helpers the hooks run that were already present without taking them over; installing into live home or global tool configuration stays deferred | Project-scoped; home install deferred |

## Native acceptance

`scripts/acceptance.py` clones a commit into a directory whose name contains spaces and drives the
public entry points (`tools/bootstrap.py`, `tools/adopt.py`, `tools/pre_push.py`,
`tools/managed_job.py`, the command guard and `tools/test.py`) in synthetic local repositories. An
exit code alone is not the result: each case reads back the files, configuration or commit range
the entry point left. Cases belong to a population, counted separately, so new cases never alter a
recorded result.

| Population | Cases | Commit | macOS | Linux | Windows |
|---|---|---|---|---|---|
| baseline | 23 | `2014391` | 23 of 23 passed | 23 of 23 passed | 23 of 23 passed |
| lifecycle | 4 | `2014391`, before repair | 0 of 4 passed | Not run | Not run |
| lifecycle | 4 | `bcd9309`, after repair | 4 of 4 passed | Not run | Not run |

Runtimes: macOS 26.7.1 on arm64 with Python 3.11.18 and Git 2.56.0; Linux 7.0.0 on x86_64 with
glibc 2.43, Python 3.14.4 and Git 2.53.0; Windows 11 build 26300 natively, not WSL, with Python
3.12.8 and Git 2.47.1. On macOS the baseline also passed 23 of 23 at `bcd9309`, so the repairs
did not regress it there.

The lifecycle population covers four failures found on 2026-11-05: a settings edit lost through
re-adoption and uninstall, push inspection that trusted stale tracking refs after a remote was
repointed, no drift reported for a helper that was already present when adopted, and an inherited
hooks path overridden without warning. Each case carries a control that passed before and after
the repair: direct uninstall, a split fetch and push URL, an unchanged pre-existing helper, and
explicit takeover with uninstall. Linux and Windows results for these four cases are not recorded;
until they are, the repairs are established natively on macOS only.

## Reading the matrix

- **Portable reimplementation** means the repository contains executable code and isolated tests for
  the underlying control pattern.
- **Sanitized adapter** means the repository provides a reviewable starter rather than a copy of live
  configuration.
- **Design-only** means the interface and safety requirements are documented without claiming native
  execution evidence.
- **Deliberate omission** means adding the private capability would violate the teaching or disclosure
  boundary.

The adoption status says how faithfully a row mirrors the private system. It does not say whether
you can run the tool against your own project; that is the use-scope table in `README.md`, which
sorts every tool into run it, copy it, or read it.

Preserve an existing identity and choose additional roles or workflow gates explicitly. Installing
policy is not proof that a live session follows it.

`adopt.py --into <project>` installs project-local starters (agent instructions, a scope guard, and
a merged `.claude/settings.json`) into an existing project directory you name, previewing by default
and never overwriting an existing file. Installing into live home or global tool configuration stays
deferred: that would change `sysops_pub` from a teaching and bundle-building repository into a
workstation configuration product, which requires auto-discovery, ownership, rollback, and a support
contract this reference does not take on.
