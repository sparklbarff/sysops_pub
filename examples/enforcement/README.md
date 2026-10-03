# Enforcement example

`scope_guard.py` is a deliberately small block/admit control. It resolves a proposed write path and
allows it only when it remains under the declared project root.

Direct use:

```sh
python3 examples/enforcement/scope_guard.py --root "$PWD" --path "$PWD/README.md"
python3 examples/enforcement/scope_guard.py --root "$PWD" --path /tmp/outside.txt
```

The first command exits 0. The second exits 2. The test suite invokes the executable as a subprocess
for both cases, so the proof covers the real process boundary rather than only its internal
predicate.

This example covers file-path inputs only. It does not claim to parse shell commands or intercept
every write mechanism.

## Advisory grounding classifier

`grounding_classifier.py` is an advisory UserPromptSubmit control, not a block. It recognizes broad,
orientation-style prompts that benefit from one bounded grounding pass over the project's own
documents, and stays silent on narrow file-level work:

```sh
python3 examples/enforcement/grounding_classifier.py "orient me in this codebase"
python3 examples/enforcement/grounding_classifier.py "fix the failing test in test_scheduler.py"
```

The first is flagged for grounding; the second is silent. It classifies the prompt text, not the
work, so a narrow task in broad language is an accepted false positive. That is why it is advisory
and fails open: a spurious flag costs one bounded query that a null result does not block, never a
halted session. The cross-cutting pattern keys on a repo-scale scope noun rather than a bare
preposition, so "across two runs" stays silent while "across the codebase" is flagged. The
`--hook claude` mode emits `additionalContext` for a broad prompt and nothing otherwise, and any
error exits 0 so a session is never blocked.
