# CiteNexus Authority-Weighting Specification v1

> Grounding proves an answer is **present** in a cited source. It does not prove
> the source has the **standing** to be cited. This spec closes that gap without
> touching the faithfulness gate one byte.
>
> Status: proposed · 2026-07-06 · implements SPEC-v6 §12 (Evidence Signals),
> §14 (Trust Modes), §20 (Evaluation), on the `domain/trust.py` +
> `domain/partition.py` seam. Ports contract delta folds into SPEC-PORTS `v2`.

---

## 0. The one guarantee this feature must not weaken

CiteNexus already holds two invariants (SPEC-v6, §11):

1. **No ungrounded claim.** Every answer token appears in the cited passage
   (`verify.is_supported`, byte-exact, deterministic).
2. **No evidence ⇒ no answer.** Weak/absent evidence ⇒ refuse.

**Authority-weighting adds a third that is subordinate to the first two:**

> Authority is a **ranking / selection / minimum-bar** signal applied *only to
> evidence that has already passed grounding*. It may reorder grounded passages,
> choose which grounded source answers when several qualify, and (in strict mode)
> require a minimum authority tier or else abstain. **It can never admit a claim
> the faithfulness gate would reject, and it can never turn a refusal into an
> answer.**

The deterministic faithfulness gate (`answer/verify.py:73-77`) stays
**byte-identical**. This spec adds no call into it, changes none of its inputs,
and every new code path either (a) narrows the set of grounded candidates or
(b) reorders them — both strictly *before* generation and the unchanged gate.

The contract is falsifiable: **the default authority profile assigns every
source the same tier, so every existing Result serializes byte-for-byte
unchanged** (§6.4). Authority-weighting is *off* until a domain profile is
chosen. Nothing breaks by upgrading.

---

## 1. Authority model

### 1.1 What authority is derived from — metadata, never content

Grounding reads **content** (tokens in the passage). Authority reads
**metadata about the source** — the same bytes a librarian reads off a spine,
never the prose. This separation is load-bearing: content decides *presence*,
metadata decides *standing*, and the two gates never see each other's inputs.

Authority metadata is **carried on the Evidence Unit** (caller-supplied at
ingest, opaque to retrieval, parsed only by a domain profile). It is distinct
from `acl` (`evidence/unit.py:71`): `acl` is never parsed by the library;
authority metadata *is* parsed, by exactly one component — the domain profile.

### 1.2 `AuthorityMetadata` — the domain-neutral carrier

A new frozen model, `domain/authority.py`, beside `partition.py` and `trust.py`.
Every field is optional; a domain profile reads the subset it needs and ignores
the rest. The union spans law + medicine so both ship on one carrier:

```
AuthorityMetadata (frozen, extra="forbid"):
    document_type:        str | None   # "statute" | "regulation" | "case" |
                                       #  "guideline" | "systematic_review" |
                                       #  "rct" | "case_report" | "blog" | ...
    jurisdiction:         str | None   # "us-federal" | "us-ca" | "eu" | ...
    hierarchy_rank:       int | None   # court level / instance depth, higher = higher court
    precedential_status:  str | None   # "binding" | "persuasive" | "vacated" | "superseded"
    evidence_grade:       str | None   # "1a" | "1b" | "2a" ... (medical GRADE-style)
    publisher:            str | None   # issuing body / journal / registrar
    peer_reviewed:        bool | None
    published_date:       str | None   # ISO-8601 date; drives the recency term
    extra:                Mapping[str, str] = {}   # profile-specific keys, string→string
```

Rationale for `extra` as `str→str` (not `Any`, unlike `acl`): authority must be
**canonically serializable** so the derived tier is byte-identical across
languages (§5). `acl` can be arbitrary because nothing parses it; authority
metadata is parsed, so its wire form is pinned.

### 1.3 `AuthorityTier` — the derived, totally-ordered verdict

```
AuthorityTier (frozen, extra="forbid"):
    rank:    int     # 0..N, HIGHER = more authoritative; 0 = unranked/unknown
    label:   str     # human-facing, e.g. "binding-precedent", "guideline", "unranked"
    profile: str     # which profile assigned it, e.g. "legal.v1"
```

`rank` is the only field the comparator (§3) reads; `label`/`profile` are for
the citation surface (§2) and audit. The tier is a **derived, rebuildable
cache** — the metadata is the source of truth (SPEC-v6 §2: "all indexes are
rebuildable caches"). It is never persisted; it is recomputed by the pinned
profile function on every `ask()`. Same metadata + same profile ⇒ same tier,
in every language.

### 1.4 `AuthorityProfile` — the pluggable, deterministic taxonomy

```
class AuthorityProfile(Protocol):
    name: str          # "legal.v1", "medical.v1", "default.v1"
    def rank(self, meta: AuthorityMetadata | None) -> AuthorityTier: ...
```

Pure, deterministic, no IO, no model call — a lookup table plus a fixed
recency/tie-break formula. Three **built-in** profiles ship, pinned in
`conformance/authority_profiles.json` (§5) so ports agree byte-for-byte:

| Profile | rank ladder (high → low), `rank` value in parens |
|---|---|
| **`default.v1`** (documented default) | everything → `rank=0`, `label="unranked"`. This IS today's behavior. |
| **`legal.v1`** | constitution (60) > statute (50) > regulation (40) > binding case (30) > persuasive case (20) > secondary/treatise (10) > blog/forum (0). `precedential_status ∈ {vacated, superseded}` floors the case to `rank=0`. `hierarchy_rank` and `published_date` break ties within a document_type (higher court first, then more recent). Cross-jurisdiction hits that don't match the query jurisdiction are demoted one band (persuasive, not binding). |
| **`medical.v1`** | guideline / systematic-review / meta-analysis (50) > RCT (40) > cohort/case-control (30) > case report (20) > narrative review (10) > forum/blog (0). `peer_reviewed=false` caps at `rank≤10`. `evidence_grade` (GRADE 1a…) refines within band; `published_date` breaks remaining ties (recency). |

Custom profiles are a **plugin seam** (like every retriever/generator in SPEC-v6
§4b): the operator registers an `AuthorityProfile` by `name`; it is *not*
conformance-covered (third-party code, third-party responsibility). Only the
three built-ins are pinned. The recency term is a pinned monotone tie-break, not
a decay that can reorder *bands* — recency never lets a blog outrank a statute.

### 1.5 Determinism rules (pinned, fixture-covered)

- Tie-break within equal `(rank)` is total and language-independent:
  `(-rank, hierarchy_rank desc (None=−1), published_date desc (None=""), eu_id asc)`.
- Unknown `document_type` for a profile ⇒ `rank=0` (fail-closed to unranked,
  never fail-open to authoritative).
- `AuthorityMetadata=None` ⇒ `rank=0` under every profile.
- Canonical serialization for hashing/fixtures: JSON, sorted keys, `None`
  fields omitted, `extra` keys sorted — one byte sequence per metadata value.

---

## 2. Where it plugs in — file:line anchors

All anchors are against the current tree (read 2026-07-06). Every change is
**additive**; no existing line's *behavior* changes under `default.v1`.

### 2.1 Carry the metadata (ingest side)

| Anchor | Change |
|---|---|
| `evidence/unit.py:62-72` (optional-metadata block) | Add field `authority: AuthorityMetadata | None = None` beside `acl` (`:71`). Persisted, carried, never enforced. |
| `evidence/builder.py:33-53` (`_build_unit`) | Thread an `authority` param onto the constructed `EvidenceUnit`, exactly as `acl` is threaded (`:52`). |
| `evidence/builder.py:56-76` (`build_evidence_units`) | Add `authority: AuthorityMetadata | None = None` param; pass through per unit. Whole-document metadata applies to every block; per-block override is ⏳ (§7). |
| `ingest/pipeline.py:132-139` (`IngestPipeline.ingest`) | Add `authority=` param alongside `acl` (`:139`); forward to `build_evidence_units` (`:173`) and the vision units (`:174`). |
| `ingest/pipeline.py:191-201` (row dict) | Add one column `"authority_meta": canonical_json(eu.authority) or ""` — the **only new persisted column** (§5.2). |
| `client.py:386-408` (`CiteNexus.ingest`) | Add `authority=` param; forward to `self._ingest.ingest(...)` (`:399-404`). |

### 2.2 Surface it on the retrieval hit (query side)

| Anchor | Change |
|---|---|
| `retrieve/types.py:28-40` (`Candidate`) | Add `authority: AuthorityMetadata | None = None`. |
| `retrieve/vector.py:55-65` (Candidate build) | Populate `authority=parse_authority(hit.get("authority_meta"))`. Same one-line addition in `retrieve/lexical.py`, `retrieve/structure.py`, `retrieve/graph/retrieve.py`, `retrieve/wiki/retrieve.py` (each builds a `Candidate` from a row). |
| `retrieve/fusion.py:37-42` (`rrf_fuse` payload copy) | **No change needed** — `best_payload[eu_id].model_copy(update={"score": score})` copies the whole `Candidate`, so `authority` rides through for free. Call this out in the fusion docstring so no future refactor drops it. |

### 2.3 Use it in selection (the heart — `answer/flow.py`)

The current flow: build `grounded` (relevance-passing) → `top = grounded[0]`
(fused-best) → generate → faithfulness gate → Result.

| Anchor | Change |
|---|---|
| `answer/flow.py:48-58` (`AnswerFlow.__init__`) | Inject `authority_profile: AuthorityProfile = DefaultAuthorityProfile()` and `min_authority_tier: int | None = None`. Defaults preserve today. |
| `answer/flow.py:60-68` (`ask` signature) | Accept a per-call `min_authority_tier: int | None = None` override (strict min-bar, §4). |
| `answer/flow.py:77-87` (build `grounded`, empty-refusal) | **Unchanged.** Grounding still decides the candidate *set*. |
| `answer/flow.py:89` (`top = grounded[0]`) | **Replace** with `selection = select_by_authority(grounded, profile=self._profile, mode=mode, min_tier=effective_min_tier)`. Returns either the chosen candidate or a refusal marker. |
| `answer/flow.py` (new, inserted before line 90) | If `selection` is the "min-bar not met" marker → `return refusal(mode, language, "no grounded evidence meets the required authority tier")`. New refusal reason; strict-mode only. |
| `answer/flow.py:91-97` (generate + `is_supported` gate) | **Byte-identical.** The chosen passage still must pass `is_supported` unchanged. If it fails → refuse, exactly as today. |
| `answer/flow.py:99-105` (`SourceRef`) | Add `authority_tier=tier.rank, authority_label=tier.label` to the built `SourceRef`. |
| `answer/flow.py:107-115` (`ProvenanceEntry`) | Extend `produced_by` (`:114`) with `{"authority_profile": tier.profile, "authority_tier": tier.rank}`. |
| `answer/flow.py:116-123` (`EvidenceSignals`) | Add `top_authority_tier=tier.rank, authority_profile=tier.profile, min_authority_tier_met=True`. |

`select_by_authority` (new, in `answer/flow.py` or `domain/authority.py`) is the
single pinned comparator (§3). It is the *only* new decision point, and it
operates on an input set (`grounded`) that has already cleared grounding.

### 2.4 Wire the profile through the client

| Anchor | Change |
|---|---|
| `client.py:97-125` (`CiteNexus.__init__`) | Add `authority_profile: AuthorityProfile | str | None = None`, `min_authority_tier: int | None = None`. Resolve a `str` name via the built-in registry. |
| `client.py:184-191` (`AnswerFlow(...)` construction) | Pass `authority_profile=` and `min_authority_tier=` into `AnswerFlow`. |
| `client.py:489-497` (`CiteNexus.ask` signature) | Add `min_authority_tier: int | None = None`; forward at `:509-515`. |
| `client.py:361-384` (`from_config` → `cls(...)`) | Map `config.authority.*` (§6) onto the two new constructor args. |

### 2.5 The gate that must NOT be touched

`answer/verify.py:73-77` (`is_supported`) — **do not edit, do not wrap, do not
add an authority branch.** Authority never calls it and never changes its two
inputs (`answer`, `passage`). A reviewer diffing this feature must see `verify.py`
unchanged. This is the mechanical proof of §0.

---

## 3. The selection comparator (pinned algorithm)

`select_by_authority(grounded, *, profile, mode, min_tier) -> Candidate | MinBarUnmet`

Deterministic, pure, fixture-covered (§5). Steps:

1. Compute `tier = profile.rank(c.authority)` for each `c in grounded`.
2. **Strict min-bar** — if `mode is strict` and `min_tier is not None`, drop
   every `c` with `tier.rank < min_tier`. If the set becomes empty → return
   `MinBarUnmet` (⇒ refusal at the flow layer). *This is the only path that can
   remove a grounded candidate; it can only ever cause a refusal, never an
   answer.*
3. **Order** by a mode-dependent key, then take the first:

   | Mode | Sort key (all ascending after negation) | Meaning |
   |---|---|---|
   | `strict` | `(-tier.rank, -score, tie_break, eu_id)` | authority-first: most authoritative grounded source wins; fused score breaks ties. |
   | `normal` | `(-score, -tier.rank, tie_break, eu_id)` | best-covered wins; **authority is the tie-break** only. |
   | `exploratory` | `(-score, eu_id)` | authority **ignored** — identical to today's `grounded[0]`. |

   `tie_break = (−hierarchy_rank, reversed published_date)` from §1.5, applied
   identically in every mode that reads `tier`.

**Backward-compat proof:** under `default.v1`, every `tier.rank == 0`, so:
`strict`/`normal` keys collapse to `(0, -score, 0, eu_id)` ≡ `(-score, eu_id)`,
which is exactly the fusion order `grounded` already carries (`fusion.py:41`).
Stable selection ⇒ `grounded[0]` ⇒ **byte-identical to today**. No min-bar is set
by default, so step 2 is a no-op. Proven, not asserted.

---

## 4. TrustMode coupling (SPEC-v6 §14)

The three postures already differ in how hard they gate on evidence signals;
authority extends each *in the same spirit*, never against it.

| Mode | Authority role | Min-bar | If nothing qualifies |
|---|---|---|---|
| **strict** (legal/medical/compliance) | **Primary selector** — most authoritative grounded source answers. Honors `min_authority_tier` (a *floor*, e.g. "binding case or above, else abstain"). | Enforced (from `ask(min_authority_tier=)` or `config.trust.min_authority_tier` or the profile's documented default). | **Refuse** — a low-authority but well-covered source is exactly the "best-covered ≠ most-authoritative" failure this feature exists to prevent. Refusal reason: `"no grounded evidence meets the required authority tier"`. |
| **normal** (enterprise search) | **Tie-break** — fused coverage still wins; authority only orders equal-coverage grounded passages. | None. | N/A — always answers if grounded, exactly as today. |
| **exploratory** (brainstorming) | **Ignored.** | None. | N/A — today's behavior verbatim. |

Strict's min-bar is the one place authority can *cause a refusal*. That is
strictly *stronger* abstention (fewer answers, never more), so it cannot violate
§0. Normal/exploratory can only *reorder* — the answered/refused decision is
untouched.

`config.trust.min_authority_tier` (§6) defaults to `None` ⇒ strict behaves
exactly as today until an operator sets a floor.

---

## 5. Polyglot contract — SPEC-PORTS delta (folds into `ports-v2`)

Python is the reference; Go/TS/Rust conform to fixtures, not to Python source.
Three additions keep them byte-identical.

### 5.1 New pinned deterministic algorithms (SPEC-PORTS §4 table)

| Algorithm | Pinned definition |
|---|---|
| **Authority tier** | For a given profile, `rank(meta)` = the profile's `document_type→band` table (§1.4, pinned in `authority_profiles.json`), with the pinned within-band tie-break (§1.5) and the pinned floor rules (`vacated`/`superseded`→0; `peer_reviewed=false`→≤10; unknown type→0). Canonical metadata serialization = sorted-key JSON, `None` omitted. |
| **Authority selection** | The mode-dependent sort keys + strict min-bar of §3. Input: ordered grounded candidates + profile + mode + min_tier. Output: selected `eu_id` or the `MinBarUnmet` sentinel. |

Both are pure functions of JSON in / JSON out — they belong in the shared Rust
core's `v2` "frozen deterministic algorithms" band (SPEC-PORTS §9) alongside
chunker/BM25/RRF/gates, so one implementation replaces cross-language
conformance for them.

### 5.2 Storage row-schema delta (SPEC-PORTS §3.2) — the T1-interface delta

Add exactly **one** column to the EU row (Lance == Postgres == dict keys):

```
authority_meta: string    # canonical sorted-key JSON of AuthorityMetadata; "" = none
```

This is the sole interop-surface change. Rules:

- Empty string is the default; corpora ingested before this feature read back
  with `authority_meta=""` ⇒ `authority=None` ⇒ `rank=0` — no rebuild required
  for backward compatibility.
- The column is **carried, not indexed** (like `raw_uri`): stores round-trip it;
  no store parses it. Parsing happens only in the profile, host-language side.
- Because it is one additive nullable-by-`""` column, it is a **minor** ports
  bump (`ports-v1` → `ports-v2`), not a breaking one. A `ports-v1` reader that
  ignores the column still answers correctly (as `default.v1`).

### 5.3 Result contract delta (SPEC-PORTS §7)

`Result` serialization gains (all defaulted so old fixtures still validate):

```
evidence.top_authority_tier: int = 0
evidence.authority_profile:  string = "default.v1"
evidence.min_authority_tier_met: bool = true
sources[].authority_tier:  int = 0
sources[].authority_label: string = "unranked"
provenance[].produced_by.authority_profile / .authority_tier
```

### 5.4 New conformance fixtures (`conformance/cases/`)

| Fixture | Shape | Proves |
|---|---|---|
| `authority_profiles.json` (top-level, like `stopwords.json`/`prompts.json`) | the three built-in profile tables + floor rules | one taxonomy, all languages |
| `cases/authority_tier.json` | `(profile, metadata) → {rank, label}` | tier derivation is byte-identical |
| `cases/authority_select.json` | `(mode, min_tier, [candidate{eu_id,score,authority}]) → selected_eu_id | "REFUSE"` | the comparator + strict min-bar agree cross-language |
| `cases/authority_e2e.json` | mixed-authority corpus + questions → `{decision, source_eu_id, authority_tier}`, run with the hash fake embedder + extractive fake LLM | end-to-end: authority reorders/gates but the faithfulness gate still fires |

The interop test (SPEC-PORTS §10) extends: Python ingests a mixed-authority
corpus with `authority_meta` into MinIO → the port under test runs strict
`ask(min_authority_tier=...)` → the selected source + decision must match the
hermetic expectation. That is §0 of this spec, executed across languages.

### 5.5 Non-negotiable port rule

A port MUST NOT ship authority selection that reads passage **content**. If a
port derives a tier from anything but `authority_meta`, it has re-created the
"best-covered" bug this feature removes. Fixtures with adversarial metadata
(a high-coverage blog vs. a low-coverage statute) catch exactly this.

---

## 6. Config + API surface

### 6.1 New config section (`config/schema.py`)

Add `AuthorityConfig` beside `TrustConfig` (`config/schema.py:196-202`), composed
into `CiteNexusConfig` (`:271-304`):

```
class AuthorityConfig(_Section):        # SPEC §14, this spec
    enabled: bool = False               # False ⇒ default.v1 ⇒ today's behavior
    profile: str = "default.v1"         # "legal.v1" | "medical.v1" | custom name
    recency_half_life_days: int | None = None   # profile recency tie-break knob
```

And extend `TrustConfig` (`config/schema.py:196-202`) with:

```
    min_authority_tier: int | None = None   # strict-mode floor; None ⇒ off
```

Both default to the identity behavior. `signals`/`plugins` registration for a
custom profile follows the existing `plugins: dict[str, str]` pattern
(`config/schema.py:298`).

### 6.2 Public API additions

- `CiteNexus(..., authority_profile="legal.v1", min_authority_tier=30)` — new
  kwargs, both optional (`client.py:97-125`).
- `client.ingest(source, authority=AuthorityMetadata(document_type="statute",
  jurisdiction="us-federal"))` — new kwarg (`client.py:386`). A plain `dict` is
  accepted and validated into `AuthorityMetadata`.
- `client.ask(q, mode=TrustMode.strict, min_authority_tier=30)` — new per-call
  override (`client.py:489`).
- `from citenexus import AuthorityMetadata, AuthorityTier, AuthorityProfile`
  and the three built-ins re-exported from the package root.

### 6.3 Backward compatibility (the whole point)

| Caller | Result |
|---|---|
| Existing code, no changes | `default.v1`, no min-bar ⇒ **byte-identical Results** (§3 proof). |
| Existing corpus, no re-ingest | `authority_meta=""` ⇒ `rank=0` everywhere ⇒ identical. |
| Old `ports-v1` reader on a new corpus | Ignores the column ⇒ behaves as `default.v1` ⇒ correct, just un-weighted. |

Authority-weighting is strictly opt-in; the default is a no-op that
provably preserves every existing byte.

---

## 7. "Best data wins" cross-corpus comparator (SPEC-v6 §20)

Today `evaluate()` scores one corpus on coverage: `groundedness_rate`,
`citation_rate`, `expected_support_rate` (`evaluate.py:31-41`). It cannot say
*"corpus A answers this question with a more authoritative grounded source than
corpus B."* Authority-weighted signals make that comparison well-defined.

### 7.1 New report fields (`evaluate.py:19-41`)

```
EvaluationReport += mean_authority_tier: float
                    authority_tier_histogram: dict[int, int]   # rank → count over answered
```

Computed from `result.evidence.top_authority_tier` over answered rows.

### 7.2 The comparator API

```
class Evaluator:
    def compare(self, other_ask: Callable[[str], Result], csv_path) -> CorpusComparison: ...

# or the free function used by both sides:
def compare_corpora(ask_a, ask_b, csv_path) -> CorpusComparison: ...
```

`CorpusComparison` (frozen):

```
total:            int
a_wins:           int
b_wins:           int
ties:             int
per_question:     tuple[QuestionVerdict, ...]   # (question, winner, a_tier, b_tier, reason)
mean_tier_a:      float
mean_tier_b:      float
```

### 7.3 Per-question winner rule (deterministic, "most-authoritative grounded")

For each question, run both `ask` callables and decide by a fixed ladder — the
first level that differs wins:

1. **Grounded-and-verified beats not** — an answered+`all_claims_verified`
   Result beats a refusal or unverified one. (Authority never overrides
   grounding: an un-grounded high-authority source still loses.)
2. **Higher `top_authority_tier` wins** — the core of "best data wins": among
   two grounded, verified answers, the more authoritative *source* wins, **not
   the one that merely covers more query tokens.**
3. **Tie-breaks:** more `distinct_documents`, then more `supporting_sources`,
   then a tie.

Aggregate `a_wins`/`b_wins`/`ties`. This is the executable definition of the
thesis: *authority-weighted grounded evidence, not coverage volume, decides
which corpus is the better source of truth for a question set.* Both corpora
must run under the **same profile** (asserted) or the comparison is meaningless.

---

## 8. Scope table — honest ✅ / ⏳

| Capability | Status | Notes |
|---|---|---|
| `AuthorityMetadata` / `AuthorityTier` / `AuthorityProfile` types | ⏳ | new `domain/authority.py` |
| `default.v1` profile (= today's behavior) | ⏳ | ships first; makes everything else opt-in |
| `legal.v1`, `medical.v1` built-in profiles | ⏳ | pinned tables in `authority_profiles.json` |
| Carry `authority` on EU + `authority_meta` column | ⏳ | one additive column (§5.2) |
| `Candidate.authority` + populate in 5 retrievers | ⏳ | one line each; fusion carries it free |
| `select_by_authority` comparator + strict min-bar | ⏳ | the one new decision point (§3) |
| `EvidenceSignals` / `SourceRef` / provenance authority fields | ⏳ | additive, defaulted |
| TrustMode coupling (strict floor / normal tie-break / exploratory ignore) | ⏳ | §4 |
| Config `authority` section + `trust.min_authority_tier` | ⏳ | defaults = no-op |
| Cross-corpus `compare_corpora` + report fields | ⏳ | §7 |
| Conformance fixtures (4 files) + interop extension | ⏳ | the real contract (§5.4) |
| Custom profile plugin registration | ⏳ | reuses `plugins:` config seam |
| Faithfulness gate (`verify.is_supported`) | ✅ **unchanged** | byte-identical, never touched |
| Per-*block* authority override (vs per-document) | ⏳ later | whole-doc metadata first; block override is a follow-on |
| Model-derived authority (LLM classifies source standing) | ⏳ later | would need a judge-style audit path; out of v1 — v1 is metadata-only + deterministic |
| Authority-aware conflict resolution (§13 conflict model) | ⏳ later | "binding case contradicts blog" auto-resolve — natural next feature, not v1 |
| Go / TS / Rust ports of the above | ⏳ later | fixtures land first (§5), ports follow SPEC-PORTS cadence |

---

## 9. Rung-ordered build plan (foundation-first, additive — ADR 0002)

Each rung is independently shippable and leaves the tree green. Nothing after
rung 1 changes default behavior until a caller opts in.

1. **Types + `default.v1` + fixtures.** `domain/authority.py`
   (`AuthorityMetadata`, `AuthorityTier`, `AuthorityProfile`, `DefaultAuthorityProfile`),
   `authority_profiles.json`, `cases/authority_tier.json`. Proves determinism
   with zero behavior change. **Gate:** default profile ranks everything 0.
2. **Carry the metadata.** EU field, builder, ingest pipeline, `authority_meta`
   column, `Candidate.authority` + 5 retriever populations. **Gate:** round-trip
   fixture — ingest with metadata, retrieve, read `candidate.authority` back
   identical. No selection change yet.
3. **The comparator.** `select_by_authority` + `cases/authority_select.json`.
   Wire into `flow.py:89` behind `default.v1`. **Gate:** the byte-identity proof
   of §3 — existing `e2e_hermetic.json` still passes unchanged.
4. **Real profiles + strict min-bar + Result surface.** `legal.v1`/`medical.v1`,
   the strict refusal path, `EvidenceSignals`/`SourceRef`/provenance fields,
   `cases/authority_e2e.json`. **Gate:** a mixed-authority corpus picks the
   statute over the blog; a below-floor corpus abstains; the faithfulness gate
   still fires on the chosen passage.
5. **Config + client API.** `AuthorityConfig`, `trust.min_authority_tier`,
   `from_config` wiring, `ingest(authority=)`, `ask(min_authority_tier=)`,
   package re-exports. **Gate:** zero-config client == today; `legal.v1` config
   changes selection.
6. **Cross-corpus comparator.** `compare_corpora` + report fields. **Gate:** A/B
   fixture where the higher-authority corpus wins despite lower coverage.
7. **Ports.** Fold §5 into SPEC-PORTS `v2`; land the algorithms in the shared
   Rust core; port fixtures. **Gate:** interop test — Python ingests, Go/TS
   `ask(min_authority_tier=)` matches.

Rungs 1–3 are pure foundation (no behavior change). The product becomes visible
at rung 4. Ports (7) never block the Python guarantee.

---

## 10. Risks

- **Metadata quality is the operator's job.** Authority is only as good as the
  ingest-time metadata. Mitigation: fail-closed (unknown ⇒ `rank=0`), and
  `default.v1` means a lazy operator gets today's (safe, un-weighted) behavior,
  never a false authority. We never *infer* standing from content in v1.
- **A high-authority source can be under-grounded.** A binding statute that
  doesn't actually contain the answer must still lose. Guarded structurally:
  authority orders the set *after* grounding, and the chosen passage still faces
  the unchanged faithfulness gate (§0). Fixtures assert exactly this adversary.
- **Strict min-bar raises refusal rate.** By design — abstaining beats citing a
  forum post in a regulated domain. Surfaced in telemetry via the new refusal
  reason so operators can tune the floor with data.
- **Profile drift across languages.** The whole reason profiles are pinned
  tables in `authority_profiles.json` and fixture-covered, not code. A port that
  hand-codes a table will be caught by `authority_tier.json`.
- **Row-schema bump touches interop.** One additive column, empty-string
  default, `ports-v1` readers still correct — chosen specifically to be the
  smallest possible interop change (§5.2).
- **Scope creep toward conflict resolution.** "Binding case contradicts blog →
  auto-resolve" is tempting but is the §13 conflict model, not this feature.
  Explicitly deferred (§8) so v1 stays a ranking/selection signal, not a
  reasoning engine.

---

*Companion: `docs/adr/0004-authority-weighting.md`. Reference spec: SPEC-v6
(§12, §14, §20). Ports contract: SPEC-PORTS-v1 → v2 delta (§5 above).*
