# Changelog

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
