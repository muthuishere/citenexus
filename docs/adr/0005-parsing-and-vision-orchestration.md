# 0005 — Deterministic parsing in the Rust core; vision via host-fulfilled two-phase requests

Status: proposed · 2026-07-11

## Context

CiteNexus ships a polyglot core: Python is the reference, Go/JS (and the Rust
`citenexus-core` cdylib beneath them) must behave **identically**. Ingest is
where drift is most expensive — if page-splitting, table extraction, or figure
detection differ per language, every downstream guarantee (bbox citations,
navigate-not-cite, conformance) diverges. Two things forced this decision:

1. **Parity of parsing.** Re-implementing PDF/office parsing, table detection,
   and figure gating in three languages guarantees three subtly different
   outputs. The volentis recon and the ingest-fidelity spike (2026-07-11)
   confirmed the deterministic parts (page render, table→markdown, figure
   gating) are what must be byte-identical.
2. **Where the model call lives.** Figures need a vision LLM (VL). The question
   was whether the core should make that HTTP call itself. CiteNexus's standing
   principle is **the host owns transport + credentials** — models are injected
   OpenAI-compatible endpoints, and a source's secret value must never enter the
   model/core layer. A core that makes the call would have to re-implement the
   host's transport (auth styles, proxy, streaming, retries, telemetry hooks)
   *and* hold the API key inside Rust.

Constraints that bound the choice: tables are **not** vision (a markdown table
is a deterministic parse); VL is for images/figures only; the API key must never
cross into the Rust core; and the licensing gate — **PyMuPDF is AGPL and must
not enter the Apache-2.0 core; use pypdfium2** (per the ingest-fidelity spike).

## Decision

> **Amended 2026-08-17 — placement is now governed by [ADR-0010](0010-algorithm-placement-rust-core-vs-ports.md).**
> The two-phase host-fulfilled protocol below is unchanged and shipped. What
> changed is *where the deterministic half lives*. ADR-0010 classifies work by
> what the algorithm carries: tier 1 (structural/arithmetic) is native in each
> port, tier 3 (real Unicode competence — parsing, normalisation, script
> detection) is Rust over FFI. The **vision orchestration** — the §9 decision
> table, the data-URI/magic-byte payload build, the record parse and the EU
> assembly — is base64, prefix matching and string joins, so it is tier 1 and
> now ships **natively** in `python/src/citenexus/vision/`, `golang/vision/` and
> `js/src/vision/`, pinned by `conformance/cases/vision_orchestration.json` in
> all three. **Artifact parsing stays tier 3 and remains in the Rust core**, as
> this ADR says. The practical reason for the split: a plain `go get` and plain
> ESM must keep working with no native library, and ADR-0010 forbids moving
> anything onto that path without an explicit distribution decision.

**All deterministic ingest work lives in the Rust core and is shared via FFI;
bindings (ctypes / cgo-or-purego / koffi) stay thin. The vision model call is
fulfilled by the host through a two-phase "emit requests" protocol, never by the
core making HTTP.**

Deterministic, in-core (identical across Go/JS/Python):

- Parse artifact → **page-level arrays**.
- **Tables → markdown by deterministic parse** (not vision).
- **Gate** which figures/regions actually need VL.
- Render the page/region, base64-encode, and **build the vision request payload**.

Vision orchestration — two-phase, host-fulfilled:

1. **Rust parse** returns the page-level arrays **plus a list of pending vision
   requests**, each carrying the prepared payload and which figure/bbox it is for.
2. **The host fulfills** those requests with its **own injected transport** —
   its concurrency, its auth, mockable in tests — and collects the descriptions.
3. A **second FFI call** feeds the descriptions back; the core assembles the
   **figure EUs** (each a citable EvidenceUnit with page + bbox).

This is the existing injected-transport pattern extended across the FFI seam:
only the thin "POST payload → return string" shim stays host-side (each binding
already has it), while every deterministic decision stays identical-in-Rust.

### Alternatives considered (ranked: two-phase > FFI-callback > core-makes-call)

- **Core makes the HTTP call (rich config struct passed in) — rejected.** Forces
  the core to re-implement the host transport and to hold the API key inside
  Rust. Directly fights "host owns transport + credentials."
- **FFI callback (core invokes a host function-pointer mid-parse) — viable but
  not chosen.** Keeps the host in charge and the key host-side, but adds
  function-pointer plumbing across three bindings with GC-liveness, thread-safety,
  and reentrancy gotchas.
- **Two-phase emit-requests — chosen.** Plain data in/out across FFI, no
  callbacks; the host owns the calls; the **key never crosses into Rust**; and it
  is naturally batch-parallel (all of a document's figures fulfilled at once).

## Consequences

- **Parity holds where it matters.** Page-splitting, table extraction, figure
  gating, and EU assembly are one Rust implementation; ports can't diverge. Only
  the uniform transport shim is per-language.
- **Secret hygiene is structural, not procedural.** The VL endpoint key lives
  only in the host's HTTP call; it cannot be logged or leaked by the core because
  it never enters the core.
- **navigate-not-cite preserved.** Figures become citable EUs with page + bbox —
  CiteNexus's edge over volentis's page-only provenance.
- **Cost:** two FFI round-trips per ingested artifact (parse → emit, then
  fulfilled → assemble) instead of one. Acceptable; it also enables host-side
  parallel fulfillment.
- **Licensing:** the core's PDF path uses **pypdfium2**, not PyMuPDF; docling
  (TableFormer) stays an opt-in Python-only `citenexus[docling]` extra for
  merged/multi-row headers and never enters the parity core.
- Additive and foundation-first (ADR 0002): documents already ingest; this
  formalizes the figure/vision route and the parse-in-core contract without
  changing the abstain guarantee.
