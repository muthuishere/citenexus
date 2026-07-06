#!/usr/bin/env bash
# Re-fetch the raw public source text for this corpus via the Jina Reader API.
#
# The curated corpus/*.txt files are committed, so you do NOT need this to run
# the example — it documents provenance and lets you refresh the sources.
#
# Requires JINA_API_KEY in the environment (referenced BY NAME; never printed).
#   export JINA_API_KEY=...   # or load from your own secret store
#   ./fetch_sources.sh
#
# Output goes to ./raw/ as <name>.md (clean markdown of each public page).
set -euo pipefail

if [[ -z "${JINA_API_KEY:-}" ]]; then
  echo "JINA_API_KEY is not set (reference by name; do not paste the value)." >&2
  exit 1
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$HERE/raw"
mkdir -p "$OUT"

fetch() {  # fetch <name> <url>
  local name="$1" url="$2"
  echo "fetch $name <- $url"
  curl -s --max-time 90 "https://r.jina.ai/$url" \
    -H "Authorization: Bearer $JINA_API_KEY" > "$OUT/$name.md"
}

# All sources are public / official government or self-help pages.
fetch ca-civ-1946_1 "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1946.1."
fetch ca-civ-1946   "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1946."
fetch ca-civ-1946_2 "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1946.2."
fetch mak-v-berkeley "https://www.courtlistener.com/opinion/2837910/mak-v-city-of-berkeley-rent-stabilization-board/"
fetch nolo-month-to-month "https://www.nolo.com/legal-encyclopedia/california-notice-requirements-terminate-month-month-tenancy.html"
fetch fl-83_57 "https://www.flsenate.gov/Laws/Statutes/2023/83.57"

echo "done -> $OUT (curated, trimmed corpus lives in ./corpus)"
