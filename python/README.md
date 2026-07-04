# CiteNexus

> Multilingual RAG that answers only when the evidence is strong.

Evidence-first, multilingual, S3-native RAG for domains where a wrong answer is
worse than no answer (legal, medical, finance/compliance, enterprise search).
CiteNexus answers **only** from retrieved evidence — every claim is grounded in a
bbox-cited source passage, and it refuses or states uncertainty when evidence is
weak, missing, or conflicting. The guarantee is **"no ungrounded claim,"** not
"zero hallucination."

The library bundles **no models** — embedding, LLM, reranker, and vision are
injected endpoints. CiteNexus owns orchestration, storage, retrieval, fusion,
grounding, and evaluation.

**CiteNexus supports pluggable vector databases.** Storage is two protocols —
`VectorStore` (dense) and `TextSearch` (lexical) — and each backend is a named
(vector, text) pair:

| Backend | Vector | Text | When |
|---|---|---|---|
| **Lance** (recommended) | `LanceVectorStore` | `LanceTextSearch` (BM25-lite) | Zero infra, S3-native: point at a bucket and go |
| **Postgres** | `PostgresVectorStore` (pgvector) | `PostgresTextSearch` (native `tsvector`) | You already run Postgres — `pip install 'citenexus[postgres]'`, set `vector_store.backend: "postgres"` |
| **Yours** | implement `VectorStore` | implement `TextSearch` | Qdrant, Weaviate, Elasticsearch, Tantivy, … |

The seams are independent: mix LanceDB vectors with an Elasticsearch
`text_search=`, or let one Postgres serve both.

```python
from citenexus import CiteNexus, S3

rag = CiteNexus(
    S3(bucket="my-bucket"),
    embedder=my_embedding_endpoint,
    generator=my_llm_endpoint,
)
rag.ingest("policy.pdf")                         # any supported input type
answer = rag.ask("Can the employee disclose this information?")
print(answer)                                    # grounded answer; .sources are bbox-cited
```

See the workspace root README for the full polyglot (python/ golang/ js/ rust/) layout.
