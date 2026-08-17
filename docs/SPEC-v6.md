# CiteNexus Specification (v6)

> Evidence-first, multilingual, S3-native evidence-integrity layer over retrieval, for domains where hallucination is unacceptable. (Script coverage is explicit and fixture-backed — see §11a Script Support. **14 scripts, at parity across Python, Go and JS** since ADR-0011 + 0.10.1.)
> v2 resolved the review issues: dead graph backend removed, graph persisted on LanceDB, `retrieve()` exposed, scalar confidence replaced with structured signals, entity resolution added, two-speed update model made explicit, community/wiki layer committed, multilingual lexical search fixed, conflict semantics defined, vision made conditional.
> v3 added (S3-native): a document-structure retrieval signal, and a deferred-RBAC `acl` field on every Evidence Unit (carried, not enforced).
> **v3.1 makes the tenancy model hierarchical and physical — org → product line → product, each a separate partition — and adds an explicit performance model. Partitioning is the isolation boundary *and* the primary latency lever. Final RBAC enforcement is delegated to an external store the operator manages (Postgres or other DB); the library stays S3-pure, carries the hierarchy tags + `acl`, and consumes an allowed-partitions set as a hard pre-filter.** Still deliberately *not* adopted: stop controller, in-loop conflict weighing, in-library RBAC engine, LibreChat citation path.
> **v3.2 generalizes the structure signal: structure is best-effort and source-type-aware (heading tree, code AST, slide sequence, table schema, thread order, or *none*) — never assumed to be a tree, optional per document, and degrades to nothing without blocking retrieval.**
> **v4 hardens the framework for production and extensibility without touching the core architecture: plugin protocol layer; per-artifact versioning + partial rebuild; background worker / queue / retry / DLQ / resume; unified telemetry + cost; provenance chain on every answer; conversation memory; LLM-as-judge (online+offline, audit-tracked); streaming (token in normal, sentence-gated in strict). Knowledge Unit renamed to Evidence Unit (EU). Dropped multi-pipeline `strategy=` presets.**
> **v5 adds the sixth retrieval signal — an LLM-derived wiki/navigation layer (the "compile sources into cross-referenced pages + index, navigate then read" idea, credited to Andrej Karpathy's LLM-Wiki) — reimplemented S3/Lance-native, not filesystem-based, with a navigate-not-cite rule that resolves every wiki hit down to bbox-cited EUs. Disambiguated from graph community summaries. Adds a `lint` maintenance pass and a backend-agnostic store seam. And it reworks the public API for a DHH-style convention-over-configuration surface: `pip install` → ingest → answer in a few lines, conversation-id native, defaults that just work, depth available but never required. Bakes in the **answer-language invariant**: the answer is always returned in the query's language (enforced, regenerate-on-mismatch — not configurable away), while citations stay verbatim in the source language.**
> **v6 consolidates the public surface to three verbs — `client` (construct, with a `signals=[...]` capability declaration), `ingest` (any input type — pdf/docx/pptx/image/txt/html/md/csv or raw plain content; sync or async), and `ask` (grounded, optionally streamed, conversation-native) — plus `evaluate(csv)` → score. The client declares which of the six signals it uses (ingest builds and ask queries only those); an optional `citenexus.validate.yaml` allow-list warns (never errors) on divergence. Language detection is now a defined method (fastText lid.176 + confidence threshold + fallback chain, §11a), not an assumption. All three verbs plus evaluate are fully audited.**

**Terminology:** the atomic retrievable object is the **Evidence Unit (EU)**. The system is evidence-first end to end: Evidence Units → Evidence Retrieval → Evidence Verification → Evidence Signals → provenance-chained Answer. ("Knowledge graph" keeps its industry name; EUs feed it.) The retrieval layer fuses **six signals**: embedding (dense), lexical (sparse), graph, graph-community, structure, and wiki-navigation (§10b) — all resolving to citable EUs.

---

> **Reading order.** The `v2`–`v6` paragraphs above are **revision history** — they
> record what each spec revision added, in the words of the day, and some of it has
> since been superseded. Where they disagree with the numbered invariants below or
> with an ADR, the **invariants and the ADRs win.** In particular: `v5`'s
> "the answer is always returned in the query's language" is superseded by
> invariant 4 (it is the *caller-stated* language, down a four-rung chain), and
> "bbox-cited EUs" describes the intended contract, not the shipped one — see the
> implementation gap under invariant 1. ADRs 0004, 0007, 0008, 0009, 0011, 0012,
> 0013 and 0014 post-date this document and govern current behaviour.
>
> NOTE: This file is the verbatim reference specification (v6) for CiteNexus. It is
> the source of truth for *what* behavior ships. The build plan, conventions, and
> layer ordering (*how* we build it) live in `CLAUDE.md`. OpenSpec change proposals
> under `openspec/changes/` carve incremental delta-specs out of the sections below;
> on archive they fold into the living spec under `openspec/specs/`.
>
> The full section-by-section text (§1–§23) is reproduced from the approved v6
> document. Sections are referenced throughout the codebase and OpenSpec changes by
> their numbers (e.g. §4c rebuild matrix, §7 Evidence Unit, §9 vision decision table,
> §11a language detection, §15 three-verb API, §16 Result object, §20b judge).

See the project root conversation / approved v6 document for the complete prose of
each section. Key invariants the implementation MUST hold (do not drift from these):

1. **No ungrounded claim.** Every claim in an answer resolves to a cited Evidence
   Unit; unsupported claims are dropped by the always-on faithfulness gate (§11).
   Since ADR-0009 the gate is **per atomic claim** — ordered, gap-bounded
   containment with a polarity guard, drop-not-fail — because plain set
   containment is closed under reordering and deletion and accepted **9 of 9**
   adversarial false answers in all three implementations.
   *Implementation gap:* the spec says bbox-cited and `bbox` **is** captured at
   extraction, but nothing on the answer path carries it onto `Result.sources`,
   so `SourceRef.bbox` is always `None` (`answer/result.py:101`). Citations
   resolve to **document + page** today. Do not document bbox citations until
   this closes.
2. **No evidence ⇒ no answer.** Weak/missing/conflicting/unauthorized evidence ⇒ refuse
   or state uncertainty; strict mode gates on structured evidence signals (§12, §14).
   Conflict is **detected deterministically and surfaced, never resolved** — strict
   mode abstains citing both sides (ADR-0007). Authority is a **curator assertion
   supplied at ingest**, never inferred from prose, applied after grounding and
   before generation, and **unranked by default** (ADR-0004).
2b. **Open gap — subject scope (ADR-0012, *proposed*).** Invariants 1 and 2 do not
   yet cover *applicability*: chunking severs a precondition from the operative
   rule it governs, so **8 of 11 operative EUs are citable without the clause that
   governs them** (73% severance). Such an answer is verbatim, correctly cited,
   passes the gate, clears the authority floor — and still does not govern the
   question. This is stated as open, not solved.
3. **S3 is the source of truth; all indexes are rebuildable caches** (§2). Every artifact
   carries a `produced_by` provenance stamp; a model/plugin swap rebuilds only stale
   layers per the dependency DAG (§4c).
4. **Answer-language invariant** (§11): the answer is returned in the **caller-stated**
   language, enforced by regenerate-on-mismatch; citations stay **verbatim** in the
   source language, never translated in place. *Stated precisely* — it resolves down a
   four-rung chain: explicit `answer_language="xx"` → `"auto"` (detects the language
   of the **question**, per §11a) → the conversation's language →
   `default_answer_language` (`"en"`). **Unset is a fixed default, not an inference
   from the query.** Because verbatim wins, an English answer can carry a Telugu
   citation; read `sources[*].passage_language` for the script actually returned.
   Which language you **search** in is a separate knob (`search_languages`,
   ADR-0013) and the evidence votes on neither.
5. **Six fused retrieval signals**, all resolving to citable EUs; wiki & community hits
   resolve **down** to their EUs before citation (navigate-not-cite, §10b).
6. **Everything is a typed plugin** with a `plugin_version`; built-ins are plugins too;
   fusion + grounding stay in core so a third-party retriever can't bypass the guarantees (§4b).
7. **Three-verb public surface** — `client(signals=[...])`, `ingest`, `ask` — plus
   `evaluate(csv)`; strict mode is the default (opt *down*); `conversation_id` is the only
   state the caller carries (§15). All four are fully audited (§20b).
   **`ingest` is synchronous — there is no `ingest_async`, in any port.** The
   durable worker queue buys *durability* (retry/backoff, DLQ,
   idempotent-by-hash, resume), not concurrency, and is not reachable from the
   `CiteNexus` constructor. Shipped since v6 was written and part of the surface:
   `retrieve`, `stream`, `recall`, `delete`, `reconcile`/`remediate` (ADR-0008),
   and the typed structural verbs `rag.code` / `rag.schema`.
7b. **The model seam is a transport, not an endpoint** (ADR-0014). Models are
   injected; the documented way to bring one is to keep the shipped client and
   swap `transport=` — a keyword-only `Callable[[str, bytes, dict[str, str]], bytes]`,
   with tri-port equivalents in Go and JS. The seven Protocols in
   `citenexus.contracts` are the escape hatch for models that cannot be made
   OpenAI-shaped. Auth is `${ENV}`-in-headers, expanded only at the HTTP
   boundary; a key value never enters a constructor.
8. **Physical partitioning** by a declared, variable-depth hierarchy; isolation by partition
   selection; finer authorization delegated to an external operator-managed store, consumed
   as a hard `allowed_partitions` pre-filter (§6b, §7c).

**§11a Script Support — what "multilingual" means today.** The per-script support
matrix below is part of §11a. A script is *supported* only where an answer in
that script can pass the faithfulness gate; every other script abstains **by
name**. The rule that governs this table has not changed and must not be relaxed:
**no script may be listed as supported until it has a golden conformance
fixture.** The claimed set is defined once and shared —
`python/src/citenexus/tokenize.py:214-231`, `golang/tokenize/scripts.json`,
`js/src/gen/tables.ts:141-155`, all generated from / checked against
`conformance/cases/tokenize_v2.json`.

**14 scripts are claimed, and at parity in Python, Go and JavaScript** since the
Unicode tokenizer v2 landed (ADR-0011) and the ports' `ask` path was corrected to
call the v2 predicate (0.10.1):

| Script | Languages | Status |
| --- | --- | --- |
| Latin | English, Dutch, German, French, Spanish, Portuguese, Italian, … | supported |
| Cyrillic | Russian, Ukrainian, … | supported |
| Greek | Greek | supported |
| Arabic | Arabic | supported |
| Hebrew | Hebrew | supported |
| Devanagari | Hindi, Marathi, … | supported |
| Bengali | Bengali | supported |
| Tamil | Tamil | supported |
| Telugu | Telugu | supported |
| Han | Chinese | supported — character bigrams (space-less) |
| Hiragana | Japanese | supported — character bigrams (space-less) |
| Katakana | Japanese | supported — character bigrams (space-less) |
| Hangul | Korean | supported |
| Thai | Thai | supported — character bigrams (space-less) |
| Khmer, Lao, Myanmar, Georgian, Armenian, Kannada, Malayalam, Gujarati, Sinhala | — | **deliberately not claimed** — abstains |

Space-less scripts are indexed by **character bigrams**, which do not cross script
boundaries. The unclaimed scripts are unclaimed on purpose: the bigram path
mechanically "works" for several of them, and answering through an unfixtured
segmentation is worse than refusing. *"I cannot read this script"* is a better
answer than a plausible ranking.

An unclaimed script produces **zero tokens** (`tokenize.py:277-278` drops the run)
and the question refuses before a model call is spent (`answer/flow.py:204-211`);
candidates carrying an unclaimed script are blocked and never citable
(`flow.py:194-195`). This is reported through
`EvidenceSignals.unsupported_scripts` (`answer/result.py:75`) — a **capability
signal, never an evidence judgement**. A refusal carrying a non-empty value there
means "I cannot read this script", which is a different thing from "the evidence
isn't there"; conflating the two is exactly what let the ASCII-only tokenizer
hide. Invariant 1 ("no ungrounded claim") holds either way.

Background:
[`adr/0011-tokenizer-and-non-latin-scripts.md`](adr/0011-tokenizer-and-non-latin-scripts.md).
Making a script *citable* is not the same as making it *reachable*: an English
question does not retrieve a Tamil passage unless it is also **searched** in
Tamil — see [`adr/0013-multilingual-search-fanout.md`](adr/0013-multilingual-search-fanout.md)
(`search_languages`, Python facade only). Both are required; neither is sufficient.

The numbered sections (§1 Product Goal · §2 Core Principles · §3 Design Rationale ·
§4 Architecture · §4b Plugins · §4c Artifact Versioning & Partial Rebuild · §5 Two-speed
update · §5b Worker/Queue/Resume · §6b Partitioning/Tenancy/Performance · §6c Telemetry &
Cost · §7 Evidence Unit · §7b Structure Index · §7c RBAC-ready · §8 Ingestion · §9
Conditional Vision · §10 Retrieval · §10b Wiki-Navigation · §11 Answer Flow · §11a Language
Detection · §12 Evidence Signals · §13 Conflict Model · §14 Trust Modes · §15 API ·
§16 Result · §16b Memory · §16c Streaming · §17 Configuration · §18 Modules · §19 CLI ·
§20 Evaluation · §20b Judge · §21 MVP Scope · §22 Non-Goals · §23 Positioning) are the
authoritative breakdown. Each OpenSpec change names the section(s) it implements.
