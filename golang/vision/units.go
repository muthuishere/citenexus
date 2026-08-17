// Assemble phase — join fulfilled descriptions into cited figure EUs (§9).
//
// The third phase of the two-phase seam (ADR-0005): this package emitted the
// PendingRequests, the host fulfilled them into {request_id: Record}, and this
// joins the two by request_id to build the figure Evidence Units. Each unit's
// Text is the model's description (so it is retrievable in context); its
// Citation points at the real image region carried on the request's SourceRef
// (page + bbox) — navigate the description, cite the figure. The EuID is the
// request_id ({document}::img::{image_id}), so it never collides with block
// units ({document}::{order}).
//
// Degrade-to-text lives here: a request with NO fulfilled description, or an
// empty one, yields no unit and never fails the rest — identical to the "no
// vision model injected" path, and never a fabricated caption.

package vision

import "strings"

// PartitionLevel is one {level, value} step of a variable-depth partition path.
type PartitionLevel struct {
	Level string `json:"level"`
	Value string `json:"value"`
}

// PartitionPath is the tenancy/isolation path an Evidence Unit is stored under.
type PartitionPath struct {
	Levels []PartitionLevel `json:"levels"`
}

// Citation is the quoted passage plus where it lives on the page.
type Citation struct {
	Passage string `json:"passage"`
	Page    *int   `json:"page"`
	BBox    *BBox  `json:"bbox"`
}

// EvidenceUnit is the §7 citable unit, in the wire shape
// conformance/cases/vision_orchestration.json pins for `assembled_eus`.
// Only the fields the vision assemble phase sets are populated; the rest are
// present and null so the serialization matches the reference exactly.
type EvidenceUnit struct {
	EuID       string        `json:"eu_id"`
	Partition  PartitionPath `json:"partition"`
	DocumentID string        `json:"document_id"`
	// Type is always "figure" for a vision-assembled unit.
	Type             string             `json:"type"`
	Language         string             `json:"language"`
	Text             string             `json:"text"`
	Citation         Citation           `json:"citation"`
	Page             *int               `json:"page"`
	Section          *string            `json:"section"`
	SourceURI        *string            `json:"source_uri"`
	Entities         []string           `json:"entities"`
	StructurePath    []string           `json:"structure_path"`
	DocumentMetadata any                `json:"document_metadata"`
	ACL              any                `json:"acl"`
	DenseVector      []float64          `json:"dense_vector"`
	SparseVector     map[string]float64 `json:"sparse_vector"`
	Checksum         *string            `json:"checksum"`
	SourceChecksum   *string            `json:"source_checksum"`
}

// EUTypeFigure is the §7 unit type every vision-assembled unit carries.
const EUTypeFigure = "figure"

// pyGet renders m[key] the way Python's `dict.get(key)` inside an f-string does
// — a MISSING key is None, which formats as "None", not "".
func pyGet(m map[string]any, key string) string {
	return pyStr(m[key])
}

// recordText composes the searchable text from a record's fields.
// Port of vision/units.py:29 _record_text, field order included.
func recordText(record Record) string {
	parts := []string{record.ShortCaption, record.DetailedDescription}
	if record.ImageType != nil && *record.ImageType != "" {
		parts = append(parts, "image type: "+*record.ImageType)
	}
	if len(record.Objects) > 0 {
		parts = append(parts, strings.Join(record.Objects, ", "))
	}
	if len(record.Relationships) > 0 {
		parts = append(parts, strings.Join(record.Relationships, "; "))
	}
	if record.OCRText != nil && *record.OCRText != "" {
		parts = append(parts, *record.OCRText)
	}
	if len(record.DataValues) > 0 {
		rendered := make([]string, 0, len(record.DataValues))
		for _, dv := range record.DataValues {
			rendered = append(rendered, pyGet(dv, "label")+": "+pyGet(dv, "value"))
		}
		parts = append(parts, strings.Join(rendered, "; "))
	}
	kept := make([]string, 0, len(parts))
	for _, part := range parts {
		if strings.TrimSpace(part) != "" {
			kept = append(kept, part)
		}
	}
	return strings.TrimSpace(strings.Join(kept, "\n"))
}

// BuildUnitOptions carries the assemble phase's non-request inputs.
type BuildUnitOptions struct {
	Partition PartitionPath
	Language  string
	// ACL is CARRIED, not enforced — isolation is the partition's job.
	ACL any
}

// BuildUnits assembles figure Evidence Units by joining requests to fulfilled
// records on request_id.
//
// A request the host did not fulfill (absent from fulfilled), or whose
// description composes to empty text, yields NO unit and does not fail the
// others — per-request degrade-to-text. Port of vision/units.py:47.
func BuildUnits(requests []PendingRequest, fulfilled map[string]Record, opts BuildUnitOptions) []EvidenceUnit {
	units := []EvidenceUnit{}
	for _, request := range requests {
		record, ok := fulfilled[request.RequestID]
		if !ok {
			continue
		}
		text := recordText(record)
		if text == "" {
			continue
		}
		ref := request.SourceRef
		units = append(units, EvidenceUnit{
			EuID:       request.RequestID,
			Partition:  opts.Partition,
			DocumentID: ref.Document,
			Type:       EUTypeFigure,
			Language:   opts.Language,
			Text:       text,
			Citation:   Citation{Passage: text, Page: ref.Page, BBox: ref.BBox},
			Page:       ref.Page,
			SourceURI:  ref.SourceURI,
			Entities:   []string{},
			ACL:        opts.ACL,
		})
	}
	return units
}
