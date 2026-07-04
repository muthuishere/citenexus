// Package core is the opt-in cgo binding to the shared Rust engine
// (citenexus-core). It is compiled only with the `citenexus_ffi` build tag; build
// the Rust cdylib first (`cd rust && cargo build --release`). Without the tag this
// package is intentionally empty, so the pure Go port stays `go get`-clean and CI
// (which does not set the tag) never needs a C toolchain or the Rust library.
package core
