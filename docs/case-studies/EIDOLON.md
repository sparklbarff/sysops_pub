# Eidolon case study: parse structured evidence, not command prose

Eidolon is an audio software project that records test evidence in an append-only ledger.

The ledger producer initially recognized test activity by searching raw command text for runner
names. Monitoring and inspection commands that merely mentioned a runner were therefore recorded as
test evidence. A later executable-hash field also selected the first executable-looking token, which
could hash a utility such as `sed` or `ls` instead of the actual test binary.

This was an evidence-integrity defect, not cosmetic log noise. A monitoring command that printed a
pass-like count could be credited as a test run by a downstream consumer.

The safe repair pattern is:

- parse shell structure sufficiently to identify a runner in command position;
- derive structured `runner` and binary identity fields from that same parse;
- preserve compound commands where a monitoring loop is followed by a real test run;
- make consumers trust structured fields rather than searching free-form prose;
- retain historical ledger rows and add regression fixtures from real false records.

The lesson is to bind evidence to the subject that actually ran. Filtering by the first word or by
substring presence can both create false confidence.
