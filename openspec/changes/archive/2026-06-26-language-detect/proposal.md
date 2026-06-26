## Why

The answer-language invariant (§11) requires the answer to come back in the
query's language, and that language must be *detected*, not assumed. v6 §11a
makes detection a defined method — fastText `lid.176` + a confidence threshold +
an explicit fallback chain — applied to the **short query only** (documents carry
their own per-EU `language` from ingest; query-time detection never re-scans
them). This change lands that method behind the existing `LanguageDetectorPlugin`
seam so the L5 answer flow can rely on a concrete, testable language signal.

## What Changes

- Add a concrete `LanguageResult` (frozen pydantic: `language` ISO code,
  `confidence`, `is_reliable`) — the return type the §4b `LanguageDetectorPlugin`
  protocol left as a forward alias.
- Add `FastTextDetector(LanguageDetectorPlugin)` using fastText `lid.176`: it
  **lazily downloads** the compressed model (`lid.176.ftz`) to `assets/models/`
  on first use via `urllib`, caches it on disk + in memory, and returns the
  top predicted language + confidence, with `is_reliable = confidence >=
  threshold` (default `0.50`, the §17 `detect_confidence_threshold`).
- Add `HeuristicDetector(LanguageDetectorPlugin)` — a hermetic, network-free
  unicode-script + cue detector used as the deterministic default in unit tests
  (and as an offline fallback when the model is unavailable).
- Add `resolve_answer_language(...)` implementing the §11a fallback chain for the
  short query: reliable detection → explicit `answer_language` override →
  established conversation language → dominant language of retrieved evidence
  (`languages_in_evidence`) → configured `default_answer_language`.
- Add a code-mixing flag helper: when the top-2 language candidates are both
  strong, the input has no single reliable label.

## Capabilities

### New Capabilities
- `language-detect`: the concrete `LanguageResult`, the fastText + heuristic
  `LanguageDetectorPlugin` implementations (lazy model download), the §11a
  query-language fallback chain, and the code-mixing flag.

### Modified Capabilities
<!-- none — the LanguageDetectorPlugin protocol already exists (plugin-protocol-registry); this change only supplies its concrete return type + implementations. -->

## Impact

- New module `src/trustrag/lang/` (`detect.py`, `fallback.py`, `__init__.py`).
- Model asset cached under `assets/models/lid.176.ftz` (gitignored); fetched on
  first use, never bundled and not a pip dependency. `fasttext` is the only
  runtime dependency, already installed.
- Downstream: the L5 answer flow calls `resolve_answer_language(...)` to pick the
  answer language; provenance can stamp the detector's `plugin_version`.
- Tests are hermetic (heuristic detector, no download); a single opt-in
  `@pytest.mark.integration` test exercises the real fastText model.
