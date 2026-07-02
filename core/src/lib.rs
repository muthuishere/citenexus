//! trustrag-core — TrustRAG's Rust engine (SPEC-PORTS-v1 §3.4).
//!
//! One core, FFI for all languages: extraction now; lance store access and
//! lid.176 detection next. The core is the ENGINE, not the brain —
//! orchestration, cite-or-abstain, hooks, and model IO stay in each host
//! language. Boundary: JSON in/out, no callbacks.

pub mod extract;
pub mod types;

mod ffi;

pub use extract::{extract, source_type_for_extension};
pub use types::*;
