# Retrieval contract example

The private system uses a local FAISS and Ollama pipeline. This reference repository does not bundle
models or indexes. Instead, `tools/search_docs.py` demonstrates the evidence contract over three
synthetic documents:

```sh
python3 tools/search_docs.py "How is desired state verified?" \
  --requirement-id demo-orientation-001
```

The receipt records:

- an explicit `answered` or `not_found` outcome;
- a digest identifying the exact corpus state;
- cited source paths;
- the requirement that caused the query.

A production embedding pipeline can replace the ranking function while retaining this receipt
shape. Scores should not be compared across different corpus digests.
