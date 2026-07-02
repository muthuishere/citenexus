## 1. Tests first (red)

- [x] 1.1 `tests/lang/test_detect.py`: `LanguageResult` is frozen and typed;
      threshold gating (`is_reliable` False below threshold, True at/above).
- [x] 1.2 `tests/lang/test_detect.py`: `HeuristicDetector` returns a plausible
      ISO code for clearly-one-script text (Latin / Cyrillic / Han), hermetic.
- [x] 1.3 `tests/lang/test_fallback.py`: `resolve_answer_language` — one scenario
      per link (reliable detection wins; unreliable → override; → conversation;
      → evidence-dominant; → default).
- [x] 1.4 `tests/lang/test_fallback.py`: code-mixing helper — two strong
      candidates flagged code-mixed; one dominant candidate not flagged.
- [x] 1.5 `tests/lang/test_detect.py`: a single `@pytest.mark.integration` test
      loads the real `lid.176` model and detects English (skips if offline).

## 2. Implement (green)

- [x] 2.1 `src/citenexus/lang/detect.py`: frozen `LanguageResult`; `DEFAULT_THRESHOLD`;
      `FastTextDetector(LanguageDetectorPlugin)` with lazy `urllib` download +
      cache of `lid.176.ftz` to `assets/models/`; `HeuristicDetector(LanguageDetectorPlugin)`.
- [x] 2.2 `src/citenexus/lang/fallback.py`: `resolve_answer_language(...)` (§11a
      chain) + `flag_code_mixing(...)` helper.
- [x] 2.3 `src/citenexus/lang/__init__.py`: export the public names.

## 3. Verify

- [x] 3.1 `uv run pytest tests/lang -m "not integration" -q` passes.
- [x] 3.2 `uv run ruff check src/citenexus/lang tests/lang` clean;
      `uv run mypy src/citenexus/lang tests/lang` clean.
- [x] 3.3 `npx -y @fission-ai/openspec@latest validate --change language-detect` passes.
