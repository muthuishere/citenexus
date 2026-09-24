//go:build citenexus_ffi

package core

/*
#include <stdlib.h>
#include <stdint.h>
char* citenexus_ooxml_units(const uint8_t* bytes, size_t len, const char* source_type);
void citenexus_free_string(char* s);
*/
import "C"

import (
	"encoding/json"
	"errors"
	"unsafe"
)

// DocUnit is one block of a converted document (ADR-0017 decisions 1, 8, 10),
// field-for-field the Rust `units::DocUnit` JSON. Kind is one of heading |
// paragraph | list | table | furniture | image. Page is 1-based (PPTX slide) or
// nil where the format has no pages (DOCX); BBox is [x0,y0,x1,y1] in points,
// top-left origin, or nil when unknown; Level is set on headings only.
type DocUnit struct {
	Page       *int        `json:"page"`
	BBox       *[4]float64 `json:"bbox"`
	Kind       string      `json:"kind"`
	Level      *int        `json:"level"`
	Markdown   string      `json:"markdown"`
	Provenance Provenance  `json:"provenance"`
}

// Provenance says how a unit was produced (ADR-0017 decision 6). Route is
// "ooxml" for DOCX/PPTX. TableSource is set on tables only ("ooxml" here);
// HeadingSource on headings only ("style" here).
type Provenance struct {
	Route             string  `json:"route"`
	TableSource       *string `json:"table_source"`
	VisionTranscribed bool    `json:"vision_transcribed"`
	TableUncertain    bool    `json:"table_uncertain"`
	FailedCheck       *string `json:"failed_check"`
	HeadingSource     *string `json:"heading_source"`
	JoinedHyphen      bool    `json:"joined_hyphen"`
	// VisionDisputed: part (or all) of this unit's vision text is disputed —
	// the two transcriptions disagreed or only one came back. Disputed text
	// sits in <!-- vision_disputed … --> blocks; cite only CitableText(Markdown).
	VisionDisputed bool `json:"vision_disputed"`
	// HeaderFlattened: a table header cell spanning several columns was
	// flattened into its sub-headers ("<label> <sub-header>", PDF words).
	HeaderFlattened bool `json:"header_flattened"`
}

// OoxmlUnits converts a DOCX or PPTX (sourceType "docx" | "pptx") into
// structured units read deterministically from its own OOXML structure:
// headings from paragraph styles / title placeholders, lists from numbering,
// pipe tables (merged cells render once at their anchor, table_uncertain set),
// headers/footers as furniture kept once. No model, no network. The same bytes
// always give the same units.
func OoxmlUnits(data []byte, sourceType string) ([]DocUnit, error) {
	var bp *C.uint8_t
	if len(data) > 0 {
		bp = (*C.uint8_t)(unsafe.Pointer(&data[0]))
	}
	cSourceType := C.CString(sourceType)
	defer C.free(unsafe.Pointer(cSourceType))

	out := C.citenexus_ooxml_units(bp, C.size_t(len(data)), cSourceType)
	defer C.citenexus_free_string(out)
	return decodeUnits(C.GoString(out))
}

func decodeUnits(raw string) ([]DocUnit, error) {
	var units []DocUnit
	if err := json.Unmarshal([]byte(raw), &units); err != nil {
		var failure struct {
			Error string `json:"error"`
		}
		if json.Unmarshal([]byte(raw), &failure) == nil && failure.Error != "" {
			return nil, errors.New("citenexus: " + failure.Error)
		}
		return nil, errors.New("citenexus: unexpected units response: " + raw)
	}
	if units == nil {
		units = []DocUnit{}
	}
	return units, nil
}
