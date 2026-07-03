# CiteNexus language ports

> One contract, three languages. **Python is the reference implementation**
> ([`../src/citenexus`](../src/citenexus)); ports conform to
> [`../docs/SPEC-PORTS-v1.md`](../docs/SPEC-PORTS-v1.md), not to Python's source.
> The [`../conformance/`](../conformance) fixtures are the real contract — every
> deterministic algorithm (§4) is proven byte-identical by making them pass.

Rust core ([`../core`](../core), `citenexus-core`) is the shared engine for
extraction, Lance store access, and lid.176 detection, exposed over one C ABI
(cgo for Go, napi-rs for TS). See SPEC-PORTS-v1 §3.4 / §9.

## Status — foundation slice (SPEC-PORTS-v1 §4)

The **deterministic algorithm core** is implemented and green against the shared
fixtures in both languages. This is the load-bearing base every T1 capability
(ingest / retrieve / ask / evaluate) sits on.

| §4 algorithm | fixture | Go (`ports/go`) | TypeScript (`ports/ts`) |
|---|---|:--:|:--:|
| Tokenizer | `tokenize.json` | ✅ | ✅ |
| BM25-lite | `bm25.json` | ✅ | ✅ |
| RRF fusion | `rrf.json` | ✅ | ✅ |
| Faithfulness + relevance gate | `faithful.json` | ✅ | ✅ |
| Recursive chunker | `chunker.json` | ✅ | ✅ |
| Evidence-unit ids (block + chunked) | `eu_ids.json` | ✅ | ✅ |
| Answer-language fallback chain | `language.json` | ✅ | ✅ |

**Not yet ported** (tracked): T1 orchestration (client, ingest, retrieve, the
`ask` faithfulness-gated flow, evaluate), Lance/Postgres store bindings, the
Rust-core FFI wiring, hooks/telemetry/streaming, and the Result-JSON +
end-to-end hermetic fixtures (`result_roundtrip.json`, `e2e_hermetic.json` — not
yet present in `conformance/`). A port MUST NOT ship `ask()` without the
faithfulness gate (§1).

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
