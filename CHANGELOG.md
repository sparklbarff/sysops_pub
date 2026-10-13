# Changelog

## 0.11.3 - 2026-10-13

Repairs for the remaining public findings of the same joint audit, each reproduced first.

- State what the release gate enforces instead of a guarantee it never earned. The README said
  every published commit passed its own suite; one commit, `1541a09`, went out unchecked before
  0.10.1, and the range and memo were not bound to the destination and commit until 0.11.2. It now
  states the per-push policy, the version each part dates from, and the known exception.
- Keep every updater write inside its sandbox. A `receipts` symlink sent the receipt outside, and a
  link planted at the predictable `.state.json.tmp` name was written through. The updater now
  refuses a receipts directory that is a symlink or a file, and any output file that is a symlink,
  before it writes the state, and replaces each file through a uniquely named, exclusively created
  temporary file. Tests cover each refused path with the state and an outside file unchanged, and
  planted temporary links that a legitimate apply must not follow.
- Clean up the owned job when the managed-job runner itself is cancelled. The job runs in its own
  session, so SIGTERM or SIGHUP sent to the runner killed only the runner, left the job running and
  wrote no receipt. The runner now catches both while it waits, terminates its owned group through
  the timeout path, records the receipt as interrupted and exits 128 plus the signal number. A test
  signals the real runner process and requires the receipt, the exit code, the job's child gone and
  an unrelated process untouched; the previous runner dies on the signal.
- Keep a preservation failure on record, and make the updater's check observational. A collateral
  write to an unselected item failed verification, but only the selected items were recorded, at
  versions that were correct, so the record cleared at once and the next check passed. A failed
  verification now records every item whose persisted version differs from the expected one, at the
  expected version. Separately, check rewrote `unresolved.json` despite its check-without-writing
  contract; it now reports a satisfied entry and leaves the record for the next apply. Tests run the
  collateral failure through a later check, a repair and an apply, and require check to leave the
  record's bytes and timestamp unchanged; the previous updater fails each.
- Judge an external corpus against its own files. The evaluator resolved each cited path against
  this repository first and fell back to the corpus only when no such repository file existed, so
  an external corpus's `README.md` was judged as this repository's `README.md`. Citations now
  resolve against the base the retriever used, and one that resolves outside the evaluated corpus
  is an error. A test with a colliding `README.md` gets both verdicts right; the previous evaluator
  inverts both.
- Repair what an audit of the live manual found. All fifteen manual pages had no top-level heading;
  the running head's first label is now the page's one `h1`, styled as before, and the build test
  requires exactly one on every page. Wrapped inline code was painted as one box sliced across
  lines, which pushed the second fragment's box past the column's left edge; each line now gets its
  own box, and the short tokens in notes no longer split at a slash. Manual-page examples taken
  from PowerShell blocks now carry the documents' "Windows, untested" label instead of reading as
  tested commands. The disclosure rating names the history it now covers. The audit also confirmed
  every page and asset returns 200, every external link resolves, the security headers are intact,
  no disclosure pattern appears in served pages, and every text color pair meets WCAG AA in both
  themes.

## 0.11.2 - 2026-10-13

Three identity defects in the release gate, found in a joint audit and reproduced before repair.
Each new test fails on the previous code.

- Verify every commit the push destination does not have. The driver excluded every
  remote-tracking ref, and the hook never passed Git's destination, so a commit some other remote
  already had was never verified on its way to this one. The hook now passes the destination's name
  and location, the driver refuses to run without them, and only the destination's own
  remote-tracking refs and the ref's current value bound the range; a push to a bare location
  excludes only the ref's value.
- Key the verified-gate memo by the subject the gate judged. 0.11.0 keyed it by tree, so a
  different commit with the same files, an amended author for instance, reused a pass from a gate
  that reads commit identity and history. The memo is now keyed by commit identity. A gate that
  reads only the files may declare `memo = "tree"` and is still reused across commits with
  identical files; a gate that receives `{commit}` cannot declare it, and an unknown scope refuses
  the push. The memo file is renamed, so entries keyed the old way are no longer consulted.
- Scan the text a merge adds. The history scan read no merge diffs, so text added only in a merge
  commit and removed later was never seen, and the scanner's own description said otherwise. It
  now reads merges as combined diffs and reports only lines present in no parent, under the merge;
  lines a parent carried stay reported under the commit that added them, not twice.

## 0.11.1 - 2026-10-12

- Name GitHub's private vulnerability reporting as the security channel in `SECURITY.md`, now that
  it is enabled on the repository. An ordinary issue remains fine for a defect that discloses
  nothing.

## 0.11.0 - 2026-10-12

- Make the pre-push gate adoptable and cheaper to retry. The driver demanded this repository's own
  verifier at a fixed path inside every outgoing commit. It now runs the command the commit's own
  `pyproject.toml` declares under `[tool.sysops_pub.gate]`, with `{commit}` replaced by the
  commit's identity, and falls back to this repository's verifier when nothing is declared; a
  declared command that is missing or malformed refuses the push. Bootstrap reads the tools the
  declared gate needs from the same table. A tree this clone has already verified with the same
  command is not verified again, so a push retried after a failure re-runs only the commits that
  changed; the memo lives untracked inside the Git directory, records the tree and the command but
  not the tools' versions, and can be deleted to force a full run. This repository declares its own
  gate explicitly, and tests cover a declared gate that passes and fails from its own tree, a
  missing command, a malformed declaration, and the memo.
- Wire the guards for Codex. Codex documents hooks that can block, so the scope guard gains a
  Codex mode that reads every file an `apply_patch` payload names from the patch header and
  requires all of them to stay under the session's working directory, and a project hooks file
  wires it on `apply_patch` and the command guard on `Bash`, resolving the guard's path from the
  Git root. The adoption tool places the hooks file and the guards for Codex projects, once when
  both tools are selected. A test runs the adopted commands through a real shell. Trust stays the
  human's: the notes record that Codex keys hook trust to a handler's position as well as its hash,
  so a handler inserted ahead of a trusted one silently stops every shifted handler, and the rule is
  to append, re-trust after every change, and never let an installer write trust entries.
- Add a command guard and a read guard, and wire both in the Claude Code settings starters beside
  the scope guard. The command guard judges a Bash command or a WebFetch URL by parsed structure
  and blocks five classes: credential reads including the keychain, credential and configuration
  writes including a new remote, recursive deletes and pipe-to-shell and decoded-eval commands and
  raw device writes, a pipe after `git push` that would mask its exit status, and fetches of
  private or local addresses. The read guard records every read and write per session, blocks an
  Edit of a file not read this session or changed on disk since, and blocks a shell command that
  names a path with a pending stale block until the file is read again. Both fail closed on
  malformed input, run on Codex payloads of the same shape, and ship with block-and-admit tests at
  the process boundary; the wiring test runs the adopted settings' commands end to end. The
  adoption tool installs both guards, and the export manifest records them as reimplementations.
- Keep the managed-job ownership probe in-process. It listed the process group through ps, and a
  sandboxed runtime that refuses to spawn setuid executables made that probe report unknown
  ownership, and so exit 125, on every job, success included. The probe is now a null signal to
  the owned group, with a short settle window for children a dead leader left as zombies. A test
  refuses the subprocess the old probe needed and expects a clean verdict.
- Scan history content, not only the current tree. The disclosure scan now matches every line any
  reachable commit added against its identifier patterns, so an identifier that one commit added
  and a later commit removed still fails the gate; before, only the current tree's content and the
  history's author and committer identities were checked, and a published-then-removed line was
  never seen. One hit per commit, path and label; suppressed only by a `history_findings` entry
  naming the full commit, and a stale entry fails. A test shows the previous scanner reporting
  clean on exactly that history.
- Say who the repository is for and what each tool is for. The README names its reader, one
  operator running several agents on one machine, and sorts every tool into run it, copy it, or
  read it. The security boundary gains a threat model, an agent's mistakes rather than a hostile
  model, and an operating scope, one operator and one machine. A support statement and
  `SECURITY.md` say the repository is unsupported and how to report a defect. Both instruction
  starters end with their enforcement classes: hook-gated or sandbox-gated, audited, and
  instruction-only.
- Narrow the platform claim to what is evidenced. macOS is the only platform with a recorded run;
  Linux and Windows are untested, and the Windows settings example is an untested design sketch.
- Carry three operating lessons into the design-only sections without figures: charge measured
  use rather than declarations and batch benchmarks; a new interpreter is a migration, not an
  update; tolerate an application-written configuration entry only while it stays disabled. The
  architecture chapter adds the authority rule, that a peer's request is a work order against the
  operator's machine, learned from an audit loop between agents. The Codex integration notes
  record that its hooks can block and that hook trust is positional and the human's to grant.

## 0.10.1 - 2026-10-10

- Fix the pre-push gate to verify every commit a push publishes, not only the tip of each ref. It
  read one object ID per ref record, so the 0.10.0 push of two commits verified only its tip,
  6b61b1b, and published 1541a09 without its own check. A problem in an intermediate commit that a
  later commit fixed would reach public history the same way. The range is now each pushed object
  minus the remote ref's current value and every remote-tracking ref, verified oldest first; a
  remote value this clone has not fetched refuses the push. A test with a failing commit under a
  passing tip fails on the old gate.

## 0.10.0 - 2026-10-10

- The synthetic updater keeps a failed update in `unresolved.json` and re-checks it on every later
  check or apply, exiting 1 while any entry is unmet, so a run that changes nothing cannot hide an
  earlier failure. An entry clears at its recorded target or the catalog's current version, which
  supersedes an older target. Receipts move to schema 3 and carry the remaining record.
- Add `tools/calibrate_check.py` and `samples/calibration/`: prove that a checker rejects a preserved
  known failure with its declared exit code and diagnostic and accepts a valid case and an allowed
  variation. Inputs and checker are fingerprinted; a run that changes them stops calibration.
  Tests show a claim-trusting checker, a syntax error, an input-changing checker and a hang all
  fail. The result covers the declared cases only and is not approval.
- Both instruction starters add an assignment-and-acceptance section: preserve the user's actual
  assignment and acceptance requirements, keep engineering validity, user outcome and approval
  separate, calibrate repaired checks, and target and restore desktop automation.
- Operations, quickstart, capability matrix, export manifest and parity record cover the above.

## 0.9.0 - 2026-10-09

- Project adoption rejects symlinked roots, destination parents and settings-backup paths before
  placing any starter. Synthetic fixtures preserve both the named project and the outside directory.

- Repair the synthetic updater's verification: reopen persisted state, compare it with the complete
  expected result, and reject dropped writes or collateral changes outside the selected channel.
  Version-2 receipts distinguish observed and expected state and retain failed verification.
- Repair POSIX managed-job ownership after the leading process exits. Surviving children are cleaned
  up and produce exit 125. Timeout cleanup handles a child that ignores termination without touching
  an unrelated process. Reject nonfinite timeouts and record terminal group evidence in version-2
  receipts. Windows remains leading-process-only; escaped sessions are not confined.
- Add operations guidance for passive shared-runtime reconciliation, resource-budgeted validation,
  scheduled-job accounting, cross-runtime continuity, explicit role choices and scoped recovery.
  The local manual includes it as chapter 9. These host adapters are design-only, not new queue
  or daemon implementations.
- Update both instruction starters for cross-runtime evidence, owned-process cleanup and concise
  outcome-first output. Codex's example hides reasoning events and opts out of analytics without
  changing model effort or answer verbosity.

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
