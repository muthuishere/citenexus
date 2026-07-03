// Loads the shared cross-language conformance fixtures at <repo>/conformance/
// (SPEC-PORTS-v1 §10). These fixtures ARE the port contract: every §4
// deterministic algorithm is proven identical to the Python reference by making
// them pass, byte-for-byte.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
// here = <repo>/ports/ts/src/conform → up 4 to <repo>.
const conformanceDir = join(here, "..", "..", "..", "..", "conformance");

/** Parse conformance/cases/<name> (e.g. "tokenize.json"). */
export function loadCase<T>(name: string): T {
  return JSON.parse(readFileSync(join(conformanceDir, "cases", name), "utf8")) as T;
}

/** Parse a top-level conformance file (e.g. "stopwords.json"). */
export function loadData<T>(name: string): T {
  return JSON.parse(readFileSync(join(conformanceDir, name), "utf8")) as T;
}
