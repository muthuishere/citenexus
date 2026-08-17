// Parse phase — shape an injected vision model's reply into an EU-ready record.
//
// Honest scope: real visual-language inference needs an injected endpoint — this
// module owns no model. It only normalizes the loosely-typed mapping a model
// client returns into a VisionRecord the assemble phase can turn into a figure
// Evidence Unit.

/** A vision description shaped for an Evidence Unit (§7/§9).
 *
 * These property names are the pinned wire shape of
 * `conformance/cases/vision_orchestration.json`'s `fulfilled` map. Mirrors
 * `python/src/citenexus/vision/describe.py:24` VisionRecord. */
export interface VisionRecord {
  image_id: string;
  short_caption: string;
  detailed_description: string;
  objects: string[];
  relationships: string[];
  ocr_text: string | null;
  /** Numeric/tabular values read off a chart, graph or table-as-image. */
  data_values: Record<string, unknown>[];
  /** photo | chart | diagram | screenshot | table | handwriting | logo | other. */
  image_type: string | null;
}

/**
 * Render a decoded-JSON value the way Python's `str()` does, because the
 * reference applies `str()` to short_caption / detailed_description / each
 * object / each relationship and the ports must agree on what a non-string model
 * reply becomes. `null` is "None" and booleans are "True"/"False" — JS's own
 * `String()` would say "null"/"true", and a port that silently disagreed here
 * would put different text in an Evidence Unit in one language only.
 */
export function pyStr(value: unknown): string {
  if (value === null || value === undefined) return "None";
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "True" : "False";
  if (typeof value === "number") return String(value);
  // A list/object where the contract says string is a plugin bug either way.
  // Python's str() would render its repr; this renders the JSON. The two DIVERGE
  // on purpose rather than pretending to reproduce Python's repr syntax — no
  // conformance vector exercises it, and a fake-repr renderer would pin a lie.
  return JSON.stringify(value);
}

/** `pyStr(data[key])` when the key is present, else "" — Python's
 *  `str(data.get(key, ""))`. */
function stringOr(data: Record<string, unknown>, key: string): string {
  if (!(key in data)) return "";
  return pyStr(data[key]);
}

/** Coerce a model reply's list field into `string[]`, each element through
 *  pyStr. A missing/null/non-array field yields `[]`, matching the reference's
 *  `objects: tuple = ()`. */
function stringList(data: Record<string, unknown>, key: string): string[] {
  const raw = data[key];
  if (raw === null || raw === undefined || !Array.isArray(raw)) return [];
  return raw.map((item) => pyStr(item));
}

/** The raw string at `key`, or null when absent/null. Unlike stringOr this does
 *  NOT stringify: the reference passes ocr_text / image_type through untouched
 *  and lets the model layer reject a non-string. */
function optString(data: Record<string, unknown>, key: string): string | null {
  const raw = data[key];
  if (raw === null || raw === undefined) return null;
  return typeof raw === "string" ? raw : pyStr(raw);
}

function mappingList(data: Record<string, unknown>, key: string): Record<string, unknown>[] {
  const raw = data[key];
  if (raw === null || raw === undefined || !Array.isArray(raw)) return [];
  return raw.filter(
    (item): item is Record<string, unknown> =>
      typeof item === "object" && item !== null && !Array.isArray(item),
  );
}

/** Shape a model client's reply mapping into a VisionRecord for the given image.
 *  Port of `vision/describe.py:60`. */
export function recordFromMapping(
  imageId: string,
  data: Record<string, unknown>,
): VisionRecord {
  return {
    image_id: imageId,
    short_caption: stringOr(data, "short_caption"),
    detailed_description: stringOr(data, "detailed_description"),
    objects: stringList(data, "objects"),
    relationships: stringList(data, "relationships"),
    ocr_text: optString(data, "ocr_text"),
    data_values: mappingList(data, "data_values"),
    image_type: optString(data, "image_type"),
  };
}
