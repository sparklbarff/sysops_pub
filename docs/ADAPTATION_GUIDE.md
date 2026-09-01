# Adaptation guide

Start by running the sandbox demo unchanged. Then adapt one component at a time.

## Add a component

1. Create a directory under `components/<name>/desired/`.
2. Put only non-secret desired files in it.
3. Add a registry entry with a relative source and destination.
4. Enable it in a profile.
5. Run `plan` and confirm the destination is correct.
6. Add a test that proves missing, matching, and drifted states.

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
