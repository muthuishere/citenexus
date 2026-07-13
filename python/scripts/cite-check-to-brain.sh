#!/usr/bin/env bash
# cite-check-to-brain.sh — complementarity glue (citenexus organ -> brain organ).
#
# Runs `citenexus cite-check` over an evidence dir and records the verdict into a
# brain as an audited episode, so the fleet's memory accrues *grounded* evidence
# of what was and wasn't verified. CITED earns a positive reward, ABSTAIN a
# negative one — the brain learns which claims survive the gate.
#
# Usage:
#   BRAIN=/path/to/brain scripts/cite-check-to-brain.sh "<claim>" <evidence-dir>
#
# Exit code is the cite-check verdict's own code (0 CITED / 3 ABSTAIN / 2 setup),
# so a caller can gate on it exactly as if it had run cite-check directly.
set -euo pipefail

claim="${1:?usage: cite-check-to-brain.sh <claim> <evidence-dir>}"
evidence_dir="${2:?usage: cite-check-to-brain.sh <claim> <evidence-dir>}"
brain_repo="${BRAIN:?set BRAIN=/path/to/brain}"

# --format json so the verdict is machine-parseable; capture exit code without
# tripping `set -e`.
set +e
verdict_json="$(citenexus cite-check "$claim" "$evidence_dir" --format json)"
code=$?
set -e

if [ "$code" -eq 2 ]; then
  echo "$verdict_json" >&2
  exit 2
fi

# Let Python do all JSON parsing and formatting (no fragile shell quoting), and
# emit `reward<TAB>episode` on one line. JSON comes in via an env var so stdin
# stays free.
line="$(VJSON="$verdict_json" CLAIM="$claim" python3 <<'PY'
import os, json
d = json.loads(os.environ["VJSON"])
claim = os.environ["CLAIM"]
verdict = d["verdict"]
coverage = f'{d["coverage"]:.2f}'
sources = ", ".join(f'{s["file"]}:block{s["block"]}' for s in d["sources"]) or "none"
reward = "1" if verdict == "CITED" else "-1"
episode = (
    f'citenexus cite-check {verdict} (coverage {coverage}) '
    f'for claim: "{claim}" -- sources: {sources}'
)
print(reward + "\t" + episode)
PY
)"
reward="${line%%$'\t'*}"
episode="${line#*$'\t'}"

brain --repo "$brain_repo" record "$episode" --reward "$reward" --label cite-check --dimension truth >/dev/null

echo "$verdict_json"
exit "$code"
