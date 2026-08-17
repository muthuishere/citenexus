// Assemble phase — join fulfilled descriptions into cited figure EUs (§9).
//
// The third phase of the two-phase seam (ADR-0005): this module emitted the
// PendingVisionRequests, the host fulfilled them into {request_id: VisionRecord},
// and this joins the two by request_id to build the figure Evidence Units. Each
// unit's `text` is the model's description (so it is retrievable in context);
// its `citation` points at the real image region carried on the request's
// `source_ref` (page + bbox) — navigate the description, cite the figure. The
// `eu_id` is the request_id (`{document}::img::{image_id}`), so it never
// collides with block units (`{document}::{order}`).
//
// Degrade-to-text lives here: a request with NO fulfilled description, or an
// empty one, yields no unit and never fails the rest — identical to the "no
// vision model injected" path, and never a fabricated caption.

import { pyStr, type VisionRecord } from "./describe.js";
import type { BBox, PendingVisionRequest } from "./requests.js";

/** One `{level, value}` step of a variable-depth partition path. */
export interface PartitionLevel {
  level: string;
  value: string;
}

/** The tenancy/isolation path an Evidence Unit is stored under. */
export interface PartitionPath {
  levels: PartitionLevel[];
}

/** The quoted passage plus where it lives on the page. */
export interface Citation {
  passage: string;
  page: number | null;
  bbox: BBox | null;
}

/** The §7 unit type every vision-assembled unit carries. */
export const EU_TYPE_FIGURE = "figure";

/** The §7 citable unit, in the wire shape
 *  `conformance/cases/vision_orchestration.json` pins for `assembled_eus`. Only
 *  the fields the vision assemble phase sets are populated; the rest are present
 *  and null so the serialization matches the reference exactly. */
export interface EvidenceUnit {
  eu_id: string;
  partition: PartitionPath;
  document_id: string;
  type: string;
  language: string;
  text: string;
  citation: Citation;
  page: number | null;
  section: string | null;
  source_uri: string | null;
  entities: string[];
  structure_path: string[] | null;
  document_metadata: unknown;
  acl: unknown;
  dense_vector: number[] | null;
  sparse_vector: Record<string, number> | null;
  checksum: string | null;
  source_checksum: string | null;
}

/** Compose the searchable text from a record's fields. Port of
 *  `vision/units.py:29` _record_text, field order included. */
export function recordText(record: VisionRecord): string {
  const parts: string[] = [record.short_caption, record.detailed_description];
  if (record.image_type) parts.push(`image type: ${record.image_type}`);
  if (record.objects.length > 0) parts.push(record.objects.join(", "));
  if (record.relationships.length > 0) parts.push(record.relationships.join("; "));
  if (record.ocr_text) parts.push(record.ocr_text);
  if (record.data_values.length > 0) {
    parts.push(
      record.data_values
        // `dv.get('label')` on a missing key is None in Python, which formats as
        // "None" — pyStr keeps that, where `${undefined}` would say "undefined".
        .map((dv) => `${pyStr(dv["label"])}: ${pyStr(dv["value"])}`)
        .join("; "),
    );
  }
  return parts
    .filter((part) => part.trim().length > 0)
    .join("\n")
    .trim();
}

/** The assemble phase's non-request inputs. */
export interface BuildUnitOptions {
  partition: PartitionPath;
  language: string;
  /** CARRIED, not enforced — isolation is the partition's job. */
  acl?: unknown;
}

/**
 * Assemble figure Evidence Units by joining requests to fulfilled records on
 * request_id.
 *
 * A request the host did not fulfill (absent from `fulfilled`), or whose
 * description composes to empty text, yields NO unit and does not fail the
 * others — per-request degrade-to-text. Port of `vision/units.py:47`.
 */
export function buildVisionUnits(
  requests: readonly PendingVisionRequest[],
  fulfilled: Readonly<Record<string, VisionRecord>>,
  options: BuildUnitOptions,
): EvidenceUnit[] {
  const units: EvidenceUnit[] = [];
  for (const request of requests) {
    const record = fulfilled[request.request_id];
    if (record === undefined) continue;
    const text = recordText(record);
    if (text.length === 0) continue;
    const ref = request.source_ref;
    units.push({
      eu_id: request.request_id,
      partition: options.partition,
      document_id: ref.document,
      type: EU_TYPE_FIGURE,
      language: options.language,
      text,
      citation: { passage: text, page: ref.page, bbox: ref.bbox },
      page: ref.page,
      section: null,
      source_uri: ref.source_uri,
      entities: [],
      structure_path: null,
      document_metadata: null,
      acl: options.acl ?? null,
      dense_vector: null,
      sparse_vector: null,
      checksum: null,
      source_checksum: null,
    });
  }
  return units;
}
