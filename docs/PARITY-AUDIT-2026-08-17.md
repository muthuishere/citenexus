# CiteNexus tri-port parity audit

**Date:** 2026-08-17 · **Tree:** `main` @ `1b2c7ee` (`chore(release): 0.11.0`)
**Scope:** read-only. Every row below was checked against source with a `file:line`,
and every row marked ⚡ was additionally **executed** against the shipped path.

> 🛑 **SUPERSEDED IN PART — read this before quoting any row.** This audit is a
> snapshot of `1b2c7ee`. Commit `d519550` landed conflict detection natively in
> Go and JS, byte-identical to Python and wired onto the shipped ask path
> (`golang/answer/conflict.go`, `js/src/answer/conflict.ts`,
> `golang/answer/askwith.go:157`, `js/src/answer/answer.ts:97`), pinned by 102
> cases in `conformance/cases/conflict.json`. That **closes §0 finding #1, §3d
> row 1-2 and §7 gap #1**, and supersedes §3b's `conflicts` WIRE-ONLY row and
> §3c's "conflict tables, zero callers" row.
> [`DETERMINISTIC-UTILITIES-2026-08-17.md`](DETERMINISTIC-UTILITIES-2026-08-17.md) §0
> is the corrected delta and was written against `d519550`; read it alongside
> this file. Everything else here was re-confirmed at `d519550`/`070dcf4`.
> The findings this audit contributed to `CLAUDE.md` — the inert
> `allowed_partitions` pre-filter, the never-populated `EdgeConfidence`, the
> non-existent answer-language regeneration, and ASCII-only conflict detection —
> all still hold and are now documented in `CLAUDE.md → Known gaps`.

> ⚠️ **Snapshot caveat — gap #1 is actively being closed while this was written.**
> Another agent is landing ADR-0007 conflict detection into the ports on this same
> tree. At audit time the ports shipped the generated *tables only*, with zero
> importers (`golang/answer/conflict_tables.go`, `js/src/gen/conflict_tables.ts`,
> both untracked). Before the audit closed, `js/src/answer/answer.ts:35-42` gained
> an import of `findConflicts` / `collapseNearDuplicates` / `describeConflicts` /
> `CONFLICT_TOP_K` from a new `js/src/answer/conflict.ts`. **All §8 execution
> results were captured against the pre-change `js/dist` and the pre-change Go
> tree.** Re-run §8.2 before trusting the JS row; Go was still unwired when
> measured. Nothing else in this audit is affected.

---

## 0. Headline — read this if you read nothing else

Three findings outrank everything else in this document.

1. **⚡ Go and JS answer a self-contradicting corpus, confidently, with the
   contradiction erased from the output.** Given two grounded passages —
   `"The employee may disclose the information."` and `"The employee may **not**
   disclose the information."` — Python refuses (`"The available evidence
   disagrees, so I can't answer that."`, `conflicts_detected: 1`). Go and JS both
   return `"The employee may disclose the information."` with
   `decision: "answered"`, `all_claims_verified: true`, `conflicts: []`,
   `conflicts_detected: 0`, **and `supporting_sources: 2`** — counting the passage
   that says the opposite as corroboration. This is a confident, correctly-cited,
   unflagged wrong answer. It is the exact failure class the project exists to
   close, live in two of three ports.

2. **⚡ Python has no embedding-vector validation at all, and Go/JS do.** The
   reverse gap is real and worse than the prompt suggested. Python's
   `embed_texts` (`python/src/citenexus/contracts.py:210`) and `embed_in_batches`
   (`python/src/citenexus/embed/batcher.py:28`) accept a batch that returns
   **fewer vectors than texts** without error — which silently shifts every
   subsequent text→vector pairing and corrupts the index with no loud failure.
   They also accept empty vectors, NaN, and ragged dimensions. Go rejects
   empty / dim-mismatch / all-zero / wrong-arity; JS rejects those **plus
   non-finite**. Grep for any vector guard in `python/src/citenexus/` returns
   nothing outside doc comments.

3. **⚡ Go and JS stamp `"en"` onto evidence that is not English.** A Tamil
   passage answered in Tamil comes back with `passage_language: "en"`,
   `languages_in_evidence: ["en"]`, `unsupported_scripts: []`. Python reports
   `"ta"` correctly. This is not a missing field — it is a **false assertion in a
   populated field**, and both ports contain a working language resolver
   (`golang/lang/lang.go:35`, `js/src/lang/lang.ts:42`) that nothing calls.

Beneath those: **Go and JS have no retrieval pipeline whatsoever.** Their `ask`
takes the corpus as a function argument and ranks it with in-memory cosine over a
hash-bucket fake embedder. BM25, RRF, the chunker, the structure index, euid and
the co-mention graph all exist, are conformance-pinned, and have **zero non-test
callers** in their own port. Closing "every capability in all three ports" is not
a matter of porting ~6 named features; it is building the facade Go and JS do not
have.

---

## 1. Where CLAUDE.md is wrong

CLAUDE.md's "Port parity, stated precisely" section is **directionally honest** —
the three claims it makes loudest (tokenizer v2 parity, predicate-only atomic
claims, Python-only conflict/authority) all survived execution.

**But three capability claims elsewhere in CLAUDE.md are false**, and the file's
own rule ("never write a capability claim from memory") was skipped for each.

### 1a. False capability claims — fix these first

| CLAUDE.md says | Reality |
|---|---|
| *"every graph edge carries an **explicit confidence** (`graph/store.py`) rather than being asserted"* — and the "Where a new feature goes" table passes structural code intake on gate 2 with the justification **"✅ confidence, not assertion"** | **FALSE.** `EdgeConfidence` (`python/src/citenexus/graph/store.py:44`) is **never constructed anywhere in `python/src/`** — `grep 'EdgeConfidence('` returns only the class definition. `GraphEdge.confidence` (`store.py:66`) is always `None`; `graph/distill.py:161-165` sets `relation=` only. Go and JS are the same (`graph/graph.go:147-148`, `graph/graph.ts:106-107`, both hardcoded nil/null). **The cite-or-abstain gate rationale for admitting code intake rests on a field nothing populates.** |
| *"`acl` is carried, not enforced. **Isolation comes from `PartitionPath` + the `allowed_partitions` pre-filter.**"* | **FALSE.** The pre-filter is **not wired**. `access/prefilter.py:31,39,46` and `access/scope.py:20` have **zero non-test callers**; `allowed_partitions` appears exactly once outside `access/` — as a config field at `config/schema.py:282` that **nothing reads**. Retrieval performs no partition filtering and no ACL filtering. So the doc names a fallback mechanism that is also inert: **there is no tenant isolation in any port**, and the caveat as written makes it sound like there is. |
| L5 build plan: *"`answer-flow-strict` (… **answer-language invariant** regenerate-on-mismatch …)"* | **FALSE.** No such check exists. `grep -rn regenerat python/src/` returns exactly one hit — a *comment* at `config/schema.py:264`. `flow.py:308` merely *instructs* the generator via the `language` argument; the returned text's language is never verified, so a generator that ignores the instruction is never caught. |

### 1b. Understatements and citation drift

| CLAUDE.md says | Reality | Severity |
|---|---|---|
| "the ports gate the whole answer string as one claim (`askwith.go:194`)" | The gate call is **`golang/answer/askwith.go:167`**; `:194` is `MissingEvidence: []string{}`. The single-`Claim` construction is `:188-190`. The *claim* is correct; the *citation* points at the wrong line. | citation |
| Facade verb line numbers: "`ingest` :432, `code` :481, `schema` :494, `delete` :512, `retrieve` :635, `ask` :659, `stream` :850, `evaluate` :883, `reconcile` :887, `remediate` :915, `recall` :944" | Every one is **off by exactly +1**: `client.py:433, 482, 495, 513, 636, 660, 851, 884, 888, 916, 945`. A line was inserted above them and the doc was not re-checked. | citation |
| "`SourceRef.bbox` is always `None` (`answer/result.py:101`)" | The field is at **`:102`**. The *behaviour* claim is correct — `grep 'bbox=' python/src/citenexus/answer/` is empty. | citation |
| "Conflict detection … the ports set `Conflicts: []string{}` and nothing more" | **Understated as of this tree.** Both ports now ship the full ADR-0007 *table set* — `golang/answer/conflict_tables.go` (105 lines, 8 exported symbols) and `js/src/gen/conflict_tables.ts` (331 lines, 7 tables) — with **zero importers in either port**. Shipped dead data is a worse state than absence: it reads as "conflict detection is in Go now." | **understatement** |
| "the frozen v1 predicate has zero non-test callers" | ✅ Confirmed for `IsSupported`/`isSupported`. **But v1 `tokenize` is still live on the answer-adjacent path**: `golang/gate/gate.go:51` and `js/src/gate/gate.ts:17` use it for `ContentTokens` (v1), which drives the co-mention graph (`js/src/graph/graph.ts:8,50`) — so the graph is still ASCII-only in both ports. Also `fakes/fakes.go:30` / `js/src/fakes/fakes.ts:22` embed with v1, so **non-Latin text embeds to the all-zero vector** in the hermetic flow. | **incomplete** |
| Tokenizer parity "pinned byte-for-byte … over the same 14 scripts" | ✅ **Verified by execution**, not just by reading — see §5. All four cited paths exist and are correct, including `golang/tokenize/scripts.json`. | correct |
| Known gap: "`evaluate()` does not fan out over `search_languages`" | ✅ Correct (`client.py:884`). | correct |
| Known gap: "`acl` is carried, not enforced" | ✅ Correct — and **stronger than stated across ports**: `grep -i acl` returns **zero hits** in both `golang/` and `js/src`. It is not even carried there. | correct, understated |

**What CLAUDE.md does not say at all, and should:** Python is *not* the superset
(§4), Go and JS have no retrieval pipeline (§0), `conformance/stopwords.json` is
unpinned in two of three ports (§6), **Python's conflict detection is ASCII-only**
(§3e), and **the deep-ask path still cites the context model's blurb** (§3e).

---

## 2. Method

- Structural inventory: full reads of all 32 non-test `.go` files (~4.3k lines) and
  all 32 non-test `.ts` files under `js/src` (~4.7k lines); targeted reads of the
  Python reference.
- Caller counts: `grep` over each port excluding `*_test.go` / `*.test.ts`.
  **Caveat learned the hard way:** `js/src/graph/graph.ts` contains a literal NUL
  byte at line 76 (an intentional co-mention key separator), so plain `grep -r`
  silently skips it. Use `grep -a` when auditing this port.
- ⚡ **Execution** (the part that settles arguments): a Go module with a `replace`
  onto `golang/`, a Node script against the built `js/dist`, and the Python flow
  driven directly — all three fed **identical** inputs, outputs diffed. Full
  transcripts in §8. This is deliberate: the 0.10.0 regression happened because
  probes tested a *predicate* instead of the shipped path, so every behavioural
  claim below that matters was run, not inferred.

---

## 3. The capability matrix

Legend — **PARITY** · **WIRE-ONLY** (field exists, nothing computes it) ·
**DEAD-CODE** (implemented, zero non-test callers) · **MISSING** ·
**HARDCODED** (constant where another port computes).
**A?** = on the answer path — can its absence produce a confidently wrong or
unflagged answer? **T** = ADR-0010 tier (1 structural/arithmetic → native per
port · 2 language-dependent *data* → canonical table, code native · 3
language-dependent *algorithm* → Rust over FFI).

### 3a. The deterministic core — genuinely at parity

| Capability | Python | Go | JS | Verdict | A? | T |
|---|---|---|---|---|---|---|
| ⚡ Tokenizer v2 (14 scripts, NFKC+casefold) | `tokenize.py:227` | `tokenize/tokenize_v2.go:282` | `tokenize/tokenize-v2.ts:225` | **PARITY** — `conformance/cases/tokenize_v2.json`; 12 adversarial Unicode inputs byte-identical in all 3 (§8.4) | — | 3 (correctly placed native; ADR-0010 permits, prototype proved it) |
| ⚡ Faithfulness gate v2 (ordered containment + polarity) | `answer/verify.py:221` | `gate/verify_v2.go:225` | `gate/verify-v2.ts:150` | **PARITY** — `conformance/cases/faithful_v2.json`; 8 adversarial pairs identical in all 3 (§8.4) | yes | 1 ✅ |
| ⚡ Relevance overlap v2 | `answer/verify.py:87` | `gate/gate.go:100` | `gate/gate.ts:58` | **PARITY** — identical in all 3 (§8.4) | yes | 1 ✅ |
| Alignment DP + gap budget (4/8) | `verify.py:135-136,149` | `gate/verify_v2.go:43-45,106` | `gate/verify-v2.ts:36-37,65` | **PARITY** (constants pinned, non-configurable, English-fitted in all three) | yes | 1 ✅ |
| Polarity marker table | `answer/tables.py` | `golang/gate/polarity.json` | `gen/tables.ts:56` | **PARITY** — canonical `conformance/polarity.json`, byte-pinned in Go (`gate/verify_v2_test.go:94`), JS (`gen/tables.test.ts:27`), Python (`tests/answer/test_polarity_table.py:82`) | yes | 2 ✅ |
| Claim segmentation table | `answer/segment.py` | `golang/answer/segmentation.json` | `gen/tables.ts:87` | **PARITY** — byte-pinned (`segment_test.go:44`, `gen/tables.test.ts:31`) | yes | 2 ✅ |
| ⚡ BM25 (k1=1.5, b=0.75, round6) | `storage/bm25.py` | `bm25/bm25.go:41` | `bm25/bm25.ts:34` | **PARITY** — `conformance/cases/bm25.json`; Go/JS scores identical to 1e-6 (§8.4) | no¹ | 1 ✅ |
| ⚡ RRF (k=60) | `retrieve/fusion.py` | `rrf/rrf.go:24` | `rrf/rrf.ts:19` | **PARITY** — `conformance/cases/rrf.json`, the only 4-language vector (Rust `rust/tests/rrf_test.rs:19`). ADR-0010 says delete `rust/src/rrf.rs`; it is **still present** (`ffi.rs:110`) and both ports now mark their native copy `@deprecated` in favour of it — the ADR is being applied *backwards*. | no¹ | 1 |
| ⚡ Chunker (450/60, recursive) | `evidence/chunker.py` | `chunker/chunker.go:160` | `chunker/chunker.ts:127` | **PARITY** — `conformance/cases/chunker.json`; identical output (§8.4) | no | 1 ✅ |
| EU-ID derivation + SHA-256 | `evidence/` | `euid/euid.go:28,41` | `euid/euid.ts:130,137` | **PARITY** — `conformance/cases/eu_ids.json` | no | 1 ✅ |
| Result JSON wire shape | `answer/result.py` | `result/result.go` | `result/result.ts` | **PARITY** — `conformance/cases/result_roundtrip.json` | no | 1 ✅ |
| Answer-language fallback chain (§11a) | `lang/fallback.py` | `lang/lang.go:35` | `lang/lang.ts:42` | **PARITY of the function** — `conformance/cases/language.json`. But see 3c: **nothing calls it in Go or JS.** | yes | 1 |

¹ *not* on the answer path **because Go/JS never call them** — see 3d.

### 3b. WIRE-ONLY — the most dangerous class

Every row here is a populated field in the shipped JSON that no code computes. A
consumer parsing a Go or JS `Result` cannot distinguish "checked, none found"
from "never checked".

| Capability | Python (computes) | Go | JS | Verdict | A? | T |
|---|---|---|---|---|---|---|
| ⚡ **`conflicts` / `conflicts_detected`** | `answer/conflict.py:find_conflicts`, called `flow.py:271`; strict-mode abstention `flow.py:344` | `Conflicts: []string{}` `askwith.go:195`; `ConflictsDetected` never assigned (`result/result.go:49`) | `conflicts: []` `result.ts:213`; `conflicts_detected: 0` `result.ts:131` | **WIRE-ONLY** | **YES — the #1 harm** | 1 (scoring) + 2 (tables) |
| ⚡ `authority_tier` / `authority_floor_applied` | `answer/authority.py`, applied `flow.py:252`, tier `flow.py:397` | `result/result.go:72-73`, never assigned | `result.ts:134-135`, never assigned | **WIRE-ONLY** (both ports' comments admit it) | **yes** | 1 |
| `unsupported_scripts` | `tokenize.py:unsupported_scripts`, `flow.py:189,202` | `[]string{}` `askwith.go:186` — **despite `tokenize.UnsupportedScripts` existing at `tokenize_v2.go:331` with zero callers** | `[]` `result.ts:133` — **despite `unsupportedScripts` at `tokenize-v2.ts:274` with zero callers** | **WIRE-ONLY** over a **DEAD-CODE** producer | **yes** | 3 (producer already native+pinned) |
| `unsupported_claims_removed` | `flow.py:393` | never assigned | `result.ts:130` | **WIRE-ONLY** (no drop-not-fail to report) | no² | 1 |
| `retrieval_score_spread` | `flow.py:391` | never assigned | `result.ts:128` | **WIRE-ONLY** | no | 1 |
| `all_claims_verified` | `flow.py:392` (`removed == 0`) | hardcoded `true` `askwith.go:184` | hardcoded `true` `answer.ts:105,258` | **HARDCODED** — asserts a fact it did not check | **yes** | 1 |
| `provenance` | `flow.py:375` builds entries | `[]result.ProvenanceEntry{}` `askwith.go:196`; the type is **never constructed** | `[]`; `provenanceEntry()` `result.ts:172` zero callers | **WIRE-ONLY** | no | 1 |
| `loop` (deep-ask signals) | `answer/agentic.py` | `Loop` always nil; `LoopSignals` `result.go:82` 0 callers, 0 tests | `loop: null` `result.ts:136`, builder has no option | **WIRE-ONLY** | no | — |
| `page` / `bbox` / `source_uri` / `translation` | `page`/`source_uri` set `flow.py:365-366`; **`bbox` never set in any port** | all nil | all null | **WIRE-ONLY** (`bbox` in all 3 — CLAUDE.md is right) | no | 1 |
| `Decision.partial` | — | `result.go:22`, never produced | `result.ts:17`, never produced | **WIRE-ONLY** in all three | no | 1 |
| `GraphEdge.relation` / `.confidence` | `graph/store.py:66` real | always nil `graph/graph.go:147-148` | always null `graph/graph.ts:106-107` | **WIRE-ONLY** | no | 1 |

² not a wrongness gap *because* the ports refuse whole instead — safe-but-lossy.

### 3c. DEAD-CODE — implemented, zero non-test callers, never runs

| Capability | Go | JS | Proof | A? |
|---|---|---|---|---|
| ⚡ **Atomic-claim segmentation** | `SplitClaims` `answer/segment.go:144` | `splitClaims` `answer/segment.ts:107` | grep for the identifier in each port returns **only the declaration + tests**. ⚡ Both split correctly when called by hand (§8.1 P5) — they are simply not wired. The gate runs on the whole answer (`askwith.go:167`, `answer.ts:94,247`) and `Claims` is always length ≤1 (`askwith.go:188-190`, `answer.ts:108,261`). | yes (lossy, not wrong) |
| ⚡ **Answer/passage language resolution** | `ResolveAnswerLanguage` `lang/lang.go:35` | `resolveAnswerLanguage` `lang/lang.ts:42` | Zero non-test callers. ⚡ Go's returns `"ta"` correctly when called (§8.1 P6); `askwith.go:48` uses `const answerLanguage = "en"` instead. | **yes** |
| **The entire ADR-0007 conflict table set** | `answer/conflict_tables.go:26-91` (8 symbols) | `gen/conflict_tables.ts:8-315` (7 tables) | **Zero callers — and in Go, zero tests too.** Byte-pinned to `conformance/conflict.json` but consumed by nothing. Currently *untracked* (in-flight work). | **yes** (misleads: looks shipped) |
| `unsupported_scripts` producer | `tokenize_v2.go:331` | `tokenize-v2.ts:274` | Zero callers; field hardcoded empty | **yes** |
| BM25 | `bm25/bm25.go:41` | `bm25/bm25.ts:34` | Zero non-test callers in either port | no |
| RRF (native copy) | `rrf/rrf.go:24` | `rrf/rrf.ts:19` | Zero non-test callers; both `@deprecated` in favour of the FFI core | no |
| Structure index | `structure/structure.go:133` | `structure/structure.ts:86` | Zero non-test callers | no |
| Co-mention graph | `graph/graph.go:75` | `graph/graph.ts:57` | Zero non-test callers; **uses v1 (ASCII-only) tokens** | no |
| EU-ID builders | `euid/euid.go:28,41` | `euid/euid.ts:130,137` | Zero non-test callers. Note `euid` carries a **second, duplicated copy of the chunker** (`euid.go:61-211`, `euid.ts:109`) that does not reuse `chunker.ChunkText` — and JS's euid copy uses a real lookbehind regex while `chunker.ts` deliberately avoids one, so **the two chunkers can drift within the same port**. | no |
| Search-language table | `lang.SearchLanguages()` `lang/codes.go:168` | `searchLanguageByCode` `lang/codes.ts:148` | Zero non-test callers | no |
| `TableNameFor` / `tableNameFor` | `storage/storage.go:68` | `storage/postgres.ts:34` | Go: zero non-test callers | no |
| v1 gate + v1 relevance | `gate/gate.go:82,113` | `gate/gate.ts:42,67` | Zero non-test callers ✅ (CLAUDE.md correct) | no |
| `PostgresTextSearch` (Go) | `storage/postgres_store.go:347` | — | Zero callers **and zero tests** | no |
| `PluginVersion` ×3 (Go) | `storage.go:49`, `:352`, `lance_adapter.go:28` | — | Zero callers, zero tests — nothing stamps a plugin version in Go | no |
| `TOKENIZER_VERSION` | `tokenize_v2.go:45` | `tokenize-v2.ts:34` | Zero callers — **nothing stamps a tokenizer version onto an index in either port**, so a v1-built index is indistinguishable from a v2 one | **yes** (silent corruption) |
| FFI core entry points | `core.Detect/ToMarkdown/Version/Fuse` `core/core.go:114,96,46,56` | — | Zero non-test callers in Go | no |

### 3d. MISSING — not present at all

| Capability | Python | Go | JS | A? | T |
|---|---|---|---|---|---|
| ⚡ **Conflict detection algorithm** | `answer/conflict.py:detect_conflict/find_conflicts` | **MISSING** (tables only) | **MISSING** (tables only) | **YES** | 1+2 |
| ⚡ **Near-duplicate collapse** | `collapse_near_duplicates`, `flow.py:277` | **MISSING** — only unread constants `conflict_tables.go:31-32` | **MISSING** — `grep dedup` = 0 | **YES** | 1 |
| **Authority selection** | `select_by_authority` `flow.py:252` | **MISSING** | **MISSING** | **YES** | 1 |
| **Drop-not-fail** | `flow.py:357-358` | **MISSING** (refuses whole) | **MISSING** | no (lossy) | 1 |
| **Retrieval engine / fusion on the ask path** | `retrieve/engine.py` | **MISSING** — `AskWith` takes `corpus []Doc` as an argument | **MISSING** | **yes** (no real retrieval to be wrong about) | 1 |
| Reranker | `retrieve/rerank.py` | **MISSING** by design (`contracts.go:18-20`) | **MISSING** by design (`contracts.ts:18-24`) | no | — |
| `search_languages` fan-out | `lang/search.py`, `client.py:713` | **MISSING** — `grep search_languages` = 0 hits | **MISSING** — 0 hits | no | 1 |
| `evaluate()` | `evaluate.py`, `client.py:884` | **MISSING** — 0 hits | **MISSING** — 0 hits | no | 1 |
| `reconcile()` / `remediate()` | `reconcile/`, `client.py:888,916` | **MISSING** | **MISSING** | **yes** (poisoned corpus goes unreconciled) | 1 |
| `delete()` / revoke | `delete.py`, `client.py:513` | **partial** — row-level `DeleteDocument` `storage.go:49`, `postgres_store.go:269`, `lance_adapter.go:98`; no facade verb, no manifest | **partial** — `core.ts:317`, `postgres.ts:216` | yes | 1 |
| Partitions / `allowed_partitions` | `access/prefilter.py`, `domain/partition.py` | **MISSING** — only a sanitized table-name string `storage.go:68`; `grep allowed_partition` = 0 | **MISSING** — `postgres.ts:34`; 0 hits | **YES** (tenant leakage) | 1 |
| `acl` | carried `domain/` | **MISSING** — `grep -i acl` = **0 hits** | **MISSING** — 0 hits | no³ | 1 |
| Conversation memory / `recall()` | `memory/store.py`, `client.py:945` | **MISSING** | **MISSING** | no | 1 |
| Streaming | `stream/answer.py`, `client.py:851` | **MISSING** — `grep -i stream` = 0 | **MISSING** — 0 hits | no | 1 |
| Wiki | `wiki/` | **MISSING** (1 comment) | **MISSING** | no | 1 |
| Deep-ask / agentic | `answer/agentic.py`, `client.py:660` | **MISSING** (type only) | **MISSING** (type only) | no | 1 |
| Vision | `vision/` (6 modules) | **MISSING** by design | **MISSING** by design | no | 3 |
| Language detection (pure) | `lang/detect.py` (+ heuristic default) | **FFI-only** `core.go:114`, tag-gated, 0 callers | **FFI-only** `core.ts:230`, subpath-only, 0 callers | **yes** | 3 |
| Ingest surfaces | `ingest/pipeline.py`, `rag.code`, `rag.schema`, `client.py:433,482,495` | **FFI-only** `ingest/ingest.go:63` | **FFI-only** `ingest/ingest.ts:50` | no | 3 |
| Storage backends | LocalFs + S3 + Lance + Postgres + manifests | Postgres ✅ + Lance (FFI) — **no S3, no manifest, no LocalFs** | Postgres ✅ + Lance (FFI) — same | yes | 1 |
| Provider contracts | **7** Protocols `contracts.py:83-192` | **3** `contracts/contracts.go:76,90,101` | **3** `contracts.ts:79,94,107` | no | — |
| Transport seam | `http.py:36` | `models/openai.go:16` | `models/openai.ts:20` | **PARITY** ✅ | no | — |
| Worker queue / DLQ / resume | `worker/` | **MISSING** | **MISSING** | no | 1 |
| Telemetry / cost | `telemetry/` | **MISSING** | **MISSING** | no | 1 |
| Provenance stamps / rebuild planner | `provenance/` | **MISSING** | **MISSING** | yes | 1 |

³ `acl` is not enforced anywhere, including Python — so its absence in the ports
costs nothing today. It is listed for completeness, not as a gap to close.

### 3e. Python-internal defects that make the "Python has it" column weaker than it looks

Several rows in 3d are marked "Python ✅". That verdict is correct but load-bearing
qualifications belong with it, or closing the port gaps will copy a defect.

| Defect | Where | Why it matters |
|---|---|---|
| ⚡ **Conflict detection is ASCII-only** | `answer/conflict.py:42` imports **v1** `tokenize`; used at `:188` and `:286` | v1 returns `[]` for any non-Latin script, so `MIN_CONTENT=3` (`conflict.py:88`) is never met and `detect_conflict` **silently returns "no conflict" for every non-English corpus**. The #1 harm in §7 is *unfixed in Python too* outside Latin script — it just fails quietly instead of visibly. Porting `conflict.py` as-is would triplicate that. |
| **The v1 tokenizer is still load-bearing in five more places** | `evaluate.py:79-80`, `memory/store.py:62,68`, `graph/store.py:179`, `graph/retrieve.py:37`, `wiki/store.py:321`, `wiki/retrieve.py:30,40-41`, `cli/cite_check.py:94,106,146` — all via `content_tokens` (**v1**, `verify.py:66`) | The gates and BM25 moved to v2; evaluation scoring, conversation recall, the graph and the wiki did not. On a non-Latin corpus they degrade to no-ops **silently** — the exact failure mode ADR-0011 was written to end. |
| ⚡ **Deep-ask cites the context model's blurb, not the source** | `tools.py:33` returns `"text": c.text` (the *contextualized* text) → pooled → emitted as `SourceRef.passage` at `answer/agentic.py:385` | This is precisely the defect commit `0697c41` ("cite the source's words, not the context model's blurb") fixed in `flow.py` by switching to `citable_text`. **The deep path was not fixed with it.** `strategy="deep"` can therefore attribute a model's situating sentence to the customer's document — a confidently wrong attribution, in Python, today. |
| **Deep-ask has no script gate** | `unsupported_scripts` is never called in `answer/agentic.py` | `strategy="deep"` always reports `unsupported_scripts=()`, so the ADR-0011 abstain-on-unclaimed-script guarantee does not hold on that path. |
| **`Decision.partial` is orphaned** | emitted only at `agentic.py:375`; `evaluate.py:54,58` counts it as neither answered nor refused; `client.py:731,766,829` treats it as a refusal | A partial answer is scored as nothing and reported as a refusal. |
| **Stale-index detection is dead** | `storage/manifest.py:165` `record_tokenizer_version` is called (`ingest/pipeline.py:245`); the read half — `tokenizer_manifest:174`, `TokenizerManifest.is_stale:156` — has **zero callers** | A v1-built index is written with a version stamp nobody ever reads, so it is never detected as stale. Matches the ports, which never stamp at all. |
| **`_PLACEHOLDER_VECTOR = [0.0]`** | `ingest/pipeline.py:72`, written at `:413` when no embedder is configured | A 1-dimension vector deliberately written into the index, with no guard anywhere that would later notice the dimension inconsistency. |
| **`worker/`, `provenance/`, `telemetry/cost`, `config/loader`, `plugins/registry` are unreachable** | `client.py:173` never passes `queue=`; no stamp is produced or read; `rag.use()` **does not exist** on `CiteNexus` | CLAUDE.md already flags the queue honestly. The others are not flagged. `Stage.verify` is never emitted, so `count_citation_failures` (`telemetry/counters.py:36`) and `groundedness_rate` (`:41`) are permanently `0`. |
| **`.png` / `.jpg` / `.yaml` / `.json` paths get `PlainExtractor`** | `extract/dispatch.py:38` — `ImageExtractor` and `SchemaOpenapiExtractor` are in `_BY_SOURCE_TYPE` only, not the extension map | Silent wrong-extractor selection on a file path. |

---

## 4. Reverse gaps — where Python is NOT the superset

This is the section the prompt was right to demand. Python is the reference for
*orchestration*; it is the **weakest** port for *input validation*.

| Capability | Go | JS | Python | Verdict |
|---|---|---|---|---|
| ⚡ **Vector arity check** (N texts must yield N vectors) | `contracts.EmbedTexts` `contracts/contracts.go:120` — errors | `embedTexts` `contracts.ts:158` — throws | **NONE.** `contracts.py:210` returns whatever the provider gave; `embed/batcher.py:28` blindly `extend`s. ⚡ Proven: 2 texts → 1 vector, no error (§8.3). | **MISSING in Python — silent index corruption** |
| ⚡ **Empty-vector rejection** | `CheckVector` `contracts/contracts.go:203` | `checkVector` `contracts.ts:223` | **NONE** ⚡ (§8.3) | **MISSING in Python** |
| ⚡ **Dimension-consistency check** | `contracts.go:207` | `contracts.ts:226` | **NONE** ⚡ | **MISSING in Python** |
| **All-zero-vector rejection** | `contracts.go:212` + `IsZeroVector` `:178` | `contracts.ts:234` + `isZeroVector` `:198` | **NONE** (only doc comments at `contracts.py:33,101` *asking* providers to behave) | **MISSING in Python** |
| ⚡ **Non-finite (NaN/Inf) rejection** | **MISSING** ⚡ — `CheckVector` has three rejections, NaN passes (§8.3 P11) | ✅ `contracts.ts:231` | **NONE** | **Go↔JS divergence** — two ports that are supposed to be byte-identical disagree on what a valid vector is |
| **Non-array / non-number type guard** | implicit (typed) | ✅ `contracts.ts:219` `TypeError` | n/a | JS-only, correctly |
| **Fail-closed all-or-nothing ingest** | ✅ `ingest/ingest.go:53-62` — writes nothing on any failure | ✅ `ingest/ingest.ts:40-48,90` — single upsert after the loop | partial (`ingest/pipeline.py`) | ports stronger |
| **`Ask` panics rather than abstains on an impossible internal error** | ✅ `answer/answer.go:54` — refuses to hide a broken flow behind a safe default | — | — | Go-only; a good pattern worth lifting |

There is also a **contract violation in Go's own model client**:
`models/openai.go:98-100` returns `("", nil)` when `choices` is empty — an empty
answer reported as success — directly contradicting its own contract doc
(`contracts/contracts.go:47-49,88-89`: "MUST error"). JS does not have this bug.

---

## 5. Conformance coverage — what is actually pinned

Verified against the loaders (`golang/internal/conform/conform.go:25,37`,
`js/src/conform/fixtures.ts:14,19`) and every consuming test.

**Structural asymmetry:** Python does not *replay* most vectors — it **generates**
them (`python/scripts/gen_conformance.py:1334-1359`) and asserts regeneration
equality (`python/tests/test_conformance_fixtures.py:30-41`). So for most vectors,
Python's "coverage" is *"the reference still emits this"*, not *"the reference
still obeys this"*. That is a weaker guarantee than Go's and JS's, and it means a
Python behaviour change that also changes the generator is invisible.

| Vector | Go | JS | Python | Note |
|---|---|---|---|---|
| `cases/conflict.json` | ❌ | ❌ | ✅ `tests/answer/test_conflict_conformance.py:28` | **Python-only** — nothing to replay in the ports |
| `cases/vision_orchestration.json` | ❌ | ❌ | ❌ | **ZERO consumers in any language.** Generated, documented (`conformance/README.md:25`), replayed by nobody |
| `conformance/prompts.json` | ❌ | ❌ | ❌ | **ZERO consumers.** Go (`models/openai.go:18`) and JS (`models/openai.ts:26`) each hardcode `SYSTEM_PROMPT` with a *comment* citing this file. **"Byte-identical prompts" is asserted nowhere.** The grounded-answer prompt is on the answer path. |
| `cases/model_wire.json` | ✅ | ✅ | ❌ | The one vector the *reference* does not check itself against |
| `cases/faithful.json` | ✅ | ✅ | CLI only (`tests/cli/test_verify.py:20`) | |
| `cases/rrf.json` | ✅ | ✅ | ✅ | Only 4-language vector (incl. Rust) |
| tokenize, tokenize_v2, bm25, chunker, faithful_v2, segmentation, language, languages, eu_ids, e2e_hermetic, result_roundtrip, graph_comention, structure, multilingual | ✅ | ✅ | generator-only (3 exceptions replay) | |

### The unpinned table — a real answer-path drift risk

| Embedded copy | Canonical source | Byte-pin test |
|---|---|---|
| `golang/gate/polarity.json` | `conformance/polarity.json` | ✅ `gate/verify_v2_test.go:94` |
| `golang/answer/segmentation.json` | `conformance/segmentation.json` | ✅ `answer/segment_test.go:44` |
| `js/src/gen/tables.ts` (all tables) | conformance/ via `js/scripts/gen-tables.mjs` | ✅ `gen/tables.test.ts:23,27,31,39` |
| **`golang/gate/stopwords.json`** | `conformance/stopwords.json` | ❌ **NONE.** Only three `conform.Data` calls exist in all of `golang/` (conflict, segmentation, polarity) — stopwords is not one of them. |
| **`python/.../answer/verify.py:16` `_STOPWORDS`** | `conformance/stopwords.json` | ❌ **NONE** — a hand-maintained `frozenset`. **ADR-0010's own consequence list (lines 125-127) scheduled this for conversion; it has not happened.** |

I diffed all three by hand: **currently identical, 44 words, no drift today.**
But the stopword set feeds `ContentTokens` → the *relevance gate* on the answer
path, and two of three ports have no guard against it drifting.

---

## 6. Rust core and CI — the untested surface

- 16 `citenexus_*` exports in `rust/src/ffi.rs` (`:38`–`:381`).
- **Python cannot reach Rust at all** in the shipped package — `grep ctypes python/src` is empty; bindings exist only in `python/tests/core/`. The core is a *parity arbiter* for Python, not a runtime dependency.
- **Go** reaches the full surface behind `//go:build citenexus_ffi` — but `grep citenexus_ffi .github/` is **empty**, so `golang/core`, `golang/ingest` and `golang/storage/lance_adapter.go` are **never compiled in CI**. Largest untested surface in the repo.
- **JS** is the only port whose published artifact can reach Rust (koffi, `optionalDependencies`, subpath `./ffi`).
- **There is no cross-port CI job that runs one vector in all three ports.** `ports-ci.yml` runs Go/TS/Rust as three independent parallel jobs; Python's generator guard lives in a different workflow (`ci.yml`). Nothing joins or compares them.
- `python/Taskfile.yml:71` `core:test` (the Python↔Rust parity suite) is **not in `task check` and not called by any workflow** — it is local-only, and `tests/core` silently skips when the dylib is absent (`test_rust_parity.py:45-47`).

---

## 7. Gaps ranked by user harm

Ordering rule applied: *a port emitting a confident, correctly-cited, wrong or
unflagged answer* > *a silently corrupted index* > *a loud failure* > *a missing
convenience*. Abstaining is never a harm.

| # | Gap | Ports | Why it ranks here |
|---|---|---|---|
| **1** | ⚡ **Conflict detection absent** — contradicting evidence answered confidently, `conflicts: []`, and the contradicting passage **counted as a supporting source** | Go, JS | The only gap proven to produce a confident, correctly-cited, unflagged wrong answer (§8.2). Python abstains on the identical input. Ships *dead tables* that make it look present. |
| **2** | ⚡ **Near-duplicate collapse absent** — 3 clones report `supporting_sources: 3, distinct_documents: 3`; Python reports `1, 1` | Go, JS | Not a wrong answer but a **wrong confidence signal**, and it is the corroboration number a caller trusts. A poisoned corpus (the 5th failure class) is *rewarded* by it: inject N copies and the answer looks N-times corroborated. |
| **3** | ⚡ **Python has no embedding-vector validation** — wrong arity, empty, ragged, NaN all accepted silently | **Python** | Silently corrupted index, no loud failure. Wrong arity is the worst: it shifts every subsequent text→vector pair, so the index is *plausibly* wrong forever. Go and JS both catch it. |
| **3b** | ⚡ **`strategy="deep"` cites the context model's blurb as the source's words** — `tools.py:33` (`c.text`) → `agentic.py:385` | **Python** | A confidently wrong *attribution*: the customer's document is quoted saying something a model wrote. Identical in kind to the defect commit `0697c41` fixed in `flow.py` and did not fix here. Ranks with the wrongness tier, not the feature tier. |
| **3c** | **Python's conflict detection is ASCII-only** — `conflict.py:42` imports v1 `tokenize` | **Python** | The #1 gap is silently unfixed in the reference too, for every non-Latin corpus: v1 yields `[]`, `MIN_CONTENT=3` is never met, and `detect_conflict` returns "no conflict" without saying it could not look. **Port `conflict.py` as-is and this triplicates.** |
| **3d** | **No partition or ACL enforcement in any port** — `access/prefilter.py` has zero callers; `allowed_partitions` (`config/schema.py:282`) is read by nothing | **all three** | A multi-tenant caller who set `allowed_partitions` believes they are isolated and is not. Cross-tenant evidence can reach an answer. Ranks here because it is silent and the doc actively asserts the opposite (§1a). |
| **4** | **Authority floor absent** — nothing stops a non-authoritative source answering | Go, JS | The measured Texas→Florida failure class, unguarded. Ranks below 1-2 only because the ports have no real retrieval to pull a wrong-jurisdiction source *from* yet — it becomes #1 the moment they get a facade. |
| **5** | ⚡ **`passage_language` / `languages_in_evidence` hardcoded `"en"`**, `unsupported_scripts` hardcoded `[]` | Go, JS | A **false statement in a populated field** about non-English evidence. The ADR-0011 abstain-on-unclaimed-script guarantee is structurally unreachable, and both ports contain the working resolver + detector, uncalled. |
| **6** | **`allowed_partitions` / partition tree absent** | Go, JS | Tenant isolation is Python-only. A port user has no isolation primitive at all — only a sanitized table name. |
| **7** | **`TOKENIZER_VERSION` never stamped** | Go, JS (and unverified in Python) | A v1-built index is indistinguishable from a v2 one, so a stale index is queried with the wrong tokenizer and silently under-retrieves. |
| **8** | **`prompts.json` pinned by nobody** | all three | The grounded-answer prompt is on the answer path and its cross-port identity is asserted by comment only. Drift here changes answers everywhere with no test failing. |
| **9** | **Stopword table unpinned in Go and Python** | Go, Python | Feeds the relevance gate. Identical today; nothing keeps it so. ADR-0010 already ordered the Python fix (lines 125-127) and it was not done. |
| **10** | **Go `CheckVector` misses non-finite; JS catches it** | Go | Two "byte-identical" ports disagree on vector validity. NaN propagates into cosine and ranks nondeterministically. |
| **11** | **Go `models/openai.go:98` returns `("", nil)` on empty `choices`** | Go | Contract violation against its own doc; an empty answer wearing the costume of success. |
| **12** | **Atomic-claim decomposition + drop-not-fail absent** | Go, JS | ⚡ Proven: ports **refuse whole** where Python returns the true half. Lossy, never wrong — so it ranks *below* every wrongness gap despite being the most-cited parity gap in CLAUDE.md. |
| **13** | **`reconcile()` / `remediate()` / manifests absent** | Go, JS | No way to detect a poisoned or drifted corpus. Loud-failure-adjacent: the harm needs an attacker. |
| **14** | **No retrieval pipeline, no facade** | Go, JS | The largest amount of *work*, but the smallest *harm*: a capability you cannot invoke cannot lie to you. Listed last deliberately — it is a scope finding, not a safety finding. |
| **15** | Streaming, wiki, deep-ask, memory, evaluate, vision, worker, telemetry | Go, JS | Missing conveniences. No harm. |

### Two structural fixes that are cheap and outrank most of the list

- **Wire what already exists.** `SplitClaims`, `resolveAnswerLanguage`,
  `unsupportedScripts` and the conflict tables are all written, tested and
  pinned in both ports. Gaps 5 and 12 and half of 1 are *call-site* work, not
  algorithm work.
- **Make WIRE-ONLY unrepresentable.** Every field in 3b is a lie a consumer
  cannot detect. Until a port computes one, it should be **absent from the JSON**
  (or explicitly `null`), never `[]`/`""`/`false`/`true`. `all_claims_verified:
  true` from a port with no claim decomposition is the sharpest example.

---

## 8. Execution evidence

All probes fed **identical inputs** to a Go module (`replace` → `golang/`), Node
against `js/dist`, and the Python `AnswerFlow` directly.

### 8.1 Atomic claims — ports refuse whole, Python drops the false half

Passage: `"The tenant must give thirty days notice. The landlord must return the deposit."`
Generated: `"The tenant must give thirty days notice. The landlord must keep the deposit forever."`

| | answer | decision | `unsupported_claims_removed` | claims |
|---|---|---|---|---|
| Python | `"The tenant must give thirty days notice."` | answered | **1** | 2 (one `supported: false`) |
| Go | refusal | **refused** | 0 | 0 |
| JS | refusal | **refused** | 0 | 0 |

`SplitClaims` / `splitClaims` called by hand on the same string returns the correct
two claims in both ports — the capability works, it is not invoked.
`lang.ResolveAnswerLanguage(&Detection{Language:"ta", IsReliable:true}, ...)`
returns `"ta"` — likewise working, likewise not invoked.

### 8.2 ⚡ Conflict — the #1 finding

Corpus: `a = "The employee may disclose the information."`,
`b = "The employee may not disclose the information."` · Question: `"employee disclose information"`

| | answer | decision | conflicts | `conflicts_detected` | `supporting_sources` |
|---|---|---|---|---|---|
| Python | *"The available evidence disagrees, so I can't answer that."* | **refused** | `("negation: a vs b (0 vs 1 negations)",)` | **1** | — |
| Go | **"The employee may disclose the information."** | **answered** | `[]` | **0** | **2** |
| JS | **"The employee may disclose the information."** | **answered** | `[]` | **0** | **2** |

Near-duplicate (3 byte-identical docs): Python `supporting_sources: 1,
distinct_documents: 1`; Go and JS both `3, 3`.

Non-English (Tamil passage, Tamil answer): Python `passage_language: "ta"`,
`languages_in_evidence: ["ta"]`; Go and JS both `"en"` / `["en"]`.

**Scope note, stated so it is not overclaimed:** Python's detector is
polarity/value-based. On `"thirty days"` vs `"sixty days"` (spelled out) it also
reports `conflicts_detected: 0` — it fires on `"30"` vs `"60"` (numeric, rule
`value`) and on negation, not on spelled-out numerals. Python is better here, not
complete.

### 8.3 ⚡ Embedding-vector validation

| input | Go `CheckVector` | JS `checkVector` | Python |
|---|---|---|---|
| empty vector | ❌ rejects | ❌ rejects | **accepts** |
| dimension mismatch | ❌ rejects | ❌ rejects | **accepts** |
| **NaN** | **accepts** | ❌ rejects | **accepts** |
| all-zeros | ❌ rejects | ❌ rejects | **accepts** |
| **2 texts → 1 vector** | ❌ rejects (`EmbedTexts`) | ❌ rejects (`embedTexts`) | **accepts** |

Go's message on arity: *"contracts: embedder returned 1 vectors for 2 texts; the
contract is one vector per input text, in input order."* Python returns the
one-element list and carries on.

### 8.4 ⚡ Cross-port determinism — the good news

- **Tokenizer v2**, 12 adversarial inputs (Turkish `İ`, `Straße`/`STRASSE`, NFC/NFD `naïve`, Japanese, Balinese, Khmer, `p50 500mg 2019 3.14`, `क्ष`, `école`, Roman numerals, emoji, fullwidth): **12/12 byte-identical across Python, Go, JS. 0 divergences.**
- **Gate v2**, 8 adversarial pairs (negation deletion, role inversion, value swap, CJK, `Straße`, gap-budget boundary, case-fold, identifier): **`[F,F,F,T,T,F,T,T]` in all three.**
- **Relevance v2**: identical in all three.
- **BM25**: Go and JS scores identical to 1e-6 (`1.37365`, `1.189587`).
- **RRF**: identical. **Chunker**: identical, including newline handling.

CLAUDE.md's core parity claim is **true and now execution-verified**, not merely
fixture-asserted.

---

## 9. Reproducing this

```bash
# Go: module with `replace github.com/muthuishere/citenexus/golang => ./golang`
# JS: node --input-type=module against js/dist/index.js
# Python: cd python && uv run python <probe>   (AnswerFlow + Candidate directly)
```

Probe scripts were written to the session scratchpad, not the repo. Nothing in
this audit modified tracked source; the only file written is this one.
