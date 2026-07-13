//go:build citenexus_ffi && !citenexus_static

package core

// Default FFI linkage: dynamically link the shared Rust core (libcitenexus_core
// .dylib/.so/.dll) with an rpath so the port finds it at runtime. This is what
// the Go/TS FFI bindings and CI use. The self-contained CLI adds the
// `citenexus_static` tag to instead absorb the .a — see link_static.go.

// #cgo LDFLAGS: -L${SRCDIR}/../../rust/target/release -lcitenexus_core -Wl,-rpath,${SRCDIR}/../../rust/target/release
import "C"
