// Parse phase — shape an injected vision model's reply into an EU-ready record.
//
// Honest scope: real visual-language inference needs an injected endpoint — this
// file owns no model. It only normalizes the loosely-typed mapping a model
// client returns into a Record the assemble phase can turn into a figure
// Evidence Unit.

package vision

import (
	"encoding/json"
	"strconv"
)

// Record is a vision description shaped for an Evidence Unit (§7/§9).
//
// The JSON tags are the pinned wire shape of
// conformance/cases/vision_orchestration.json's `fulfilled` map. Mirrors
// python/src/citenexus/vision/describe.py:24 VisionRecord.
type Record struct {
	ImageID             string   `json:"image_id"`
	ShortCaption        string   `json:"short_caption"`
	DetailedDescription string   `json:"detailed_description"`
	Objects             []string `json:"objects"`
	Relationships       []string `json:"relationships"`
	OCRText             *string  `json:"ocr_text"`
	// DataValues are numeric/tabular values read off a chart, graph or table-as-image.
	DataValues []map[string]any `json:"data_values"`
	// ImageType is photo | chart | diagram | screenshot | table | handwriting | logo | other.
	ImageType *string `json:"image_type"`
}

// pyStr renders a decoded-JSON value the way Python's str() does, because the
// reference applies str() to short_caption / detailed_description / each object
// / each relationship and the ports must agree on what a non-string model reply
// becomes. Only the types encoding/json produces are handled; nothing else can
// reach here from a parsed model reply.
func pyStr(value any) string {
	switch v := value.(type) {
	case nil:
		return "None"
	case string:
		return v
	case bool:
		if v {
			return "True"
		}
		return "False"
	case float64:
		return strconv.FormatFloat(v, 'g', -1, 64)
	case int:
		return strconv.Itoa(v)
	default:
		// A list/dict where the contract says string is a plugin bug either way.
		// Python's str() would render its repr; Go renders the JSON. The two
		// DIVERGE here on purpose rather than pretending to reproduce Python's
		// repr syntax — no conformance vector exercises it, and inventing a
		// fake-repr renderer would pin a lie.
		encoded, err := json.Marshal(v)
		if err != nil {
			return ""
		}
		return string(encoded)
	}
}

// stringOr returns pyStr(data[key]) when the key is present, else "".
// Mirrors Python's str(data.get(key, "")).
func stringOr(data map[string]any, key string) string {
	value, ok := data[key]
	if !ok {
		return ""
	}
	return pyStr(value)
}

// stringSlice coerces a model reply's list field into []string, mapping each
// element through pyStr. A missing/null/empty field yields an EMPTY, non-nil
// slice so it serializes as [] — matching the reference's `objects: tuple = ()`.
func stringSlice(data map[string]any, key string) []string {
	out := []string{}
	raw, ok := data[key]
	if !ok || raw == nil {
		return out
	}
	items, ok := raw.([]any)
	if !ok {
		return out
	}
	for _, item := range items {
		out = append(out, pyStr(item))
	}
	return out
}

// optString returns the raw string at key, or nil when absent/null. Unlike
// stringOr this does NOT stringify: the reference passes ocr_text / image_type
// through untouched and lets the model layer reject a non-string.
func optString(data map[string]any, key string) *string {
	raw, ok := data[key]
	if !ok || raw == nil {
		return nil
	}
	if s, ok := raw.(string); ok {
		return &s
	}
	s := pyStr(raw)
	return &s
}

func mappingSlice(data map[string]any, key string) []map[string]any {
	out := []map[string]any{}
	raw, ok := data[key]
	if !ok || raw == nil {
		return out
	}
	items, ok := raw.([]any)
	if !ok {
		return out
	}
	for _, item := range items {
		if m, ok := item.(map[string]any); ok {
			out = append(out, m)
		}
	}
	return out
}

// RecordFromMapping shapes a model client's reply mapping into a Record for the
// given image. Port of vision/describe.py:60.
func RecordFromMapping(imageID string, data map[string]any) Record {
	return Record{
		ImageID:             imageID,
		ShortCaption:        stringOr(data, "short_caption"),
		DetailedDescription: stringOr(data, "detailed_description"),
		Objects:             stringSlice(data, "objects"),
		Relationships:       stringSlice(data, "relationships"),
		OCRText:             optString(data, "ocr_text"),
		DataValues:          mappingSlice(data, "data_values"),
		ImageType:           optString(data, "image_type"),
	}
}
