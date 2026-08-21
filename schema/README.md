# Why SCAR is a graph, not a vector store

SCAR stores **corrections and the error connections between them**. That is a graph problem. HydraDB OSS (`graph-node` over Bolt `7687` / HTTP `8443`) is the system of record.

A vector index cannot answer:

- What corrections already live on the **callers** of this function? (`CALLS` 1–2 hops)
- Which files **import** a module that already failed with this signature? (`IMPORTS*`)
- We used to say X; now we say Y (`SUPERSEDES` with `active = false` on the old node)
- I have never seen this — **abstain**, do not invent a house rule

Cosine similarity will rank "use datetime.utcnow" next to "never use datetime.utcnow". Those chunks are semantically close and chronologically opposed. The graph keeps one active `Correction` and a `SUPERSEDES` edge to the dead one.

Node labels: `Repo`, `File`, `Symbol`, `Session`, `Turn`, `Error`, `Correction`, `AntiPattern`, `Constraint`. Every node is `MERGE`d on `id`. Relationship types are in `ontology.cypher`. Named operations that write this graph live only in `scar/graph/queries.py`.
