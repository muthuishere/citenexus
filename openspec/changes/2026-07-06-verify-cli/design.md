# Design notes

## Input contract: inline JSON, not file+byte-range resolution

Considered: (a) inline `{claim, passage}` text, zero I/O; (b) a citation
referencing a source file path + byte offset/page+bbox that the CLI reads and
re-extracts itself. Chose (a). `is_supported` already operates purely on two
strings — it never touches files. Building (b) now would mean building a new
extraction/hashing layer, which the mission explicitly rules out ("reuse the
gate, don't rebuild RAG"). (b) is a legitimate, separately-sellable v2
feature (`--resolve`, verifying against re-extracted bytes on disk) — noted
as follow-up, not built here.

## Why claims/citations are arrays, decoupled from `AnswerFlow.ask()`

`flow.py`'s v0.1 `ask()` only ever produces one claim against one top passage.
The verify-cli contract accepts an array of claims, each with an array of
citations, regardless of what the current internal flow produces — otherwise
the CLI could never be used for the multi-claim answers real customers bring,
and the whole "sellable, standalone" premise collapses to "only useful for
citenexus's own current internal shape."

## Why the tokenizer moves out of `citenexus.testing.fakes`

`tokenize()` is the pinned SPEC-PORTS-v1 §4 tokenizer — `golang/gate/gate.go`'s
own docstring calls it out as pinned parity, not a test fixture. Four
production modules already import it from a module literally named
`testing.fakes`. That's an internal-only smell today; it becomes a
credibility problem the moment external customers can `pip install citenexus`
and inspect the CLI's dependency graph. Moving it to `citenexus.tokenize` and
re-exporting from `testing.fakes` (so `FakeEmbedding` and existing test
imports need no changes) fixes the naming with zero behavior change.

## Why Rust gets no gate module in this change

`docs/SPEC-PORTS-v1.md` §9 ("The shared Rust core — target architecture
(DECIDED)") lays out `citenexus-core` v1 (store/extract/detect) vs. v2
("+ the pinned deterministic algorithms (§4): chunker · BM25 · RRF · token
gates — they are frozen contracts, so **one implementation** replaces
cross-language conformance for them"). That is the correct home for a Rust
gate: FFI-exposed, consumed by Go/TS/Python bindings, replacing their local
implementations — not a fifth pure-Rust reimplementation sitting beside three
existing ones. Building `rust/src/gate.rs` as an ad hoc, non-FFI, Rust-only
module in this change would (a) not be consumable by any existing port
(nothing currently calls into Rust for gate logic), so it would satisfy no
real "4th port" use case, and (b) add a maintenance burden pulling in the
opposite direction from the documented "one implementation" goal. Recommend
the v2 migration be its own change when prioritized, scoped to the whole
chunker/BM25/RRF/gate set per the target architecture — not gate alone,
bolted on here.

## GitHub Action: composite, not Docker

A composite action (`checkout` → `setup-python` → `pip install citenexus` →
run the CLI) avoids Docker build/pull latency; the CLI's own dependency
footprint is small. Docker would only be justified for a non-Python runtime
consumer, which isn't a v1 requirement.
