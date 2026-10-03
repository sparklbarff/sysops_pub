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

## Retrieval evaluation

Retrieval quality is measured, not assumed. `tools/eval_retrieval.py` scores a frozen question set
(`eval-questions.json`) over the synthetic corpus, reusing the same `search_docs` retrieval path
rather than a second retriever:

```sh
python3 tools/eval_retrieval.py
```

The discipline it demonstrates:

- Judge the context, not the filename, and judge it by hand. A question is a hit only if its answer
  appears in the text the retrieval surfaced; retrieving a topically named document whose shown
  window omits the answer is a miss. In the real system a person makes that call, because a
  relevance score or a keyword match cannot tell an answer from a mere mention. The answer token in
  `eval-questions.json` is that human verdict frozen so the demo runs reproducibly, not a claim the
  verdict can be automated.
- Three cohorts, scored differently. `curated-in-corpus` answers genuinely live in the corpus, so a
  miss is a real recall failure and these are the primary metric. `coverage-gap` answers live only
  outside the indexed surface, so a miss is a coverage limitation tracked off the headline rather
  than a retrieval failure. `absent-control` answers are nowhere, so any retrieval is a false
  positive.
- Bind the verdicts to the retriever identity. The set records the `retriever_id` it was judged
  against; changing tokenization, scoring, ordering, or context selection bumps that id, and the
  tool refuses to trust stale verdicts until the set is re-judged. This is the same reason scores
  are never compared across corpus digests.

Measure before adopting a retrieval change: run the frozen set on the current retriever, change one
variable, re-run, and keep the change only if the primary cohort improves with no regression and the
controls stay rejected.
