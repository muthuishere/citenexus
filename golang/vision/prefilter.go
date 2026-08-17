// Package vision is the Go port of the §9 conditional-vision ORCHESTRATION —
// everything around the model call, none of the model call.
//
// Vision is an injected model, exactly like the generator and the embedder: the
// library hosts none of them. What it does own is deterministic and therefore
// portable by construction — the pre-filter that decides whether a model is
// called at all, the emitted request payload, the parse of the model's reply,
// and the assembly of citable figure Evidence Units. The model call itself is
// fulfilled by the HOST (ADR-0005 two-phase emit/fulfil), so no credential ever
// crosses into this package.
//
// Pure Go, no cgo, no native library (ADR-0010 tier 1). The pinned prompt is
// tier-2 shared data, generated into prompts.go from conformance/prompts.json.
//
// The contract is conformance/cases/vision_orchestration.json, asserted by
// vision_conformance_test.go and mirrored in Python and JS.
package vision

// Decision is one of the four routes an image can take through the §9
// pre-filter. Only DecisionVision spends a model call.
type Decision string

const (
	// DecisionText — text-native page: the page has an authoritative text layer
	// and is not rasterized. No image processing at all.
	DecisionText Decision = "text"
	// DecisionOCR — an embedded raster that is scanned text. Cheaper and more
	// faithful to OCR than to a VL model.
	DecisionOCR Decision = "ocr"
	// DecisionVision — a meaningful figure. The only outcome that spends a call.
	DecisionVision Decision = "vision"
	// DecisionSkip — decoration: too small a share of the page, or a
	// banner/strip aspect ratio.
	DecisionSkip Decision = "skip"
)

// PrefilterConfig holds the operator-tunable §9 thresholds. Mirrors
// python/src/citenexus/vision/prefilter.py:44 VisionPrefilterConfig, defaults
// included: a nil aspect bound disables that side of the check.
type PrefilterConfig struct {
	MinAreaRatio   float64
	SkipIfOCRDense bool
	MinAspectRatio *float64
	MaxAspectRatio *float64
}

// DefaultPrefilterConfig returns the reference defaults (0.05 / true / 0.125 / 8.0).
func DefaultPrefilterConfig() PrefilterConfig {
	minAspect, maxAspect := 0.125, 8.0
	return PrefilterConfig{
		MinAreaRatio:   0.05,
		SkipIfOCRDense: true,
		MinAspectRatio: &minAspect,
		MaxAspectRatio: &maxAspect,
	}
}

// ImageRef is a meaningful image asset — a candidate for conditional vision.
// Mirrors python/src/citenexus/extract/types.py:62.
type ImageRef struct {
	ImageID string `json:"image_id"`
	Page    *int   `json:"page,omitempty"`
	BBox    *BBox  `json:"bbox,omitempty"`
	Width   *int   `json:"width,omitempty"`
	Height  *int   `json:"height,omitempty"`
	// BlobKey is where the bytes live (a backend key), or nil if not persisted.
	BlobKey *string `json:"blob_key,omitempty"`
}

// Decide routes one image to text / ocr / vision / skip per the §9 table.
//
// pageArea is the area of the image's page in the same units as the image's
// width*height; pass nil for a text-native page (the pre-filter then returns
// DecisionText). ocrTextDense is the extractor's signal that the region is
// scanned text. Pure: no I/O, no network, no model call.
//
// Byte-for-byte port of vision/prefilter.py:62, including the ORDER of the
// guards — area before aspect before OCR-density — which is observable
// whenever more than one would fire.
func Decide(image ImageRef, pageArea *float64, ocrTextDense bool, config PrefilterConfig) Decision {
	// Pre-filter: text-native page → use the text layer; no image processing.
	if pageArea == nil {
		return DecisionText
	}

	width, height := 0, 0
	if image.Width != nil {
		width = *image.Width
	}
	if image.Height != nil {
		height = *image.Height
	}
	imageArea := float64(width * height)
	areaRatio := 0.0
	if *pageArea > 0 {
		areaRatio = imageArea / *pageArea
	}

	// Decoration: too small a share of the page to carry answerable content.
	if areaRatio < config.MinAreaRatio {
		return DecisionSkip
	}

	// Decoration: banner/strip aspect ratios (very wide or very tall).
	if width > 0 && height > 0 {
		aspect := float64(width) / float64(height)
		if config.MaxAspectRatio != nil && aspect > *config.MaxAspectRatio {
			return DecisionSkip
		}
		if config.MinAspectRatio != nil && aspect < *config.MinAspectRatio {
			return DecisionSkip
		}
	}

	// Scanned-text raster: cheaper and more faithful to OCR than to a VL model.
	if ocrTextDense && config.SkipIfOCRDense {
		return DecisionOCR
	}

	// A meaningful figure: this is what vision is for.
	return DecisionVision
}
