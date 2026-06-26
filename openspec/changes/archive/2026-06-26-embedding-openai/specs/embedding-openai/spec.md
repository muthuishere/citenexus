## ADDED Requirements

### Requirement: OpenAI-compatible dense embedding plugin

The library SHALL provide `OpenAICompatibleEmbedding`, a concrete
`EmbeddingPlugin` that embeds texts by calling `POST {base_url}/embeddings` with
a JSON body `{"model": <model>, "input": [<texts...>]}` and parsing the response
`data[].embedding` into dense vectors (`list[list[float]]`), preserving the input
order. It SHALL carry `plugin_version = "openai-embed-v1"`.

#### Scenario: Embed returns one dense vector per input in order

- **WHEN** `embed(["a", "b"])` is called against an endpoint that returns two
  embeddings
- **THEN** the result is a list of two dense `list[float]` vectors of the
  endpoint's dimension, in the same order as the inputs

#### Scenario: Request body carries the model and every input text

- **WHEN** `embed(["a", "b"])` is called
- **THEN** the JSON body sent to `{base_url}/embeddings` has `model` equal to the
  configured model and `input` equal to `["a", "b"]`

### Requirement: Injected transport keeps unit tests hermetic

The plugin SHALL perform its HTTP request through an injected
`transport: Callable[[str, bytes, dict[str, str]], bytes]` (url, json body,
headers → response bytes). When no transport is supplied, the DEFAULT transport
SHALL use the Python standard library (`urllib.request`) and add no third-party
dependency.

#### Scenario: A fake transport replaces the network

- **WHEN** the plugin is constructed with a fake transport returning canned
  `{"data": [{"embedding": [...]}]}` bytes
- **THEN** `embed(...)` parses that canned response and performs no network IO

### Requirement: API key read from env var, never logged

When an `api_key_env` is configured, the plugin SHALL read the key from that
named environment variable at call time and pass it ONLY in the `Authorization`
header given to the transport. The key value SHALL NOT be hardcoded, logged, or
stored on the instance. When no `api_key_env` is configured (or the variable is
unset), the request SHALL be sent without an `Authorization` header.

#### Scenario: Configured key flows only through the Authorization header

- **WHEN** `api_key_env="TRUSTRAG_EMBED_API_KEY"` is configured, that variable is
  set, and `embed(...)` is called
- **THEN** the headers passed to the transport include
  `Authorization: Bearer <value>` and the key value appears nowhere else

#### Scenario: No key configured sends no Authorization header

- **WHEN** no `api_key_env` is configured and `embed(...)` is called
- **THEN** the headers passed to the transport contain no `Authorization` key

### Requirement: Single-text convenience matching the Embedder protocol

The plugin SHALL expose `embed_query(text: str) -> list[float]` returning the one
dense vector for a single text, matching the ingest `Embedder` protocol.

#### Scenario: embed_query returns one vector

- **WHEN** `embed_query("x")` is called
- **THEN** the result is a single dense `list[float]` vector

### Requirement: Order-preserving batching helper

The library SHALL provide `embed_in_batches(plugin, texts, batch_size=64)` that
splits `texts` into consecutive batches of at most `batch_size`, calls the
plugin once per batch, and concatenates the results so the output order matches
the input order. The default batch size SHALL be 64.

#### Scenario: Long sequence is split into ordered batches

- **WHEN** `embed_in_batches(plugin, [t0..t4], batch_size=2)` is called over five
  texts
- **THEN** the plugin is called exactly three times (sizes 2, 2, 1) and the
  returned five vectors are in the original input order
