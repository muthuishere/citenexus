# Tasks — port provider contracts

## 0. Decide what is real before writing a line of it

- [x] 0.1 Enumerate every model seam Python publishes and grep both ports for a
      consumer of each (`rerank`, `vision`/`describe`, `Complete`/deep-ask)
- [x] 0.2 Record the verdict per seam in `design.md` §1 — ship embedding +
      generation, withhold completion / vision / reranking, with the evidence
- [x] 0.3 Confirm the ports' `ask` flows hardcode the fakes, i.e. even the two
      shipped seams have no injection point yet

## 1. Go — publish the contracts

- [x] 1.1 Red: `contracts/contracts_test.go` — a struct declared in the test,
      embedding nothing, satisfies `EmbeddingProvider` and `GeneratorProvider`
- [x] 1.2 Red: no contract method takes a base URL / headers / transport /
      timeout (asserted by reflecting over the interface method signatures)
- [x] 1.3 Red: the `contracts` package imports no other CiteNexus package
      (asserted by parsing the package's own import blocks)
- [x] 1.4 Red: a single-text embedder does NOT satisfy `EmbeddingProvider`, and
      a batch provider does NOT satisfy `SingleTextEmbedder`
- [x] 1.5 Red: `EmbedTexts` prefers the batch path, falls back to single-text,
      preserves order, returns `ErrNotAnEmbedder` for anything else
- [x] 1.6 Red: `EmbedTexts` propagates a provider error unchanged
- [x] 1.7 Implement `golang/contracts/contracts.go`

## 2. Go — the seams become aliases, the clients declare

- [x] 2.1 Red: `ingest.Embedder` and `contracts.SingleTextEmbedder` are the same
      type (a value of one is assignable to the other, both directions)
- [x] 2.2 Alias `ingest.Embedder = contracts.SingleTextEmbedder`
- [x] 2.3 Red: `models.OpenAIEmbedding` satisfies `EmbeddingProvider`;
      `OpenAIChatGenerator` and `AnthropicGenerator` satisfy `GeneratorProvider`
- [x] 2.4 Add the compile-time `var _ contracts.X = (*Y)(nil)` assertions in
      `golang/models/`
- [x] 2.5 Red: `contracts.SingleFrom(batch)` yields a working `ingest.Embedder`,
      and errors rather than returning a placeholder when the batch comes back short

## 3. Go — give the contracts a caller

- [x] 3.1 Red: `answer.AskWith` with an empty `Providers` is byte-identical to
      `Ask` over every `e2e_hermetic.json` case
- [x] 3.2 Red: injected providers produce an `answered` result citing the right
      document, with the answer verbatim in that document
- [x] 3.3 Red: a partial provider set (generator only / embedding only) works
- [x] 3.4 Red: an embedding failure and a generator failure each return an error,
      and the returned Result is NOT a refusal
- [x] 3.5 Red: a zero vector / an empty vector / a dimension-inconsistent vector
      from a non-failing provider each return an error naming the vector
- [x] 3.6 Red: a short vector does not panic the cosine
- [x] 3.7 Red: an injected generator that paraphrases is refused by the
      faithfulness gate — the gate still runs on injected output
- [x] 3.8 Implement `AskWith`, `Providers`, the guarded cosine, and make `Ask`
      delegate; confirm `TestAskConformance` still passes untouched

## 4. Go — the third-party proof

- [x] 4.1 Red: `golang/contracts/thirdparty_test.go` — an in-process hashing
      embedder + extractive generator, defined in the test, drive `AskWith` to a
      cited answer over a two-document corpus
- [x] 4.2 Red: a second question over the same provider set cites the other document
- [x] 4.3 Red: the batch method is the path actually taken, and the question is a
      batch of one
- [x] 4.4 Red: assert the test file's CiteNexus imports are exactly the contract
      package plus the packages the *test* (not the provider) needs

## 5. JS — publish the contracts

- [x] 5.1 Red: `src/contracts.test.ts` — an object literal declared in the test
      satisfies `EmbeddingProvider` / `GeneratorProvider` under `tsc --strict`
      (`expectTypeOf`), and both types are re-exported from the package root
- [x] 5.2 Red: a synchronous provider and an async provider both satisfy the contract
- [x] 5.3 Red: `isEmbeddingProvider` returns true for the batch object shape and
      false for the function-shaped single-text seam, `null`, and a bare object
- [x] 5.4 Red: `embedTexts` prefers batch, falls back per-text, preserves order,
      and rejects for a value that is neither
- [x] 5.5 Red: `embedTexts` propagates a rejection unchanged
- [x] 5.6 Red: `embedOne` is a batch of one
- [x] 5.7 Implement `js/src/contracts.ts`; export it from `src/index.ts`;
      re-publish `Embedder` as `SingleTextEmbedder`

## 6. JS — the clients declare

- [x] 6.1 Red: `expectTypeOf<OpenAIEmbedder>().toMatchTypeOf<EmbeddingProvider>()`
      and the same for both generators
- [x] 6.2 Add the static contract assertions inside `models/embed.ts`,
      `models/openai.ts`, `models/anthropic.ts`

## 7. JS — give the contracts a caller

- [x] 7.1 Red: `askWith(corpus, q, {})` matches `ask(corpus, q)` on every
      `e2e_hermetic.json` case
- [x] 7.2 Red: injected providers produce an `answered`, citing result
- [x] 7.3 Red: partial provider sets work
- [x] 7.4 Red: a rejecting embedder and a rejecting generator each reject
      `askWith` rather than resolving to a refusal
- [x] 7.5 Red: zero / empty / wrong-dimension vectors reject
- [x] 7.6 Red: a paraphrasing generator is refused by the gate
- [x] 7.7 Implement `askWith` in `js/src/answer/answer.ts`; leave `ask` sync and
      untouched in behaviour

## 8. JS — the third-party proof

- [x] 8.1 Red: `src/contracts.thirdparty.test.ts` — an in-process provider class
      defined in the test drives `askWith` to a cited answer
- [x] 8.2 Red: a second question cites the other document
- [x] 8.3 Red: batch is the path taken; the question is a batch of one
- [x] 8.4 Red: `globalThis.fetch` is stubbed to throw for the duration of the
      end-to-end run — an in-process provider must not reach the network
- [x] 8.5 Red: the provider's prototype chain contains no CiteNexus class

## 9. Gates

- [x] 9.1 `cd golang && go clean -testcache && go test ./...` — exit 0, zero FAIL
- [x] 9.2 `cd golang && go vet ./... && gofmt -l .` — clean
- [x] 9.3 `cd js && npm test` — no regression from the 334-passing baseline
- [x] 9.4 `cd js && npm run typecheck && npm run build` — clean
- [x] 9.5 `cd spikes/library-stress/ports/go && go run .` — v2 still 0/9
- [x] 9.6 `cd js && node ../spikes/library-stress/ports/js/probe-a.mjs` — v2 still 0/9
- [x] 9.7 `git status python conformance rust site docs` shows none of this
      change's edits

## 10. Landed beyond the plan (recorded, not smuggled)

- [x] 10.1 The three vector rejections moved INTO the published contracts
      (`contracts.CheckVector` / `checkVector`), and each port's ingest
      `checkVector` now delegates to it with its own message prefix. Not in the
      original plan; done because the ask path needed the same guard and two
      copies of "a vector we refuse to index" is exactly the kind of drift this
      change exists to remove. Both ports' existing ingest guard tests are
      unchanged and still pass.
- [x] 10.2 JS carries the ask flow TWICE (`ask` sync + `askWith` async) because a
      contract that may return a Promise cannot be awaited from a synchronous,
      fixture-pinned entry point. Go does not — there `Ask` IS `AskWith` with an
      empty provider set. The JS duplication is held in lockstep by replaying
      every fixture case through both and deep-equalling the whole Result
      (`askwith.test.ts`).
