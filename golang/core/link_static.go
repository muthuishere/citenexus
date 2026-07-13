//go:build citenexus_ffi && citenexus_static

package core

// Static linkage for the self-contained CLI: absorb the Rust core's static
// archive (libcitenexus_core.a) into the Go binary so there is no dylib to ship
// or locate at runtime. The archive is passed by full path (not -l) so the linker
// chooses the .a over any sibling .dylib. The trailing flags satisfy the symbols
// the Rust std + lancedb/arrow/tokio + fasttext transitively need per platform.

// #cgo darwin LDFLAGS: ${SRCDIR}/../../rust/target/release/libcitenexus_core.a -lc++ -lresolv -liconv -framework CoreFoundation -framework Security -framework SystemConfiguration
// #cgo linux LDFLAGS: ${SRCDIR}/../../rust/target/release/libcitenexus_core.a -lm -ldl -lpthread -lresolv
// #cgo windows LDFLAGS: ${SRCDIR}/../../rust/target/release/libcitenexus_core.a -lws2_32 -luserenv -lbcrypt -lntdll -ladvapi32 -lsynchronization -lkernel32
import "C"
