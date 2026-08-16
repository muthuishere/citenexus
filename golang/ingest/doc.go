// Package ingest is the opt-in Go ingest orchestrator over the shared Rust
// engine (extractor + Lance store). It is compiled only with the `citenexus_ffi`
// build tag; build the Rust cdylib first (`cd rust && cargo build --release`).
// Without the tag the orchestrator itself is intentionally absent, so the pure
// Go port stays `go get`-clean and CI (which does not set the tag) never needs a
// C toolchain or the Rust library. The model seam (Embedder) and the write-path
// vector guard in embedder.go are pure Go and carry NO tag: the contract a
// provider must satisfy, and the check that keeps a degenerate vector out of the
// corpus, are compiled and tested in every build.
package ingest
