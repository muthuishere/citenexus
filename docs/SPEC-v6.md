# TrustRAG Specification (v6)

> Evidence-first, multilingual, S3-native RAG for domains where hallucination is unacceptable.
> v2 resolved the review issues: dead graph backend removed, graph persisted on LanceDB, `retrieve()` exposed, scalar confidence replaced with structured signals, entity resolution added, two-speed update model made explicit, community/wiki layer committed, multilingual lexical search fixed, conflict semantics defined, vision made conditional.
> v3 added (S3-native): a document-structure retrieval signal, and a deferred-RBAC `acl` field on every Evidence Unit (carried, not enforced).
> **v3.1 makes the tenancy model hierarchical and physical — org → product line → product, each a separate partition — and adds an explicit performance model. Partitioning is the isolation boundary *and* the primary latency lever. Final RBAC enforcement is delegated to an external store the operator manages (Postgres or other DB); the library stays S3-pure, carries the hierarchy tags + `acl`, and consumes an allowed-partitions set as a hard pre-filter.** Still deliberately *not* adopted: stop controller, in-loop conflict weighing, in-library RBAC engine, LibreChat citation path.
> **v3.2 generalizes the structure signal: structure is best-effort and source-type-aware (heading tree, code AST, slide sequence, table schema, thread order, or *none*) — never assumed to be a tree, optional per document, and degrades to nothing without blocking retrieval.**
> **v4 hardens the framework for production and extensibility without touching the core architecture: plugin protocol layer; per-artifact versioning + partial rebuild; background worker / queue / retry / DLQ / resume; unified telemetry + cost; provenance chain on every answer; conversation memory; LLM-as-judge (online+offline, audit-tracked); streaming (token in normal, sentence-gated in strict). Knowledge Unit renamed to Evidence Unit (EU). Dropped multi-pipeline `strategy=` presets.**
> **v5 adds the sixth retrieval signal — an LLM-derived wiki/navigation layer (the "compile sources into cross-referenced pages + index, navigate then read" idea, credited to Andrej Karpathy's LLM-Wiki) — reimplemented S3/Lance-native, not filesystem-based, with a navigate-not-cite rule that resolves every wiki hit down to bbox-cited EUs. Disambiguated from graph community summaries. Adds a `lint` maintenance pass and a backend-agnostic store seam. And it reworks the public API for a DHH-style convention-over-configuration surface: `pip install` → ingest → answer in a few lines, conversation-id native, defaults that just work, depth available but never required. Bakes in the **answer-language invariant**: the answer is always returned in the query's language (enforced, regenerate-on-mismatch — not configurable away), while citations stay verbatim in the source language.**
> **v6 consolidates the public surface to three verbs — `client` (construct, with a `signals=[...]` capability declaration), `ingest` (any input type — pdf/docx/pptx/image/txt/html/md/csv or raw plain content; sync or async), and `ask` (grounded, optionally streamed, conversation-native) — plus `evaluate(csv)` → score. The client declares which of the six signals it uses (ingest builds and ask queries only those); an optional `trustrag.validate.yaml` allow-list warns (never errors) on divergence. Language detection is now a defined method (fastText lid.176 + confidence threshold + fallback chain, §11a), not an assumption. All three verbs plus evaluate are fully audited.**

**Terminology:** the atomic retrievable object is the **Evidence Unit (EU)**. The system is evidence-first end to end: Evidence Units → Evidence Retrieval → Evidence Verification → Evidence Signals → provenance-chained Answer. ("Knowledge graph" keeps its industry name; EUs feed it.) The retrieval layer fuses **six signals**: embedding (dense), lexical (sparse), graph, graph-community, structure, and wiki-navigation (§10b) — all resolving to citable EUs.

---

> NOTE: This file is the verbatim reference specification (v6) for TrustRAG. It is
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

1. **No ungrounded claim.** Every claim in an answer resolves to a bbox-cited Evidence
   Unit; unsupported claims are dropped by the always-on faithfulness gate (§11).
2. **No evidence ⇒ no answer.** Weak/missing/conflicting/unauthorized evidence ⇒ refuse
   or state uncertainty; strict mode gates on structured evidence signals (§12, §14).
3. **S3 is the source of truth; all indexes are rebuildable caches** (§2). Every artifact
   carries a `produced_by` provenance stamp; a model/plugin swap rebuilds only stale
   layers per the dependency DAG (§4c).
4. **Answer-language invariant** (§11): the answer is returned in the query's language
   (auto-detected per §11a, or explicit override), enforced by regenerate-on-mismatch;
   citations stay **verbatim** in the source language, never translated in place.
5. **Six fused retrieval signals**, all resolving to citable EUs; wiki & community hits
   resolve **down** to their EUs before citation (navigate-not-cite, §10b).
6. **Everything is a typed plugin** with a `plugin_version`; built-ins are plugins too;
   fusion + grounding stay in core so a third-party retriever can't bypass the guarantees (§4b).
7. **Three-verb public surface** — `client(signals=[...])`, `ingest`, `ask` — plus
   `evaluate(csv)`; strict mode is the default (opt *down*); `conversation_id` is the only
   state the caller carries (§15). All four are fully audited (§20b).
8. **Physical partitioning** by a declared, variable-depth hierarchy; isolation by partition
   selection; finer authorization delegated to an external operator-managed store, consumed
   as a hard `allowed_partitions` pre-filter (§6b, §7c).

The numbered sections (§1 Product Goal · §2 Core Principles · §3 Design Rationale ·
§4 Architecture · §4b Plugins · §4c Artifact Versioning & Partial Rebuild · §5 Two-speed
update · §5b Worker/Queue/Resume · §6b Partitioning/Tenancy/Performance · §6c Telemetry &
Cost · §7 Evidence Unit · §7b Structure Index · §7c RBAC-ready · §8 Ingestion · §9
Conditional Vision · §10 Retrieval · §10b Wiki-Navigation · §11 Answer Flow · §11a Language
Detection · §12 Evidence Signals · §13 Conflict Model · §14 Trust Modes · §15 API ·
§16 Result · §16b Memory · §16c Streaming · §17 Configuration · §18 Modules · §19 CLI ·
§20 Evaluation · §20b Judge · §21 MVP Scope · §22 Non-Goals · §23 Positioning) are the
authoritative breakdown. Each OpenSpec change names the section(s) it implements.
