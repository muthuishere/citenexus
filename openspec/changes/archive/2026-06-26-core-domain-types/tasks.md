## 1. Partition + trust primitives (test-first)

- [ ] 1.1 Write failing tests `tests/domain/test_partition.py` for PartitionPath:
      variable-depth construction (1 and 3 levels), order-sensitive equality,
      `is_prefix_of` true/false cases, JSON round-trip.
- [ ] 1.2 Write failing tests `tests/domain/test_trust.py` asserting TrustMode has
      exactly strict/normal/exploratory.
- [ ] 1.3 Implement `src/trustrag/domain/partition.py` (PartitionLevel, PartitionPath
      with `depth`, `is_prefix_of`, serialization) and `src/trustrag/domain/trust.py`
      (TrustMode) until 1.1–1.2 pass.

## 2. Evidence Unit (test-first)

- [ ] 2.1 Write failing tests `tests/evidence/test_unit.py`: minimal EU constructs;
      missing required field rejected; closed `type` enum (accept community_summary,
      reject footnote); Citation bbox length-4 valid / length-3 rejected; `acl`
      stored verbatim + defaults None + survives JSON round-trip; EU JSON round-trip.
- [ ] 2.2 Implement `src/trustrag/evidence/unit.py` (EUType, Citation, EvidenceUnit)
      until 2.1 passes.

## 3. Result + signals (test-first)

- [ ] 3.1 Write failing tests `tests/answer/test_result.py`: EvidenceSignals fields +
      `decision` enum (reject "maybe"); assert NO `confidence` field exists on
      EvidenceSignals or Result; SourceRef keeps verbatim passage with additive
      `translation` (untranslated → None; fr passage + en translation both present);
      Result exposes `answer_language` independent of `languages_in_evidence`;
      provenance entry forms a full chain; Result JSON round-trip.
- [ ] 3.2 Implement `src/trustrag/answer/result.py` (Decision, EvidenceSignals,
      SourceRef, Claim, ProvenanceEntry, Result) until 3.1 passes.

## 4. Gate

- [ ] 4.1 Export the public models from their packages' `__init__.py` as needed.
- [ ] 4.2 Run `task check` (ruff + mypy --strict + unit tests) and ensure it is green.
- [ ] 4.3 Confirm coverage of the new modules via `task cov`.
