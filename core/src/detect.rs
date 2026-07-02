//! Language detection — fastText lid.176 (SPEC-PORTS-v1 §3.4 item 3).
//!
//! The Rust twin of `src/trustrag/lang/detect.py::FastTextDetector`: load the
//! published `lid.176` model (`.ftz` or `.bin`) from a caller-supplied path,
//! predict the top label, strip the `__label__` prefix, and return
//! `{language, confidence}`. Same model file, same algorithm — detection is
//! identical with Python by construction.
//!
//! The `fasttext` crate (0.8) is a pure-Rust reimplementation of fastText
//! inference: it parses the upstream binary format directly. No C++
//! toolchain, no system dependency. We deliberately did NOT fall back to
//! `lingua` — it ships different language coverage and different
//! confidences, which would break cross-language parity.
//!
//! **Known divergence (documented, not hidden):** the crate's QUANTIZED
//! inference is wrong in 0.8.0 — `lid.176.ftz` loads but predicts garbage
//! (verified: "The quick brown fox…" → `is@0.62` from the crate vs `en@0.74`
//! from upstream fastText on the same file). The dense `lid.176.bin` (~126 MB)
//! matches upstream. `Detector::open` therefore REFUSES quantized models with
//! a clear error rather than misdetecting silently; the Rust core needs
//! `lid.176.bin` while Python may keep using `.ftz`.
//!
//! The model is NEVER bundled or downloaded here — the host language fetches
//! and caches `lid.176.ftz` (Python: `assets/models/`) and hands the path in.
//! Tests that need the real model skip unless the file already exists.

use std::path::Path;

use serde::Serialize;

/// A detected language: ISO code (`__label__` stripped) + model confidence.
/// Thresholding into `is_reliable` stays in the host language (Python keeps
/// its `LanguageResult`); the core reports what the model said, nothing more.
#[derive(Debug, Clone, Serialize)]
pub struct Detection {
    pub language: String,
    pub confidence: f32,
}

/// A loaded lid.176 model.
pub struct Detector {
    model: fasttext::FastText,
}

impl Detector {
    /// Load the model at `model_path` (e.g. `assets/models/lid.176.bin`).
    /// Quantized models (`.ftz`) are refused — see the module docs.
    pub fn open(model_path: &str) -> Result<Self, String> {
        if !Path::new(model_path).is_file() {
            return Err(format!("model file not found: {model_path}"));
        }
        let model = fasttext::FastText::load_model(model_path)
            .map_err(|e| format!("failed to load fastText model: {e}"))?;
        if model.is_quant() {
            return Err(
                "quantized fastText models are not supported: the fasttext crate's \
                 quantized inference diverges from upstream (0.8.0); use the dense \
                 lid.176.bin instead"
                    .to_string(),
            );
        }
        Ok(Self { model })
    }

    /// Top language for `text`. Newlines are flattened to spaces first —
    /// fastText cannot handle embedded newlines (same cleanup as Python).
    pub fn detect(&self, text: &str) -> Result<Detection, String> {
        let cleaned = text.replace('\n', " ");
        let cleaned = cleaned.trim();
        let predictions = self.model.predict(cleaned, 1, 0.0);
        let top = predictions
            .first()
            .ok_or_else(|| "no prediction".to_string())?;
        let language = top
            .label
            .strip_prefix("__label__")
            .unwrap_or(&top.label)
            .to_string();
        Ok(Detection {
            language,
            confidence: top.prob,
        })
    }
}
