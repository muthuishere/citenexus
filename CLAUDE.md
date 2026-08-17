# CiteNexus — Project Instructions

An **evidence-integrity layer** for retrieval, for domains where a wrong answer
is worse than no answer (legal, medical, finance/compliance, enterprise search).
Retrieval finds passages; CiteNexus proves the answer follows from one that
*governs*, and refuses when it can't. Python is the reference facade; Go, JS and
Rust ship the deterministic core. Answers **only** from retrieved evidence;
refuses or states uncertainty when evidence is weak, missing, conflicting, or
unauthoritative. The achievable guarantee is **"no ungrounded claim,"** not "zero
hallucination."

The work is organised around **five classes of confidently-wrong answer** — the
claim that doesn't follow from its own quote, the unsurfaced conflict, the source
with no authority, the governing document in an unreadable script, and the
silently-poisoned corpus. Each is closed by a deterministic check, and each was
closed only after it was **measured failing**. See the live docs site
(`site/`) — it is the accurate public statement of what ships.

Full reference spec (v6): **`docs/SPEC-v6.md`** — the source of truth for what
behavior ships. This file is *how we build it*; the spec is *what we build*.
`docs/adr/` records *why*; ADRs 0004/0007/0009/0011/0012/0013/0014 govern the
current behaviour and outrank any prose here that contradicts them.

**Documentation rule — never write a capability claim from memory.** Every claim
in this file, `README.md`, `CHANGELOG.md` and `docs/` must be checked against
source with a `file:line` before it ships. This repo has published a false
capability claim roughly every time someone skipped that (`ingest_async`,
"13 scripts", "the ports are ASCII-only", a cross-port gate fix two ports did not
have — the last one cost a patch release). Prefer "we don't know" to "wrong".

---

## What CiteNexus is — and is not

Keep this boundary sharp so the library grows in focus instead of sprawling.

**Is:** an evidence-integrity layer over retrieval — multilingual, S3-native.
Python is the reference **facade** (`ingest`/`retrieve`/`ask`/`evaluate`); Go, JS
and Rust ship the **deterministic core**, not a facade. It ingests *artifacts* —
PDF, docx, pptx, xlsx, html, md, txt, csv, and images-into-evidence — plus typed
structural intake (`rag.code`, `rag.schema`), and answers **only** from
retrieved, cited evidence, abstaining when evidence is weak, missing,
conflicting, or below the authority floor. Graph + wiki are **navigation over
evidence** (navigate-not-cite): every hit resolves down to a cited EvidenceUnit
before an answer is generated. Models are **injected**; the documented way to
bring one is **swapping the transport** (below). CiteNexus owns orchestration,
storage, retrieval, fusion, grounding, evaluation. Downstream **products consume
it** — a CLI, an Action, a dashboard are thin surfaces *on top of* the library.

**Port parity, stated precisely** (and don't restate it loosely):

- **At parity.** Tokenizer v2, BM25, RRF, the chunker, and the ADR-0009
  faithfulness predicate are pinned byte-for-byte in Python, Go and JS, over the
  **same 14 scripts** (`python/src/citenexus/tokenize.py:214-231`,
  `golang/tokenize/scripts.json`, `js/src/gen/tables.ts:141-155`,
  `conformance/cases/tokenize_v2.json:3`). Since 0.10.1 the ports' `ask` path
  genuinely calls v2 (`golang/answer/askwith.go:167`, `js/src/answer/answer.ts:94,247`);
  the frozen v1 predicate has zero non-test callers.
- **Predicate-only, though.** `SplitClaims` / `splitClaims` *exist* in both ports
  (`golang/answer/segment.go:144`, `js/src/answer/segment.ts:107`) but have **zero
  non-test callers** — the ports gate the whole answer string as one claim
  (`askwith.go:194`). So atomic-claim decomposition and drop-not-fail are
  effectively Python-only: a port answer passes or refuses **whole**, never trimmed.
- **Python-only, full stop.** Conflict detection (the ports set
  `Conflicts: []string{}` and nothing more), the authority policy (ports carry
  `authority_tier` / `authority_floor_applied` for wire parity, no selection
  logic), the reranker, and the `search_languages` fan-out.

**Is not:**
- **Not a code-comprehension product.** Structural code and schema *intake* does
  ship (`rag.code.ingest_from(...)`, `rag.schema`, `client.py:481,494`) — source
  becomes citable Evidence Units and every graph edge carries an **explicit
  confidence** (`graph/store.py`) rather than being asserted. What stays out is
  the *product*: repo chat, call-graph analytics, IDE surfaces, god-nodes.
  *Background (2026-07-11):* a spike showed tree-sitter's name-based call
  resolution produced ~3× more guessed than reliable edges — which is why edges
  are labelled, not trusted, and why precise call-graph analytics belongs to a
  separate product that *consumes* CiteNexus.
- **Not a memory / "brain."** That moved out to its own Go repo (`../brain`);
  CiteNexus stays pure RAG.
- **Not a model host.** No bundled embedding / LLM / reranker / vision — all
  injected.
- **Not an end-user app.** It's a library (+ optional thin CLIs). Dashboards,
  agent skills, and product UX live in separate repos built on it.

### Where a new feature goes — run this on every feature ask

A capability lands **in CiteNexus core** only if it passes **both** gates:

1. **Artifact-or-grounding gate** — does it ingest an artifact, or improve
   grounded retrieval / evaluation of evidence? (A UI, a workflow, a network
   service, or a domain app is *not* this.)
2. **Cite-or-abstain gate** — can its output be held to **"no ungrounded
   claim"**? If it must assert guesses to be useful, it fails.

**Passes both → in:** propose an OpenSpec change here.
**Fails either → out:** it's a **separate product / repo** that *consumes*
CiteNexus through its public API (`ingest` / `retrieve` / `ask` / `evaluate`).
**If unsure → out.** The core stays small on purpose: you can always pull a
proven external capability in later, but scope is hard to un-ship.

Worked examples:

| Feature | Gate 1 | Gate 2 | Verdict |
|---|---|---|---|
| New extractor (audio→transcript, epub, xlsx) | ✅ artifact | ✅ citable | **in** |
| Better fusion / reranker / new eval metric | ✅ grounding | ✅ | **in** |
| Structural code/schema intake, edges labelled with confidence | ✅ artifact | ✅ confidence, not assertion | **in** (shipped: `rag.code`, `rag.schema`) |
| Call-graph analytics / god-nodes asserted as fact | ✅ artifact | ❌ guessed edges | **out** |
| CLI / dashboard / agent skill / MCP UX | ❌ a surface | — | **out** |
| "Chat with your repo" app, graphify competitor | ❌ product | — | **out** |

---

## How we work

- **Spec-driven, via OpenSpec.** OpenSpec is initialized (`openspec/`, `.claude/`).
  Every capability is one change: `/opsx:propose` → write delta-spec + tasks →
  implement → `/opsx:apply` → `/opsx:archive` (folds the delta into the living
  spec under `openspec/specs/`). OpenSpec owns the spec system — we do **not**
  run a second `docs/specs/` flow alongside it. `docs/` holds only `SPEC-v6.md`
  + ADRs. **How to run it so context stays cheap (commit + `/clear` at every
  phase boundary): [`docs/OPENSPEC-WORKFLOW.md`](docs/OPENSPEC-WORKFLOW.md).**
- **Test-driven, genuinely.** Red → green → refactor per change. Spec tables are
  fixtures: the §4c rebuild matrix, §9 vision decision table, and §11a language
  cases become tests directly. Tests use **deterministic fakes** (hash-based
  embeddings, evidence-echoing LLM, identity reranker) so the cite-or-abstain and
  faithfulness logic is provable offline and flake-free.
- **No drive-by changes.** Touch only what the current change needs.

## Stack (locked)

- **uv** (env / deps / lock) · **hatchling** build backend · **pytest** (+coverage)
  · **ruff** (lint + format) · **mypy --strict**. `src/` layout. Python ≥ 3.11.
- `pyproject.toml` (PEP 621). Import name `citenexus`.
- **No bundled models.** Embedding / LLM / reranker / vision are injected.
  CiteNexus owns orchestration, storage, retrieval, fusion, grounding, evaluation.

### The model seam — swap the transport (ADR-0014)

The **documented** way to bring a model is to keep the shipped client and replace
the function that moves bytes. `transport=` is **keyword-only** on all four
clients — `OpenAICompatibleEmbedding` (`embed/client.py:48`),
`OpenAICompatibleGenerator` (`answer/generator.py:61`), `OpenAICompatibleReranker`
(`retrieve/rerank.py:37`), `OpenAICompatibleVision` (`vision/client.py:83`) — and
`Transport` is a plain callable, nothing to subclass:

```python
Transport = Callable[[str, bytes, dict[str, str]], bytes]   # python/src/citenexus/http.py:36
```

It is genuinely tri-port: Go `models.Transport` (`golang/models/openai.go:16`,
returns an `error` too) and JS `Transport` (`js/src/models/openai.ts:20`, may
return a promise). Swapping it keeps the client's request shaping, `${ENV}`
expansion at the HTTP boundary (`http.py:74`), batching and response parsing.

The **seven** `typing.Protocol`s in `citenexus.contracts` — `EmbeddingProvider`,
`GeneratorProvider`, `CompletionProvider`, `VisionProvider`, `RerankerProvider`,
`SingleTextEmbedder`, `SequenceEmbedder` (`contracts.py:83-192`) — are the
**escape hatch** for models that cannot be made OpenAI-shaped, not the front door.
Lead with the transport. Doc: `/citenexus/bring-your-own-model/`.

**Secrets:** never accept an API-key *value* into a constructor. Auth is
`${ENV}`-in-headers, expanded only at the request boundary.

All four clients are exported **top-level** (`from citenexus import
OpenAICompatibleEmbedding, ...`, `__init__.py:57-86`) — no deep imports in docs
or examples.

## Conventions (carried from the reqsume kernel; library-adapted)

- **Taskfile target-first.** Every ritual is a `task` target; safety/env logic
  lives in the Taskfile, not callers. Verbs: `test` / `test:unit` /
  `test:integration` / `lint` / `format` / `typecheck` / `build` / `publish`.
  A separate `python/Taskfile.local.yml` (own `dotenv:`) holds the example env so
  it can't cross-contaminate. **Both Taskfiles live under `python/`; there is no
  repo-root Taskfile — run `task` from `python/`.**
- **`docs/` + `docs/adr/NNNN-name.md`.** ADRs record *why X over Y* (e.g.
  ADR-0001 = uv/hatchling stack + OpenSpec; ADR-0002 = foundation-first ordering).
  ADRs **0004** authority · **0007** conflict · **0008** reconciliation/revoke ·
  **0009** atomic-claim faithfulness · **0011** tokenizer/scripts · **0012**
  subject scope (open) · **0013** search fan-out · **0014** the model seam are the
  ones that govern current behaviour.
- **CI = GitHub Actions:** `on: pull_request` from day one; third-party actions
  pinned to commit SHAs (not floating tags); publish job `needs: test`.
- **Release:** semver, tag → build → **PyPI via OIDC trusted publishing**,
  CHANGELOG. (No precedent in the kernel — this repo sets it.)
- **Commits:** loose Conventional Commits (`feat:`/`fix:`/`docs:`/`chore:`),
  trunk-based, short-lived branches off `main`, squash-merge.
- **Never** add `Co-authored-by:` to commits. Never read/commit `*.env` or
  secrets; never echo secret values.

## Local infra (`compose.yaml`)

A local **MinIO** is the **opt-in** S3 backend for the storage layer (L2+) and the
integration tests — the examples default to LocalFs + hosted models and need no
containers. `task local:minio:up` starts it and auto-creates the
bucket: S3 API `:19000`, console `:19001` (`minioadmin`/`minioadmin`), bucket
`citenexus-local` (high ports isolate it from any other MinIO on 9000). Images
pinned by digest. Env template in `.env.example` (`CITENEXUS_S3_ENDPOINT_URL`,
`AWS_*`, model base-urls). Unit tests stay hermetic (fakes) and need nothing
running; only integration/example touch MinIO + Ollama.

## Examples — there are THREE, in two places

Easy to get wrong; check the path before writing about them. The default stack is
**cheap + hosted** (Jina embed/rerank + Gemini LLM + LocalFs), **not** MinIO +
Ollama — those are opt-in.

- **`python/example/`** — the quickstart (`run.py`, `golden.csv`, `corpus/`,
  `.env.example`). This is what `task local:example` runs: `Taskfile.local.yml`
  lives in `python/`, so its `dir: example` resolves to `python/example/`.
  *It is not broken — do not "fix" it, and do not claim the directory is missing
  because it is absent from the repo root.*
- **`examples/multilingual/`** — a 12-document EN/TA/TE corpus. The
  `search_languages` fan-out (ADR-0013) and the answer-language rule.
- **`examples/law-authority/`** — a California landlord–tenant corpus with
  `golden.csv` + committed `results.json` / `RESULTS.md`. The authority-floor
  benchmark (ADR-0004).

The last two run with `uv run python run.py` from their own directory.
`task local:ollama:up` / `task local:models:up` / `task local:minio:up` pull the
heavier all-local variants (bge-m3, qwen2.5, `xitao/bge-reranker-v2-m3`, MinIO).
Compose lives at `python/compose.yaml`.

**Benchmark numbers are single live runs.** Gemini is not deterministic at
temperature 0: `examples/law-authority/RESULTS.md:62-72` records an identical
re-run moving the *rate* metrics by one question. Only the **safety** metrics
reproduced (0 out-of-jurisdiction citations, 100% groundedness/citation, 100%
abstain-when-no-evidence). Never quote a rate from these without that caveat.

---

## Build plan — foundation-first (chosen ordering)

Each L is one or more OpenSpec changes, built test-first, then archived.

**Status: L0–L5 shipped; L6 partially.** Released **0.10.1** (2026-08-17) to PyPI
`citenexus`, npm `@muthuishere/citenexus`, and Go `golang/v0.10.1`. The
`citenexus-core` crate on crates.io is **behind** the repo (0.5.0 vs 0.10.1) and
npm `@muthuishere/citenexus-core` is at 0.8.0 — don't claim one version across
every registry. Shipped since the plan below was written: ADR-0004 authority
floor, ADR-0007 conflict surfacing, ADR-0008 corpus reconciliation + the revoke
fix, ADR-0009 per-claim faithfulness, ADR-0011 Unicode tokenizer, ADR-0013
`search_languages` fan-out, ADR-0014 the transport seam, `rag.code`/`rag.schema`,
and the deep-ask agentic loop (`strategy="deep"`).

- **L0 — Scaffold:** uv + pyproject + Taskfile(+local) + ruff/mypy/pytest + CI
  (PR-triggered, SHA-pinned) + release(OIDC) + `docs/SPEC-v6.md` + ADR-0001/0002
  + this file. (Per kernel: AGENTS.md is normally canonical with CLAUDE.md a thin
  pointer — for now CLAUDE.md is the single canonical project doc, by request.)
- **L1 — Core domain (pure, exhaustively unit-tested):** `core-domain-types`
  (EvidenceUnit, variable-depth PartitionPath, Result/Provenance/EvidenceSignals,
  trust modes) · `config-and-signals` (`signals=[…]` capability gate + warn-only
  `citenexus.validate.yaml`) · `plugin-protocol-registry` (11 typed ABCs +
  registry + `rag.use()`) · `provenance-and-rebuild` (artifact stamps + partial-
  rebuild planner = §4c matrix).
- **L2 — Storage & runtime:** `storage-partition-seam` (S3 + manifests + leaf-
  LanceDB resolution; local-fs/MinIO test backend) · `worker-queue-resume`
  (durable queue, retry/backoff, DLQ, idempotent-by-hash, resume) ·
  `telemetry-cost` (one event stream, two views) · `access-prefilter`
  (scope→partitions, `allowed_partitions` hard pre-filter, `acl` carried-not-
  enforced) · **`smoke-e2e`** (stub ingest→vector→ask over fakes, kept green by
  every later layer — the mitigation for foundation-first drift risk).
- **L3 — Ingest & extraction:** `ingest-pipeline` (universal intake:
  files/prefix/raw, sync+async, signal-gated, idempotent) · `extractors`
  (pdf/docx/pptx/html/md/txt/csv/image+OCR/plain + unknown→plain fallback) ·
  `conditional-vision` (pre-filter + 3-way decision) · `evidence-builder` +
  `structure-index` (best-effort; "no structure → empty, not failure") ·
  `language-detect` (fastText lid.176 + threshold + fallback chain).
- **L4 — Embedding, retrieval, fusion:** `embedding-bge-m3` (dense+sparse,
  batched) · `vector-store-lance` · `retrievers` (v0.1: vector + sparse-lexical +
  structure) · `rrf-fusion-rerank` (k=60, rerank seam, navigate-not-cite resolve-
  down-to-EU invariant).
- **L5 — Answer, verify, eval (the guarantee):** `answer-flow-strict` (temp-0
  grounded, per-claim faithfulness gate, cite-or-abstain, structured signals,
  conflict surfacing, **answer-language invariant** regenerate-on-mismatch,
  citations verbatim) · `evaluate-and-judge` (`evaluate(csv)` front door +
  groundedness/citation/refusal/per-language metrics + append-only audit + offline
  judge baseline). ✅ shipped — the gate is now ADR-0009's ordered, gap-bounded,
  polarity-guarded predicate per **atomic claim** with drop-not-fail
  (`answer/verify.py:221`, `answer/segment.py:57`, `answer/flow.py:299-313`).
- **L6 — v0.2/v0.3 breadth (later):** graph (extractor/resolve/lance/traverse/
  Leiden community) · wiki (distill/index/store/lint, navigate-not-cite) ·
  streaming (token / sentence-gated) · conversation memory (partition/acl-scoped)
  · MCP server · online judge · synthetic/drift · external-store authorization
  enforcement · agentic loop. **Shipped:** graph, wiki (shallow — one 24k-char
  whole-corpus call), streaming, conversation memory, the agentic deep-ask loop.
  **Still open:** Leiden communities, MCP server, online judge, LLM graph
  extraction, external-store authorization enforcement.

### Public API (DHH-style, three verbs)

```python
from citenexus import CiteNexus
rag = CiteNexus("s3://my-bucket", signals=["embedding", "text"])  # signals gate ingest+ask
rag.ingest("policy.pdf")                          # any supported type — SYNCHRONOUS
response = rag.ask("Can the employee disclose this?")  # strict default
score = rag.evaluate("golden.csv")                # scored, audited
```

**`ingest()` is synchronous. There is no `ingest_async`** — it does not exist in
`python/`, `golang/`, `js/` or `rust/`, and any doc that claims it is wrong. What
the worker layer buys is **durability**, not concurrency:
`worker/queue.py`'s `DurableQueue` gives retry/backoff, a DLQ, idempotent-by-hash
and resume, with a non-sleeping executor. It is wired into `IngestPipeline`
(`ingest/pipeline.py:231-237`) but **not reachable from the `CiteNexus`
constructor** — there is no `queue=` parameter (`client.py:117-152`).

Facade verbs actually on the client (`client.py`): `ingest` :432, `code` :481,
`schema` :494, `delete` :512, `retrieve` :635, `ask` :659, `stream` :850,
`evaluate` :883, `reconcile` :887, `remediate` :915, `recall` :944.
`ask()` also takes `strategy=` ("strict" | "deep") and `search_languages=`
(default `("en",)`, `client.py:107`). `retrieve()` (documents only) is the public
engine under `ask()` — the eval surface and the small-model escape hatch.
`ask()`/`stream()`/`evaluate()` **raise** without a generator (`client.py:934`);
`retrieve()` works without one.

## Known gaps — state these, never quietly drop them

- **Subject-scope applicability is an OPEN GAP** (ADR-0012, *proposed*).
  Chunking severs a precondition from the operative rule it governs, so **8 of 11
  operative EUs are citable without the clause that governs them** (73%
  severance). A controlling statute can be quoted verbatim, cited correctly, clear
  both the faithfulness gate *and* the authority floor, and still govern a
  different subject. Neither authority nor the gate catches it.
- **The tuning constants are pinned, non-configurable, and English-fitted.** The
  gate's `MAX_SINGLE_GAP = 4` / `MAX_TOTAL_GAP = 8` (`answer/verify.py:135-136`)
  and conflict's `MAX_RESIDUAL = 1` (`answer/conflict.py:84`) were swept on
  **synthetic, single-sentence, English** fixtures and never re-measured on a live
  non-English corpus.
- **`evaluate()` does not fan out over `search_languages`.** It calls
  `Evaluator(self.ask)` with a one-arg callable (`client.py:883-885`,
  `evaluate.py:74`), so the `("en",)` default always applies — which is why the
  multilingual example's `library_evaluate` disagrees with its own harness.
- **`evaluate()` cannot score abstention.** A blank `expected` earns
  expected-support **iff the row was answered** (`evaluate.py:76-77`). To gate on
  must-refuse rows, drive `ask()` and assert `Decision.refused`.
- **`bbox` is captured at extraction but never reaches `Result.sources`.**
  `grep 'bbox=' python/src/citenexus/answer/` is empty; `SourceRef.bbox` is
  always `None` (`answer/result.py:101`). Cite to **document + page**, not bbox.
- **`acl` is carried, not enforced.** Isolation comes from `PartitionPath` +
  the `allowed_partitions` pre-filter. Never document `acl` as tenant isolation.

## Open decisions

- ~~**PyPI dist name**~~ — resolved: `citenexus` on PyPI (ADR-0003).
- **fastText `lid.176`** (~126 MB) is a vendored asset behind
  `LanguageDetectorPlugin` — fetch on first use / cache, not a pip dep.
  `HeuristicDetector` remains the no-network default.
- **Prebuilt native core** — the FFI load seam is proven across linux x64/arm64,
  macOS arm64 and windows x64 (`spikes/prebuilt-ffi/`); cross-compiling the full
  core and per-platform packaging are not done.

<!-- ctx-optimize:begin -->
<ctx-optimize>
  <precondition>Run `command -v ctx-optimize` first. If it is NOT installed, IGNORE this entire
  block and answer by reading the code normally — the store is an optimization, not a requirement
  (install later with `npm install -g @muthuishere/ctx-optimize`, or download the binary). Everything
  below applies ONLY when the command exists.</precondition>
  <store>MULTI-MODULE repo, pre-built knowledge store at `~/ctxoptimize/rag-cite-nexus/` — one graph per module + a navigator, 6 modules declared in `.ctxoptimize/config.json`.</store>
  <use>Use it INSTEAD of grep-and-read chains — PICK BY INTENT: find → `ctx-optimize query "<terms>"` ·
  inspect a symbol → `card <symbol>` · about to EDIT → `change-plan <symbol>` (callers+impact+tests, one
  call) · blast radius → `affected <symbol>` · connection → `path <a> <b>` ·
  list/filter (no jq): `nodes --kind K` / `edges --relation R` / `deps --scope dev`.
  Scope follows your cwd: a module dir answers from that module (zero hits escalate repo-wide); the root
  federates via the navigator (`~/ctxoptimize/rag-cite-nexus/navigator.md`; `--modules all|a,b` widens).
  Output is parsed fact with exact file:line — cite it directly, do NOT re-verify in source.
  Exhaustive literal-string sweeps stay grep's job.</use>
  <deep-doc>The FULL usage card — verify discipline, store-vs-grep ladder, sources (databases/
  buckets/queues/APIs by env-var name), remote push/pull, `up` — is committed at
  `.ctxoptimize/instructions.md`. Read it before deeper store work.</deep-doc>
  <no-local-store>Fresh clone with nothing at `~/ctxoptimize/rag-cite-nexus/`? Run `ctx-optimize up` —
  it pulls the team's prebuilt store when the config declares one, otherwise rebuilds every module store in seconds.</no-local-store>
</ctx-optimize>
<!-- ctx-optimize:end -->
