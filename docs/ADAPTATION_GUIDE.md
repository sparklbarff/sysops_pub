# Adaptation guide

Start by running the sandbox demo unchanged. Then adapt one component at a time.

Use `tools/adopt.py --target` to create a reviewable starter bundle outside this repository. It
previews by default, requires `--execute` to copy, requires a new target path, verifies copied
hashes in a temporary sibling, and atomically publishes the completed bundle.

To install straight into a project you are adopting into, use `tools/adopt.py --into <project>`. It
names the project-relative destinations (agent instructions, a scope guard, and
`.claude/settings.json`), previews by default, requires `--execute` to write, never overwrites an
existing file, and merges `.claude/settings.json` additively after writing a `.sysops-pub.bak`
backup. It installs project-local files into the directory you name; it does not touch live home or
global Claude Code or Codex configuration.

## Add a component

1. Create a directory under `components/<name>/desired/`.
2. Put only non-secret desired files in it.
3. Add a registry entry with a relative source and destination. Declare `platforms` as `any`,
   `windows`, `macos`, or `linux`; the controller rejects unsupported hosts and overlapping enabled
   destination roots.
4. Enable it in a profile.
5. Run `plan` and confirm the destination is correct.
6. Add a test that proves missing, matching, and drifted states.
7. Confirm the status report identifies unmanaged files without deleting them.

The reference controller manages files only. Real package managers, macOS defaults, services, and
credential systems need dedicated adapters and stronger recovery plans.

## Adopt agent policy

Keep global instructions short. Put project-specific identity and workflow rules in the project
repository. Both Claude Code and Codex should defer to the nearest project instructions.

Use the same policy concepts across tools, but do not pretend their enforcement mechanisms are
identical. Claude Code can run lifecycle hooks. Codex should use its native filesystem sandbox,
approval controls, repository instructions, and Git gates.

## Adopt retrieval

Treat retrieval as orientation, not authority. Verify exact claims in current source and tests.
Record whether a query answered, which corpus state produced it, and which requirement caused the
query. Do not infer compliance from a session identifier alone.
