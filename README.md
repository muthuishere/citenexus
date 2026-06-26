# TrustRAG

> Multilingual RAG that answers only when the evidence is strong.

Evidence-first, multilingual, S3-native RAG for domains where a wrong answer is
worse than no answer (legal, medical, finance/compliance, enterprise search).
TrustRAG answers **only** from retrieved evidence — every claim is grounded in a
bbox-cited source passage, and it refuses or states uncertainty when evidence is
weak, missing, or conflicting. The guarantee is **"no ungrounded claim,"** not
"zero hallucination."

The library bundles **no models** — embedding, LLM, reranker, and vision are
injected endpoints. TrustRAG owns orchestration, storage, retrieval, fusion,
grounding, and evaluation.

```python
from trustrag import TrustRAG

rag = TrustRAG("s3://my-bucket")                 # sensible defaults, all signals on
rag.ingest()                                     # any input type; sync or async
answer = rag.ask("Can the employee disclose this information?")
print(answer)                                    # grounded answer; .sources are bbox-cited
```

## Status

Early development, built layer-by-layer (foundation-first) and spec-driven via
**OpenSpec**. See [`CLAUDE.md`](CLAUDE.md) for the build plan and conventions,
and [`docs/SPEC-v6.md`](docs/SPEC-v6.md) for the full specification.

## Develop

```bash
task setup            # uv sync
task check            # lint + typecheck + unit tests (the CI gate)
task test             # hermetic unit suite (fakes only)

task local:minio:up   # start local S3 (MinIO) + auto-create the bucket
task local:minio:down # stop it (keep data);  local:minio:reset wipes the volume
task local:example    # end-to-end demo over MinIO + local Ollama
```

Unit tests are hermetic (fakes only) and need nothing running. The S3-native
storage layer, the opt-in integration tests, and the example talk to a local
**MinIO** (`compose.yaml`) — S3 API on `:19000`, console on `:19001`
(`minioadmin`/`minioadmin`), bucket `trustrag-local`. Copy `.env.example` to
`.env` to override defaults.

## License

Apache-2.0
