## Context

§11a defines language detection as a concrete method behind the existing
`LanguageDetectorPlugin` seam (`detect(text) -> LanguageResult`). The protocol
already exists (`plugin-protocol-registry`); `LanguageResult` was a forward
`Any` alias. This change supplies the concrete type and two implementations, plus
the query-language fallback chain that the answer-language invariant (§11) reads.

**Scope is the short query only.** Documents are NOT language-detected here at
query time: each Evidence Unit already carries its own `language` from ingest
(`EvidenceUnit.language`). Re-scanning evidence at ask-time would be redundant and
slow; the evidence languages enter this layer only as a *fallback signal*
(`languages_in_evidence`) when the short query itself is too ambiguous to detect
reliably. Detecting a 3-word query is exactly where fastText is least confident,
which is why the fallback chain exists.

## Goals / Non-Goals

**Goals:**
- A concrete frozen `LanguageResult` (`language` ISO code, `confidence`,
  `is_reliable`).
- `FastTextDetector` — real `lid.176`, lazy-downloaded + cached, threshold-gated
  reliability.
- `HeuristicDetector` — deterministic, network-free, for hermetic unit tests.
- `resolve_answer_language(...)` — the §11a chain, one branch per link.
- A code-mixing flag (top-2 strong ⇒ no single reliable label).

**Non-Goals:**
- Translating citations or regenerating the answer (that is the L5 answer flow).
- Detecting document language at query time (it is an ingest-time per-EU field).
- Training or shipping a model; we fetch the published `lid.176.ftz` on first use.

## Decisions

- **`is_reliable = confidence >= threshold`, default `0.50`.** The threshold is
  the §17 `multilingual.detect_confidence_threshold`. A reliable detection short-
  circuits the fallback chain; an unreliable one (typical for very short queries)
  drops through to the explicit/contextual signals.
- **Lazy download via `urllib`, cached to `assets/models/lid.176.ftz`.** The
  model is ~deployment-sized, not a pip dependency, and the dir is gitignored.
  First `detect()` ensures the file exists (downloads if missing) then loads it
  once into memory. Because this needs the network, any test that actually loads
  the model is `@pytest.mark.integration` and skips when offline.
- **fastText labels → ISO codes.** `lid.176` emits `__label__<iso>`; we strip the
  prefix to the bare ISO code. The top-1 label is the language; its probability is
  the confidence.
- **Heuristic detector = unicode-script majority + light Latin cues.** It counts
  letters by script (Han/Hiragana-Katakana/Hangul/Cyrillic/Devanagari/Arabic/
  Hebrew/Greek/Latin/…), maps the dominant script to a plausible ISO code, and
  sets confidence to the dominant-script fraction. Deterministic and offline, so
  unit tests never touch the network. Not as accurate as fastText — it is a test
  default + offline fallback, never the production detector.
- **Fallback chain as a pure function.** `resolve_answer_language` takes the
  detection result plus the contextual signals and returns one ISO code, applying
  exactly the §11a order. Pure and side-effect free, so each link is one test.
- **Code-mixing is a separate flag, not a detector mode.** `flag_code_mixing`
  inspects the top-2 candidates `(lang, prob)`; if both clear a `strong`
  threshold the text is mixed and has no single reliable label, so the caller
  should fall through the chain rather than trust the top-1.

## Risks / Trade-offs

- [First-use download latency / offline boxes] → cache on disk after first fetch;
  the `HeuristicDetector` is the offline fallback, and integration tests skip when
  the network is unavailable.
- [Heuristic detector mislabels Latin-script languages (en vs es vs de)] →
  acceptable: it is a deterministic test default, not the shipping detector;
  fastText is the real path. Cues cover only a few obvious cases.
- [Short queries are inherently low-confidence] → that is precisely why the
  threshold + fallback chain exist; an unreliable detection is expected and
  handled, not an error.

## Open Questions

- Whether to memo-cache detection results per query string (L5 concern; the
  detector is cheap once loaded, so deferred).
