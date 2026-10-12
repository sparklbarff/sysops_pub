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
every write mechanism. The two guards below cover the shell and the freshness of what is edited.

## Command guard

`command_guard.py` judges a Bash command or a WebFetch URL by parsed structure before it runs. It
tokenizes the command with the standard shell lexer, splits it into simple commands at pipes and
list operators, looks through wrappers such as `sudo`, `env` and `nohup` and through leading
variable assignments for the word in command position, and blocks five classes:

| Class | Blocked | Admitted |
|---|---|---|
| credential read | a command naming a key directory, a credentials file, a password store, the keychain's read subcommands, a password-store `show`, or a `gpg --decrypt` | `cat README.md`, `security list-keychains`, `pass ls` |
| credential write | a redirection, `tee`, `cp`, `mv`, `install` or `sed -i` aimed at an environment file, a credentials file, a key directory or the repository's own configuration; `git remote add` or `set-url` | `echo x > notes.txt`, `git remote -v`, `git config --local core.hooksPath .githooks` |
| dangerous command | a recursive `rm`, a fork bomb, a download piped into a shell, a decoded payload piped into an interpreter or `eval`, and `dd`, `mkfs`, `diskutil` or a redirection aimed at a raw device | `rm build/output.txt`, `find build -mindepth 1 -delete`, `curl ... -o file` |
| masked push | `git push` followed by a pipe, whose exit status the last stage would replace | `git push origin main`, `git push origin main && echo done` |
| private address | a WebFetch of localhost, a loopback, private, link-local, unspecified or reserved address, or a `.local`, `.localhost` or `.internal` name | any public name or address |

Direct use:

```sh
python3 examples/enforcement/command_guard.py --command "rm -rf build"
python3 examples/enforcement/command_guard.py --command "find build -mindepth 1 -delete"
python3 examples/enforcement/command_guard.py --url "http://localhost:8080/"
```

The first and third exit 2; the second exits 0. `--json` prints the decision and every finding.
`--claude-hook` and `--codex-hook` read a PreToolUse payload from stdin and judge `Bash` by its
command and `WebFetch` by its URL; any other tool is admitted with a note, because the guard has
no opinion on it. Malformed input and a command the lexer cannot parse are blocked, never guessed
at.

What it does not see: a command inside a command substitution or backticks, a string handed to an
interpreter, a script invoked by path, and a local-address request made with `curl` rather than
WebFetch, which stays admitted so local model servers remain reachable. The classes come from the
private system's guard and the incidents behind it; the lesson from the Eidolon case study applies,
so nothing here matches a substring of the command text except the fork bomb.

## Read guard

`read_guard.py` blocks an edit of a file this session has not read, or that changed on disk since
it was read. It has three modes, each wired to one hook event:

- `record`, on `PostToolUse` for `Read`, `Write`, `Edit` and `NotebookEdit`: remember the file's
  content hash for this session.
- `check`, on `PreToolUse` for `Edit` and `NotebookEdit`: require a record and an unchanged hash.
  A changed file leaves a pending stale block on its path.
- `shell`, on `PreToolUse` for `Bash`: block a command that names a path with a pending stale block,
  so the blocked edit cannot be routed through the shell. A fresh read clears it.

`Write` is exempt: it supplies the whole content. A windowed read counts as a read; what the window
covered is the agent's responsibility. State is one JSON file per session under the directory named
by `SYSOPS_PUB_GUARD_STATE`, or the system temporary directory, never inside the project. The
session comes from the hook payload, so two sessions never share reads.

```sh
python3 examples/enforcement/read_guard.py record --session demo --path README.md
python3 examples/enforcement/read_guard.py check --session demo --path README.md
```

The test suite runs every mode as a process with real payloads, and the Claude Code wiring test runs
the adopted settings' commands end to end: an unread edit blocked, a read, the edit admitted, a
change on disk, the edit blocked again, the shell route blocked, a second read, both admitted.

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

Adopt it only with a grounding backend. Unlike `scope_guard.py`, a self-contained path check you can
wire as-is, this classifier only earns its keep when the project has a local retrieval backend to
ground against. This reference repository ships a synthetic retrieval demo, not a runnable index, so
`tools/adopt.py` deliberately does not bundle the classifier into a starter: wiring it without a
grounding backend would inject advice pointing at a capability that is not there. Treat it as an
illustration of the selective-grounding concept, and adopt it only alongside a real grounding
system.
