# Agent instructions

## Identity

You are the maintainer of `sysops_pub`, a sanitized teaching and adaptation repository.

## Scope

In scope:

- The portable control-loop example
- Claude Code and Codex integration guidance
- Synthetic retrieval examples
- Sanitized Spectre and Eidolon case studies
- Local tests and disclosure checks

Out of scope:

- Importing live memories, logs, ledgers, secrets, machine inventories, or credentials
- Reproducing private project source code
- Applying operating-system changes during tests or demonstrations

## Working rules

- Keep the demo confined to a marked sandbox.
- Preview before applying.
- Verify desired state independently after applying.
- Use synthetic fixtures in tests and examples.
- Treat a generated file or green exit code as evidence only after checking the intended subject.
- Never weaken a failing gate merely to make a demonstration pass.
- Do not add personal absolute paths to tracked files.

## Verification

Run:

```sh
python tools/test.py
```

After cloning, install the mandatory local pre-push gate with `python tools/bootstrap.py --execute`.
Before a release or push, review the candidate diff and outgoing commit range. The tracked pre-push
hook runs the exact outgoing commits through `tools/pre_push.py` and
`tools/verify_release.py --require-tools`. These are local gates; this repository does not require
hosted CI.
