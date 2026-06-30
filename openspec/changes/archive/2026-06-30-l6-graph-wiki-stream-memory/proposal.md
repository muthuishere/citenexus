# L6 Graph / Wiki / Streaming / Memory

Add the first concrete breadth layer after L5:

- graph artifact store + `GraphRetriever`
- wiki/navigation page store + `WikiRetriever`
- partition-scoped conversation memory used as retrieval context
- verified answer streaming

Graph and wiki are navigation signals only; they resolve down to Evidence Units
before fusion and citation. Memory is context, not evidence. Streaming wraps the
same verified `Result` path used by `ask()`.
