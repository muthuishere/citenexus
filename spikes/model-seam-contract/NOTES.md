# Spike — ADR-0014 "the model seam is a contract, not an endpoint"

Feasibility assessment. Nothing outside `spikes/model-seam-contract/` was touched.

Run the proofs:

```
python/.venv/bin/python spikes/model-seam-contract/spike.py
```

It is fully offline: it introspects the installed `citenexus` package, runs a Go
sub-proof (`go run ./spikes/model-seam-contract/go`, plus an intentional compile
failure in `./go/honest`), and a JS sub-proof (`node js/runtime.mjs` + `tsc` on
`js/embedder.ts`).

---

## Part 1 — the ADR's factual claims, checked

### Claim 1 — four embedder abstractions in Python. **HOLDS, and undercounts: there are five.**

| # | declaration | file:line | shape |
|---|---|---|---|
| 1 | `EmbeddingPlugin.embed` (ABC) | `python/src/citenexus/plugins/base.py:62,66` | `(Sequence[str]) -> list[Embedding]` |
| 2 | `Embedder` (Protocol) | `python/src/citenexus/ingest/pipeline.py:49` | `(str) -> list[float]` |
| 3 | `_BatchEmbedder` (Protocol) | `python/src/citenexus/embed/batcher.py:17` | `(Sequence[str]) -> list[list[float]]` |
| 4 | `QueryEmbedder` (Protocol) | `python/src/citenexus/retrieve/vector.py:21` | `(str) -> list[float]` — **the ADR missed this one, and it is the one on the public constructor** |
| 5 | `Embedder` (Protocol, again) | `python/src/citenexus/smoke/pipeline.py:32` | `(str) -> list[float]` |

Plus the adapters: `_SingleTextEmbedder` (`client.py:84`) and `_ZeroEmbedder`
(`client.py:104`), and a second method on the concrete client,
`OpenAICompatibleEmbedding.embed_query` (`embed/client.py:67`) — which is R1's
"a single text is not a second method" violated in the one place it matters.

Note #3 is *not* interchangeable with #1 even though both are batch:
`_BatchEmbedder` returns `list[list[float]]`, the ABC returns `list[Embedding]`.
They only appear compatible because of the finding under claim 5b below.

Same duplication exists on the other seams:
- vision — `VisionPlugin.describe -> VisionResult` (`plugins/base.py:69,73`) vs
  `VisionDescriber.describe -> Any` (`ingest/pipeline.py:53-60`)
- generator — `Generator.answer(question, passage, answer_language)`
  (`answer/flow.py:38`) vs `Generator.answer(question, passage)`
  (`smoke/pipeline.py:36`)
- reranker — `RerankerPlugin` (`plugins/base.py:96`) re-declared structurally at
  `retrieve/engine.py:26`

### Claim 2 — batching discovered by `getattr`. **HOLDS.**

`python/src/citenexus/ingest/pipeline.py:390-396`. Spike §2 runs the exact body
against two embedders that both satisfy every declared protocol; one silently
gets 1 call, the other 3. `embed_many` is declared in **no** protocol anywhere —
it exists only on `_SingleTextEmbedder.embed_many` (`client.py:99`). A provider
reading the published type cannot learn the capability exists.

### Claim 3 — Go cannot report failure. **HOLDS. Proven by construction (spike §5).**

Interface at `golang/ingest/ingest.go:24`; the unguarded call at
`golang/ingest/ingest.go:67`. With an embedder that times out on the second
chunk:

```
ingest() returned err = <nil>          <-- ingest saw NOTHING wrong
rows written: 3 (same as the healthy run: 3)
* row 1  eu_id=doc-1:b0:c1  vector=[0 0 0 0]  text="the employee may not disclose the defect"
  row 1  cosine=0.0000   (a schema-valid float64 score; no error, no flag)
```

The poisoned EU is the *polarity-flipped* clause — exactly the sentence a legal
corpus cannot afford to lose. Retrieval sees "not similar", indistinguishable
from a document that genuinely embeds far away. `nil` is worse, not better: it
produces a dimension mismatch that surfaces as a *storage* error, misattributed.

And the honest signature is structurally rejected — `go build ./go/honest`:

```
cannot use HonestEmbedder{} ... does not implement Embedder (wrong type for method Embed)
    have Embed(string) ([]float64, error)
    want Embed(string) []float64
```

**This claim is stronger than the ADR states.** Go *already has* the contract the
ADR is asking for — `golang/models/embed.go:33`
`func (e *OpenAIEmbedding) Embed(texts []string) ([][]float64, error)`: batch,
error-returning, transport-injected. It simply **cannot be plugged into
`ingest.Ingest`**. The only two implementers of `ingest.Embedder` in the whole
repo are fakes (`golang/fakes/fakes.go:28`, `golang/ingest/ingest_test.go:18`),
and the only caller of `Ingest` is a test (`ingest_test.go:39`). Go's real model
client and Go's ingest seam have never met.

Corroborating evidence the repo already knows zero vectors are poison:
`python/src/citenexus/testing/fakes.py:36` `is_zero_vector`, whose docstring says
a zero vector "ranks meaninglessly … passes or fails at random while appearing to
measure something". It was written after ADR-0011 and is **used only in tests**
(`python/tests/test_fakes_multilingual.py`). Nothing guards the write path.

### Claim 4 — JS `Embedder` is synchronous. **HOLDS, and the JS port is worse than described.**

Type at `js/src/ingest/ingest.ts:16`; used unguarded at `ingest.ts:69`.
`tsc --strict` rejects any async embedder (spike §6):

```
error TS2322: Type '(text: string) => Promise<number[]>' is not assignable to type 'Embedder'.
```

Casting past it — the only way to get an HTTP model in — puts a `Promise` in
`row.vector`, which JSON-serialises to `{}` for the FFI store, and the rejection
is never awaited, so a failed model call is an unhandled rejection `ingest()`
never sees.

**Does any real JS path already work around it? No — there is a second type lie
underneath.** `js/src/models/openai.ts:11-15` declares
`Transport = (url, body, headers) => string`, but the only concrete transport,
`js/src/http.ts:55`, is `async send(): Promise<string>` (its own comment admits
it). So `js/src/models/embed.ts:42` does `JSON.parse(<Promise>)` →
`SyntaxError: Unexpected token 'o', "[object Promise]" is not valid JSON`
(spike §6 BONUS). Every test that exercises `OpenAIEmbedder` injects a
*synchronous fake* transport (`js/src/models/models.test.ts:62,70`,
`js/src/http.test.ts:42`), which is exactly what hides it. **The JS port has no
working real-model ingest path at all** — sync `Embedder` and sync `Transport`
are only ever satisfied by fakes. The ADR says JS "works today only because
whatever is behind it is already resident"; the truth is nothing is behind it.

### Claim 5 — the other seams

| seam | file:line | shape | assessment |
|---|---|---|---|
| `RerankerPlugin` | `plugins/base.py:96,100` | `rerank(query, Sequence[Candidate]) -> list[Candidate]` | same problem shape (no failure type), but *not* the same problem as embedding: only one abstraction, no adapter, no `getattr`. Re-declared structurally at `retrieve/engine.py:26`. |
| `VisionPlugin` | `plugins/base.py:69,73` | `describe(image_region: Any) -> VisionResult` | worst-typed seam in the repo: `Any` in, and a *second* parallel declaration at `ingest/pipeline.py:53-60` returning `Any`. |
| `DecisionModel` | `answer/decision.py:33` | `decide(question, Sequence[str]) -> LoopDecision` | not a raw model seam — it is a *parsed* seam layered over `Completion`. Fine as is. |
| `Completion` | `answer/decision.py:39` | `complete(prompt: str) -> str` | **ADR's "already almost exactly right" — CONFIRMED.** One method, no transport in the signature, satisfied by `answer/generator.py:107`, `answer/anthropic.py:82`, and `testing/fakes.py:119`. Its one gap is that it is not batch and cannot express failure in the type (Python raises, so this is cosmetic here — it becomes real when Go/JS grow the same seam). |

### Where the ADR is wrong or overstated

1. **"R3 — the seam must not assume a transport" is already satisfied everywhere.**
   No seam in any port has `base_url`, `headers`, `timeout` or a status code in
   its signature. The `Transport` callable (`citenexus/http.py`,
   `golang/models/http.go`, `js/src/models/openai.ts`) is already the injection
   point, and the seam takes plain objects. R3 costs zero work and unblocks
   nothing that is currently blocked; it is a restatement of the existing design,
   not a change. Presenting it as one of four requirements inflates the ADR.

2. **"Two of the six shapes are structurally unable to accept a real provider"
   understates it for Go.** Go's real provider exists and is orphaned; JS's is a
   dead code path. The right framing is: *neither Go nor JS has ever run a real
   model through ingest.* That is a stronger argument for the ADR, and a much
   smaller migration than "breaking change to two ports" implies.

3. **"Python is one of the six broken shapes" — R2 does not apply to Python
   (spike §3).** Python's seam is untyped about failure but not broken by it: a
   raising embedder propagates and nothing is written. Python's problem is R1
   (five declarations), which is a tidiness/discoverability problem, not a
   correctness one. Lumping them together makes the Python work look more urgent
   than it is.

4. **"Every test can run offline" is already true and is not a consequence of
   this ADR.** Every test in the repo already runs offline today, through
   `FakeEmbedding` / `FakeLLM` / fake `Transport`. The contract does not buy
   offline tests; it buys *honest* ones — today's fakes are the only things that
   can satisfy the JS and Go seams, so the offline suite is green precisely
   because it never exercises a real provider shape. Say that instead; it is the
   better argument.

5. **`_SingleTextEmbedder` has a reason to exist the ADR missed.** It is not
   "an adapter between two of our own abstractions" for its own sake — it adapts
   the *batch wire plugin* to the *single-text seam that is on the public
   constructor* (`client.py:153` `embedder: QueryEmbedder | None`). Under R1 the
   adapter does not disappear; it **flips direction**: you will need a
   single→batch shim to keep every existing user's `CiteNexus(embedder=…)`
   working, because their object has `.embed(text) -> list[float]`. Under the
   0.x deprecated-not-removed policy that shim is mandatory. Budget for it.
   `_ZeroEmbedder` genuinely does disappear (it is a null-object for the
   no-embedder case, better expressed by not building the vector retriever —
   `client.py:220` already does that check).

---

## Part 2 — the three open questions, settled

### Q1. Sync or async in Python → **stay synchronous; do not add an async contract.**

The premise in the brief — "there IS an `ingest_async`" — **is false.** `ingest_async`
exists nowhere in `python/`, `js/`, `golang/` or `rust/`. It appears only as
documentation of something never built: `CLAUDE.md:188`, `CHANGELOG.md:182`
(which lists it as *shipped* — that is a documentation bug worth fixing
separately), and the archived proposal
`openspec/changes/archive/2026-06-26-ingest-pipeline/proposal.md:20`.

What actually exists is **durability, not concurrency**: `DurableQueue`
(`python/src/citenexus/worker/queue.py:69`) is a SQLite-backed, content-hash-keyed
manifest, and `Executor` (`worker/executor.py:39`) *computes* backoff without
sleeping — `:49,:67` say "a real worker would wait this long". There is no event
loop and no worker process. Go and JS have no queue at all.

So the codebase has already answered this: **the concurrency story is the worker
queue, not `async def`.** Recommendation:

- Contract is **sync**, and it is **batch** — which is the point. Batch is how a
  sync seam gets throughput out of an async provider: the provider does
  `asyncio.run(gather(...))` *inside* its own `embed(texts)`, and CiteNexus never
  sees a coroutine. An async provider is not excluded by a sync batch contract;
  it is excluded by a sync *single-text* contract. R1 and Q1 are the same
  decision.
- Do **not** ship `aembed`/`AsyncEmbeddingPlugin`. It doubles the API surface,
  doubles the conformance matrix, and colours the whole call stack above it
  (`IngestPipeline` → `client.ingest` → `ask`) — the "async colour" spreads to
  everything, for a caller base that has asked for none of it.
- If a genuine async host appears later, the additive answer is one
  `AsyncEmbedder` protocol plus a `run_async_embedder()` bridge shipped in
  `citenexus.testing`-style helpers, not a second core seam.

### Q2. Does `Embedding` stay the return type → **no. Return dense `list[list[float]]`.**

The evidence is unambiguous:

- `python/src/citenexus/plugins/base.py:28` — `Embedding = Any  # a dense vector
  + optional sparse term weights`. The type is **literally `Any`**. It has been
  documenting an intention, not enforcing a shape, and `mypy --strict` has been
  passing on it vacuously (spike §4).
- `EvidenceUnit.sparse_vector` (`evidence/unit.py:95`) is declared and **never
  written and never read** — one declaration, zero assignments, zero call sites.
- The only concrete plugin is dense-only and says so:
  `python/src/citenexus/embed/client.py:13-15` — "returns DENSE vectors only …
  this plugin never fakes a sparse vector."
- The lexical/sparse signal is BM25 over stored EU text
  (`python/src/citenexus/storage/bm25.py:15-16`,
  `python/src/citenexus/retrieve/lexical.py`) — it never touches the embedder.
- `_BatchEmbedder` (`embed/batcher.py:17`) already declares the honest type,
  `list[list[float]]`.

So sparsity is **already** elsewhere. Making the contract `list[list[float]]` is
not a decision to move it; it is deleting an alias that never described reality.
If a sparse-capable endpoint ever lands, it is a *separate* `SparseEmbedding`
contract returning `dict[str, float]`, fused as a third retrieval signal —
which is exactly how the retrieval layer is already built.

### Q3. One contract with embedding, or two → **two. They are different operations.**

- Different arity and different meaning: `embed(texts) -> vectors` is a pure
  map, `rerank(query, candidates) -> candidates` is a *query-conditioned
  reordering*. A cross-encoder has no vector to hand back at all.
- They already share nothing but the `Plugin` base:
  `plugins/base.py:62` vs `:96`, and the real clients
  (`embed/client.py:30`, `retrieve/rerank.py:21`) share only `Transport`.
- The one place they are unified today —
  `python/tests/plugins/test_registry.py:144` `DualPlugin(EmbeddingPlugin,
  RerankerPlugin)` — is a *test* proving one object may implement both. That
  works because they are two contracts, and would be impossible if they were one.
- Reranking is also the seam most likely to grow options (top-n, score
  thresholds, instruction prefixes) that embedding will never want.

Keep the *requirements* shared (R1 batch, R2 failure, R4 cross-port), keep the
*contracts* separate. Same for `VisionPlugin` and `Completion`.

---

## Part 3 — blast radius and verdict

### Call sites, per port

**Go — tiny. 1 interface, 2 implementers (both fakes), 1 caller (a test).**
- `golang/ingest/ingest.go:24` (interface), `:67` (call)
- `golang/fakes/fakes.go:28`, `golang/ingest/ingest_test.go:18` — the implementers
- `golang/ingest/ingest_test.go:39` — the only caller
- `golang/answer/answer.go:41` hardcodes `fakes.FakeEmbedding{}` — not injected
  at all; the seam is not even used there
- `golang/models/embed.go:33,61` — the real client, **already the target shape**
- No reranker, no vision in Go.
- Go test files touching the seam: **3**

**JS — tiny. 1 type, 2 values, 2 callers (both tests).**
- `js/src/ingest/ingest.ts:16` (type), `:69` (call)
- `js/src/fakes/fakes.ts:19-20`; `js/src/ingest/ingest.test.ts:26` (the adapter)
- `js/src/ingest/ingest.test.ts:30,52` — the only callers
- `js/src/answer/answer.ts:54` hardcodes `new FakeEmbedding()`
- `js/src/models/embed.ts:21,35,47` — the wire client (currently a dead path;
  fixing it means fixing `Transport` at `js/src/models/openai.ts:11-15` too)
- JS test files touching the seam: **4**

**Python — the real cost, and it is mostly mechanical.**
- 5 protocol declarations to collapse to 1
  (`plugins/base.py:62`, `ingest/pipeline.py:49`, `embed/batcher.py:17`,
  `retrieve/vector.py:21`, `smoke/pipeline.py:32`)
- 5 call sites: `ingest/pipeline.py:396` + `:391` (the `getattr`),
  `retrieve/vector.py:49`, `smoke/pipeline.py:73,90`
- 3 src implementations: `testing/fakes.py:49`, `client.py:84`, `client.py:104`
- 1 wire client: `embed/client.py:30` (already batch; loses `embed_query`)
- `IngestPipeline` construction: 1 src (`client.py:202,206,438`, real embedder
  built at `:297`) + 9 tests
- Test files touching the seam: **~52** (76 mentioning `embed*` at all).
  Most are one-line double definitions.

### Conformance fixtures — **not moved. This is the good news.**

`conformance/cases/e2e_hermetic.json` is generated by
`python/scripts/gen_conformance.py:1348`, and the generator does call the
embedder seam through the fakes: `:522` `embedder = FakeEmbedding()`, `:530`
`embedder.embed(doc["text"])`, `:534` `embedder.embed(question)`.

But the fixture's *values* are a per-text SHA-1 hash (`testing/fakes.py:72`).
Changing the seam from `embed(text)` to `embed([text])[0]` changes two lines of
the generator and **zero bytes of the fixture**. The drift guard
(`python/tests/test_conformance_fixtures.py:31`
`test_committed_fixtures_match_regeneration`) will confirm this automatically —
it re-runs the generator in memory and byte-compares. If it goes red, the change
did something it shouldn't have. Use it as the acceptance test.

Port runners that consume the fixture — `golang/answer/answer_test.go:37`,
`js/src/answer/answer.test.ts:29`, `python/tests/test_fakes_multilingual.py:104`
— all go through the *fakes*, which must keep producing the same per-text hash.
Keep `FakeEmbedding`'s hashing body untouched and only change its arity.

### Public API surface

`CiteNexus.__init__` (`client.py:153`) takes `embedder: QueryEmbedder | None`
(single-text) and `generator: Generator | None`. Under R1 the *declared type*
changes. Per the 0.x deprecated-not-removed policy:

- Keep accepting a single-text object. Detect it at construction
  (`hasattr(obj, "embed")` arity, or a `try` on a one-element batch), wrap it in
  the flipped `_SingleTextEmbedder`, and emit a `DeprecationWarning`. The ctor
  signature becomes `EmbeddingContract | QueryEmbedder` for one minor.
- `generator=` is unaffected (`Generator.answer` is not part of R1).
- Go and JS have **no external consumers of the ingest seam at all** (every
  caller is a test), so "breaking" there is nominal.

### Verdict — **FEASIBLE, with caveats.**

The two defects are real and I proved both by construction. The Go one is a
direct violation of the standing rule *"we never want wrong at all, it's okay we
can say don't know"*: a timed-out model produces a corpus that is silently
missing its most important sentence, and every downstream honesty mechanism
(the faithfulness gate, cite-or-abstain, conflict surfacing) is defeated
upstream, because they can only be honest about evidence that reached the index.
Abstention is the correct outcome of a failed embed; today the failure is
laundered into a confident "no relevant evidence".

The caveats:

1. **Sell it as a correctness fix, not an architecture cleanup.** R2 is the
   whole value. R1 is worth doing while you are in there. R3 is already true.
   R4 is a conformance chore.
2. **The Python half is 80% of the work and ~10% of the value.** ~52 test files,
   5 protocols, and a deprecation shim on the public constructor — to fix a port
   whose failure mode already works. It can be deferred without leaving anything
   broken.
3. **Fixing Go and JS is not enough to make either port usable.** Go's ingest
   has no non-test caller and JS's `Transport` is itself a type lie. If the goal
   is "a provider can plug in", the JS work is `Transport` → `Promise<string>`
   and `ingest` → `async` all the way down, which is bigger than the ADR's
   framing. Scope that explicitly or you will land a correct seam above a dead
   transport.
4. **Don't let the contract be the only fix for the zero vector.** See stage 0.

### Staged plan (minimises the window where ports disagree)

**Stage 0 — additive, non-breaking, ship first, no ADR needed.**
Reject the zero/empty vector at the *write* boundary in all three ports:
`is_zero_vector` already exists (`testing/fakes.py:36`) and is used only in
tests. Promote it to the ingest write path — a zero or wrong-dimension vector is
an ingest error, never a row. This closes the actual corpus-poisoning hole in
hours, independently of whether the contract lands, and it keeps holding for any
provider that ships a broken vector for reasons the seam can't see. It is also
the answer to "what if we do nothing else".

**Stage 1 — Go (breaking in name only).**
`Embedder` → `Embed(texts []string) ([][]float64, error)`. `golang/models/embed.go:33`
then satisfies it as-is — delete nothing, gain the real client. Update
`fakes.FakeEmbedding`, `ingest_test.go`, and `ingest.Ingest` to propagate the
error. 3 files. Zero non-test consumers.

**Stage 2 — JS (breaking, and the bigger of the two).**
`Embedder` → `(texts: string[]) => Promise<number[][]>`, `ingest()` → `async`,
and — required, not optional — `Transport` → `Promise<string>` so
`models/embed.ts` stops parsing a Promise. 5-6 files.

**Stage 3 — conformance.**
Add a `provider_contract` case set: batch-of-one equals single, order is
preserved, a failing provider surfaces as an error and writes nothing, a
zero vector is rejected. Assert it in all three runners. Regenerate; expect
`e2e_hermetic.json` to be byte-identical.

**Stage 4 — Python (additive first, breaking later or never).**
4a: collapse the five protocols to one *alias-compatible* declaration and
delete `getattr(self._embedder, "embed_many")` in favour of the declared batch
method — internal-only, no public change. 4b: widen the ctor to accept both
shapes with a `DeprecationWarning` on the single-text one. 4c (a later minor):
drop the shim.

Stages 1 and 2 should land in the same PR or back to back — that is the only
window where the ports disagree about what an embedder is, and it is measured in
days, over code with no external callers.

---

## What would make this wrong

- **If Go or JS have real consumers I could not see.** I found only test callers
  (`golang/ingest/ingest_test.go:39`, `js/src/ingest/ingest.test.ts:30,52`) and
  I searched only this repo. If any downstream product embeds these ports, the
  "breaking in name only" claim collapses and stages 1-2 need a deprecation path
  of their own.
- **If an async Python provider is a near-term requirement, not a hypothetical.**
  Q1's answer ("sync batch; the provider hides its own event loop") assumes the
  host owns the loop. A host that is *itself* inside an event loop cannot call a
  sync `embed()` without blocking it, and `asyncio.run` inside a running loop
  raises. If CiteNexus must be callable from FastAPI/Starlette request handlers,
  re-open Q1 — the answer then is a thread-pool bridge documented as the
  supported pattern, not a second seam.
- **If bge-m3 sparse weights are on the roadmap sooner than I assume.** Q2 says
  drop sparsity from the contract on the evidence that `sparse_vector` is dead
  code. If a sparse-capable endpoint is being wired now, adding it back later is
  a second breaking change to the same seam — worse than deciding it once.
- **If the fixture's stability assumption is wrong.** I reasoned that batch-of-N
  through `FakeEmbedding` equals N single calls because the hash is per-text and
  stateless (`testing/fakes.py:72`). That holds only while the fake stays
  stateless. `test_committed_fixtures_match_regeneration` is the check; if it
  goes red, this note is wrong, not the test.
- **If the owner reads R3 as load-bearing.** My claim that R3 is already
  satisfied rests on no seam signature naming a transport — which I verified for
  embedding, rerank, vision, completion and generator. If there is a seam I did
  not enumerate that does take a URL, R3 becomes real work.
- **If `_ZeroEmbedder` is protecting a shipped lexical-only configuration in a
  way `client.py:220` does not.** I read `:199-221` as already skipping the
  vector retriever when no embedder is given, which makes the null-object
  redundant. A config path that writes vector rows without an embedder would
  contradict that.
