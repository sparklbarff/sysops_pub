# Changelog

## 0.8.0 - 2026-10-03

- Add `tools/build_site.py` and `site/`: a static reference-manual website generated from the
  tracked documents with no third-party packages. Each document is a numbered chapter, the
  changelog and license are appendices, and every tool gets a manual page generated from its own
  argument parser and docstring, so the site cannot drift from the code. The two ASCII diagrams are
  redrawn as block diagrams bound to their exact source text; a changed diagram fails the build.
- The build is reproducible from a commit and writes to the ignored `_site/`. `--draft` allows
  uncommitted changes and marks every page; `--release` runs the release gate first and needs a
  pushed HEAD. The front page's absolute maximum ratings print only when that gate passed.
- Light and dark modes follow the system setting, with a header switch as the site's only script.
  The Chivo and Inconsolata subsets ship under the SIL Open Font License and are hash-bound in the
  disclosure allowlist. The Spectre and Eidolon case studies stay in the repository and are not
  published on the site.
- Navigation is a thumb index of chapter tabs on the page edge. The front page adds a data-sheet
  pin configuration (the manual as a 32-pin package, each pin a link), a package marking that
  prints the part number, date code, and the full commit as a 160-bit field, and a colophon. An
  Errata sheet is generated from every tool option that ships without help text, and an optional
  `site/eggs.js` adds a keyboard reference behind `?`.
- Give every option, argument, and subcommand of the eight argparse tools help text, and add a test
  that fails if any parser action ships without it. Help strings only; no behaviour change. The
  generated manual pages no longer have blank entries, and the Errata sheet is empty.
- Demonstrate the commands on the site: the build clones the commit into a temporary directory,
  really runs each tool's session there (control loop, adoption, bootstrap, supervised update,
  managed job, retrieval, evaluation, case exercises, and the tour), and prints the unedited output
  on its manual page. Absolute paths are replaced with `/tmp/session`, and a session that would
  publish anything the disclosure scan forbids fails the build. Release builds also show the
  release gate's own verdict lines on `verify_release(1)`.
- Make every page fit a phone: wrapped listings, narrow manual synopses, stacked data-sheet
  tables, a wrapping thumb index, and a pin description table in place of the pinout drawing.
- Name the local retrieval engine (FAISS and Ollama) on the front page as deliberately not
  bundled.

## 0.7.0 - 2026-10-02

- Add `adopt.py --into <project>`: a project-local installer alongside the existing `--target`
  bundle builder. It places the project-relative starters (agent instructions, a scope guard, and
  `.claude/settings.json`) into an existing project directory you name, previews by default, never
  overwrites an existing file, and merges `.claude/settings.json` additively after writing a
  `.sysops-pub.bak` backup. The merge unions permission lists and appends unseen hook entries without
  removing anything, so a second run reports no change.
- Move the capability-matrix "live user installer" boundary accordingly: installing project-local
  starters into a named project directory now ships; installing into live home or global tool
  configuration stays deferred, because that would need auto-discovery, ownership, rollback, and a
  support contract this teaching reference does not take on.

## 0.6.3 - 2026-10-02

- Add an MIT LICENSE. Without it the public repository defaulted to all-rights-reserved, which
  contradicted its teaching-and-adoption purpose: an adopter had no legal right to reuse the code
  the repo exists to be adopted from.
- Add `docs/PARITY.md`, a parity-state ledger recording the last audit date, the private reference
  point it was verified against, and the cadence and change-driven triggers for the next re-audit.

## 0.6.2 - 2026-10-02

- Frame the retrieval-evaluation verdict honestly: the answer token is a frozen human judgment and
  the token-in-context check is a reproducible stand-in, not a claim the verdict can be automated.
- Document the grounding classifier as a demo-only illustration rather than an adoption starter: it
  presupposes a local retrieval backend the reference repository does not ship, so `adopt.py` omits
  it by design.

## 0.6.1 - 2026-10-02

- Add an advisory grounding classifier example: a fail-open UserPromptSubmit control that flags
  broad, orientation-style prompts for one bounded grounding pass and stays silent on narrow work,
  keying the cross-cutting pattern on a repo-scale scope noun rather than a bare preposition. CLI
  and Claude hook modes, proven at the process boundary including fail-open on malformed input.

## 0.6.0 - 2026-10-02

- Add a retrieval-evaluation reference: a frozen cohort question set (curated-in-corpus,
  coverage-gap, absent-control) scored by reusing the `search_docs` retrieval path, with verdicts
  judged against the retrieved context and bound to the retriever id.
- Filter stopwords before ranking so a control query is not answered on function-word overlap. This
  tokenization change bumps the retriever id to `token-overlap-set-v2`, demonstrating the
  re-judge-on-identity-change contract against the shipped evaluation set.
- Record the retrieval-evaluation capability in the matrix and drop a hardcoded private file count.

## 0.5.0 - 2026-09-11

- Deny Claude's Artifact tool in both starter settings and carry a broader no-publication rule in
  both agent instruction examples.
- Add a synthetic supervised updater with check-only default, exact-channel apply, running-item
  deferral, post-update verification, and receipts.
- Add a foreground managed-job runner with owned timeout cleanup and sanitized receipts.
- Stop describing retrieved context as an answer; record context size, generation state, policy
  identity, and self-evaluation exclusions.
- Document the Codex structured-input fallback and explicit dedicated-browser Playwright setup.
- Add an optional non-mutating iTerm2 status publisher while leaving native Windows and Linux proof
  explicitly open.

## 0.4.1 - 2026-09-03

- Add a documented Codex named-profile example using the supported separate profile-file layout.
- Add a synthetic repository-to-index fan-out planner and prove that every owned index is selected.
- Keep both additions inside the existing clean-room and dependency-free boundaries.

## 0.4.0 - 2026-09-01

- Verify exact outgoing commit objects in detached worktrees before push.
- Prove that the tracked pre-push launcher reaches the outgoing-commit driver.
- Bind deliberate omission-name fixtures to exact paths, hashes, and review reasons.
- Audit commit identities while explicitly permitting GitHub noreply provenance and signatures.
- Catch serialized Windows user paths and broader operational-artifact filenames.
- Use shell-independent Claude Code hook arguments and fail closed on path-resolution errors.
- Reject declared source-root symlinks and normalize controller filesystem errors.
- Version retrieval receipts and require non-blank requirement identities.
- Record native versus design-level compatibility and preflight mandatory release tools.

## Internal snapshot 0.3.0 - 2026-09-01

- Make the tracked local pre-push release gate mandatory after clone bootstrap.
- Scan current files and Git history for secrets and reject unlisted non-UTF-8 artifacts.
- Add hash-bound binary exceptions while keeping the default release surface text-only.
- Prove the adopted Claude Code settings execute the real block/admit hook path.
- Enforce component platform metadata, unambiguous destination ownership, and unsafe dry-run errors.
- Build adoption bundles atomically and verify each copied file by SHA-256.
- Require retrieval receipts to identify the requirement that caused the query.

## Internal snapshot 0.2.0 - 2026-09-01

- Reject malformed, empty, and zero-file desired-state profiles.
- Report unmanaged files without deleting them.
- Fail closed on malformed or pathless Claude Code hook input and test the real stdin adapter.
- Add Python-native Windows, macOS, and Linux tour and adoption commands.
- Add runnable synthetic Spectre and Eidolon governance exercises.
- Expand tracked-file disclosure checks and add a complete local release verifier.

## Internal snapshot 0.1.0 - 2026-09-01

- Initial private clean-room teaching repository.
