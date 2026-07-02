//! citenexus-core — CiteNexus's Rust engine (SPEC-PORTS-v1 §3.4).
//!
//! One core, FFI for all languages: extraction, lance store access, and
//! lid.176 detection. The core is the ENGINE, not the brain —
//! orchestration, cite-or-abstain, hooks, and model IO stay in each host
//! language. Boundary: JSON in/out, no callbacks.

pub mod detect;
pub mod extract;
pub mod store;
pub mod types;

// Public so integration tests can exercise the exact C surface bindings use.
pub mod ffi;

pub use detect::{Detection, Detector};
pub use extract::{extract, source_type_for_extension};
pub use store::LanceStore;
pub use types::*;
