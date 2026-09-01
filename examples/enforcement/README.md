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
