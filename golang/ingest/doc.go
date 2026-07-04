// Package ingest is the opt-in Go ingest orchestrator over the shared Rust
// engine (extractor + Lance store). It is compiled only with the `citenexus_ffi`
// build tag; build the Rust cdylib first (`cd rust && cargo build --release`).
// Without the tag this package is intentionally empty, so the pure Go port stays
// `go get`-clean and CI (which does not set the tag) never needs a C toolchain or
// the Rust library.
package ingest
