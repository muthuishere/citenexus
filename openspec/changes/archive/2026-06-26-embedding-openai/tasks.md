## 1. Tests first (red)

- [x] 1.1 `tests/embed/__init__.py` created; `tests/embed/test_client.py`:
      `embed(["a","b"])` returns two dense vectors of the expected dim, in order,
      via an injected fake transport returning canned `{"data":[...]}` JSON.
- [x] 1.2 `tests/embed/test_client.py`: the request body carries `model` + all
      `input` texts (fake transport asserts on the captured body).
- [x] 1.3 `tests/embed/test_client.py`: `embed_query("x")` returns one vector;
      a configured `api_key_env` flows only through the `Authorization` header,
      and with no key configured no `Authorization` header is sent.
- [x] 1.4 `tests/embed/test_batcher.py`: `embed_in_batches` with `batch_size=2`
      over 5 texts makes exactly 3 calls and returns 5 vectors in order.
- [x] 1.5 `tests/embed/test_client.py`: one `@pytest.mark.integration` test hits
      a real `/v1/embeddings` (`CITENEXUS_EMBED_BASE_URL`, default
      `http://localhost:11434/v1`, model `bge-m3`) and SKIPS if unreachable.

## 2. Implement (green)

- [x] 2.1 `src/citenexus/embed/client.py`: `OpenAICompatibleEmbedding(EmbeddingPlugin)`
      with `plugin_version = "openai-embed-v1"`, injected `transport` (default =
      stdlib `urllib.request`), env-var API key in the `Authorization` header,
      `embed` (dense `list[list[float]]`) and `embed_query`.
- [x] 2.2 `src/citenexus/embed/batcher.py`: `embed_in_batches(plugin, texts,
      batch_size=64)` preserving order.
- [x] 2.3 `src/citenexus/embed/__init__.py`: export the public names.

## 3. Verify

- [x] 3.1 `uv run pytest tests/embed -m "not integration" -q` passes.
- [x] 3.2 `uv run ruff check src/citenexus/embed tests/embed` clean;
      `uv run mypy src/citenexus/embed tests/embed` clean.
- [x] 3.3 `npx -y @fission-ai/openspec@latest validate --change embedding-openai`
      passes.
