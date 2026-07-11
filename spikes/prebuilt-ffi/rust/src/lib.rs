//! Minimal C-ABI surface for the prebuilt-core distribution spike.
//!
//! Proves the seam: ONE cross-compiled cdylib, loaded by Python (ctypes),
//! TS/JS (koffi), and Go (purego) with no per-language toolchain. The real
//! citenexus-core exposes a richer ABI; this is just enough to prove loading.

use std::os::raw::{c_char, c_int};

/// Static, NUL-terminated version string. Caller must NOT free it.
#[no_mangle]
pub extern "C" fn citenexus_spike_version() -> *const c_char {
    b"citenexus-spike-0.1.0\0".as_ptr() as *const c_char
}

/// A trivial computation, to prove real calls cross the boundary (not just a
/// constant read): every loader asserts add(2, 3) == 5.
#[no_mangle]
pub extern "C" fn citenexus_spike_add(a: c_int, b: c_int) -> c_int {
    a + b
}
