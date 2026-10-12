# Security

`sysops_pub` is a public reference implementation maintained by one operator. It is unsupported and
carries no compatibility promise; see the support section of `README.md`.

## Reporting

A defect that could disclose private data, weaken a control, or let a demonstration touch a real
home directory is a security report. Open an issue on the repository that names the file and the
behavior without including an exploit, private data, or a path from your own machine. Issues are
the reporting channel. Private vulnerability reporting on GitHub is not enabled at this revision.

## What a report covers

- The disclosure scan, the export manifest and the secret scans: any tracked content or commit
  metadata they should have rejected.
- The sandbox and path guards: any input that lets a tool write outside its declared root.
- The pre-push gate: any way a commit reaches the public history without its own verification.
- The process runner: any way a child outlives the runner behind a success receipt.

## What it does not cover

The behavior of the coding agents themselves, their runtimes, or their models. The harness narrows
an agent's mistakes; it does not resist a hostile model or a user working around a hook. The
boundary is described in `docs/SECURITY_BOUNDARY.md`.
