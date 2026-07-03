# CiteNexus language ports

> One contract, three languages. **Python is the reference implementation**
> ([`../src/citenexus`](../src/citenexus)); ports conform to
> [`../docs/SPEC-PORTS-v1.md`](../docs/SPEC-PORTS-v1.md), not to Python's source.
> The [`../conformance/`](../conformance) fixtures are the real contract — every
> deterministic algorithm (§4) is proven byte-identical by making them pass.

Rust core ([`../core`](../core), `citenexus-core`) is the shared engine for
extraction, Lance store access, and lid.176 detection, exposed over one C ABI
(cgo for Go, napi-rs for TS). See SPEC-PORTS-v1 §3.4 / §9.

## Status — foundation + hermetic guarantee (SPEC-PORTS-v1 §4/§7)

The **deterministic algorithm core** (§4) and the **hermetic cite-or-abstain ask
flow** (§0/§7) are implemented and green against the shared fixtures in both
languages. The guarantee — an answer is emitted only when a retrieved passage is
relevant *and* the generated answer passes the faithfulness gate, else the flow
refuses — is now proven offline in Go and TS, byte-identical to the Python
reference.

| Capability | fixture | Go (`ports/go`) | TypeScript (`ports/ts`) |
|---|---|:--:|:--:|
| Tokenizer | `tokenize.json` | ✅ | ✅ |
| BM25-lite | `bm25.json` | ✅ | ✅ |
| RRF fusion | `rrf.json` | ✅ | ✅ |
| Faithfulness + relevance gate | `faithful.json` | ✅ | ✅ |
| Recursive chunker | `chunker.json` | ✅ | ✅ |
| Evidence-unit ids (block + chunked) | `eu_ids.json` | ✅ | ✅ |
| Answer-language fallback chain | `language.json` | ✅ | ✅ |
| **Hermetic ask (cite-or-abstain)** | `e2e_hermetic.json` | ✅ | ✅ |
| **Result JSON serialization (§7)** | `result_roundtrip.json` | ✅ | ✅ |

The ask flow runs on deterministic fakes (hash embedding + extractive LLM, both
pinned in §4) over an in-memory cosine store — no network, no FFI. A port MUST
NOT ship `ask()` without the faithfulness gate (§1); here it is real control
flow, verified.

**Not yet ported** (tracked, next increments): the Rust-core **FFI bindings**
(cgo / napi-rs) for real Lance + extraction + lid.176 at scale · real **HTTP
model clients** (OpenAI-compatible + Anthropic, injectable transports) ·
S3/Postgres storage · hooks / telemetry / streaming · `evaluate(csv)`.

## Run the conformance suite

```sh
# Go
cd ports/go && go test ./...

# TypeScript
cd ports/ts && npm install && npm test && npm run typecheck
```

CI ([`ports-ci.yml`](../.github/workflows/ports-ci.yml)) runs both on any change
to `ports/**` or `conformance/**`, so a fixture edit breaks any drifting port.

## Layout

```
ports/go   module github.com/muthuishere/citenexus-go — one package per algorithm,
           internal/conform loads ../../conformance fixtures. Stdlib only.
ports/ts   package @citenexus/core (ESM, Node >=20) — one dir per algorithm under
           src/, src/conform/fixtures.ts loads the shared fixtures. Stdlib only.
```

Both are in-repo (monorepo) sharing the fixtures; they split into their own
publishable repos (`citenexus-go`, the `citenexus` npm package) at release time.
