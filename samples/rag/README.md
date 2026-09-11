# Retrieval contract example

The private system uses a local FAISS and Ollama pipeline. This reference repository does not bundle
models or indexes. Instead, `tools/search_docs.py` demonstrates the evidence contract over three
synthetic documents:

```sh
python3 tools/search_docs.py "How is desired state verified?" \
  --requirement-id demo-orientation-001
```

This tool retrieves context only. It does not generate an answer, and its receipt does not call a
retrieval hit an answer. The receipt records:

- an explicit `context_found` or `no_context` retrieval outcome;
- the receipt schema and retriever algorithm identity;
- a digest identifying the exact corpus state;
- the selected context document count and character count;
- whether generation ran and whether a generator emitted a not-found marker;
- cited source paths;
- the requirement that caused the query.

`corpus/corpus-policy.json` excludes synthetic evaluation and review reports. Its digest and the
excluded filenames are included in the receipt. This prevents a report from becoming evidence for
its own evaluation while making the exclusion reviewable.

A production embedding pipeline can replace the ranking function while retaining this receipt
shape. Scores should not be compared across different corpus digests or retriever identities.
Changing tokenization, scoring, ordering, or context selection requires a new `retriever_id`.

## Repository-to-index fan-out

One Git repository can own more than one derived index. A post-commit refresh adapter must schedule
all indexes belonging to that repository, not stop after the first match. The synthetic registry in
`indexes.json` gives `sample-project` separate docs and briefs indexes. Preview the refresh plan:

```sh
python3 tools/plan_index_refresh.py sample-project
```

The output must contain both owned indexes and exclude the unrelated repository's index. This tool
only prints a plan. It does not install hooks, run models, or write queue state.
