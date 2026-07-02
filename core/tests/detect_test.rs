//! Detector behavior. Unit tests never download the model — the real-model
//! test runs ONLY when the dense lid.176.bin is already on disk
//! (`TRUSTRAG_LID176_PATH` or the repo's `assets/models/lid.176.bin`), and
//! silently skips otherwise. Quantized `.ftz` is refused (see detect.rs docs).

use std::path::PathBuf;

use trustrag_core::Detector;

fn assets() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../assets/models")
}

fn model_path() -> Option<PathBuf> {
    if let Ok(path) = std::env::var("TRUSTRAG_LID176_PATH") {
        let path = PathBuf::from(path);
        return path.is_file().then_some(path);
    }
    // repo-root assets/models (the Python detector's cache spot)
    let path = assets().join("lid.176.bin");
    path.is_file().then_some(path)
}

#[test]
fn open_missing_model_errors() {
    let Err(err) = Detector::open("/nonexistent/lid.176.bin") else {
        panic!("expected an error for a missing model file");
    };
    assert!(err.contains("not found"), "unexpected error: {err}");
}

#[test]
fn quantized_model_is_refused_not_misdetected() {
    // fasttext-rs 0.8.0's quantized inference diverges from upstream, so a
    // .ftz must be an ERROR, never silently-wrong predictions.
    let ftz = assets().join("lid.176.ftz");
    if !ftz.is_file() {
        eprintln!("skipped: lid.176.ftz not on disk");
        return;
    }
    let Err(err) = Detector::open(ftz.to_str().unwrap()) else {
        panic!("expected quantized model to be refused");
    };
    assert!(err.contains("quantized"), "unexpected error: {err}");
}

#[test]
fn real_model_detects_languages() {
    let Some(path) = model_path() else {
        eprintln!("skipped: lid.176.bin not on disk (set TRUSTRAG_LID176_PATH)");
        return;
    };
    let detector = Detector::open(path.to_str().unwrap()).expect("load lid.176");

    let cases = [
        ("The quick brown fox jumps over the lazy dog.", "en"),
        ("Bonjour, comment allez-vous aujourd'hui ?", "fr"),
        ("Los empleados acumulan días de vacaciones.", "es"),
    ];
    for (text, expected) in cases {
        let detection = detector.detect(text).expect("detect");
        assert_eq!(detection.language, expected, "text: {text}");
        assert!(detection.confidence > 0.5, "low confidence for {text}");
    }

    // Newlines are flattened, not fatal (same cleanup as Python).
    let detection = detector.detect("Bonjour,\ncomment allez-vous ?").unwrap();
    assert_eq!(detection.language, "fr");
}
