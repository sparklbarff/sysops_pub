# Security

`sysops_pub` is a public reference implementation maintained by one operator. It is unsupported and
carries no compatibility promise; see the support section of `README.md`.

## Reporting

A defect that could disclose private data, weaken a control, or let a demonstration touch a real
home directory is a security report. Report it privately through the repository's security
advisory form on GitHub, which private vulnerability reporting enables, naming the file and the
behavior. Keep private data and paths from your own machine out of the report. An ordinary issue
is fine for a defect that discloses nothing.

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
