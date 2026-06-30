# L5 Answer / Verify / Evaluate

Promote the smoke pipeline's cite-or-abstain behavior into the real public API:
`TrustRAG.retrieve()`, `TrustRAG.ask()`, and `TrustRAG.evaluate(csv)`.

This change keeps graph, wiki, streaming, and memory out of the answer path for
0.1.0. Those features land as additional retrieval/context signals later, while
the verifier and `Result` contract stay stable.
