package vision

import "testing"

// The §9 vision decision table as fixtures — one scenario per row, mirroring
// python/tests/vision/test_prefilter.py case for case. The pre-filter has no
// conformance vector of its own (conformance/cases/vision_orchestration.json
// pins emit/fulfil/assemble only), so these rows ARE the parity check: they are
// the reference's own inputs and the reference's own verdicts, copied as data.

func intp(v int) *int { return &v }

func areap(v float64) *float64 { return &v }

func imageOf(id string, width, height int) ImageRef {
	page := 1
	return ImageRef{ImageID: id, Page: &page, Width: intp(width), Height: intp(height)}
}

func TestPrefilterConfigDefaults(t *testing.T) {
	cfg := DefaultPrefilterConfig()
	if cfg.MinAreaRatio != 0.05 {
		t.Fatalf("MinAreaRatio: got %v, want 0.05", cfg.MinAreaRatio)
	}
	if !cfg.SkipIfOCRDense {
		t.Fatal("SkipIfOCRDense: got false, want true")
	}
	if cfg.MinAspectRatio == nil || cfg.MaxAspectRatio == nil {
		t.Fatal("the banner/strip aspect guards default to non-nil bounds")
	}
}

func TestDecisionTable(t *testing.T) {
	noOCRSkip := DefaultPrefilterConfig()
	noOCRSkip.SkipIfOCRDense = false

	cases := []struct {
		name     string
		image    ImageRef
		pageArea *float64
		ocrDense bool
		config   PrefilterConfig
		want     Decision
	}{
		{
			// A text-native page has an authoritative text layer (no rasterized
			// page): callers signal it with a nil page area, and the pre-filter
			// short-circuits before any image work at all.
			"text-native page routes to text",
			imageOf("img-text", 400, 300), nil, false, DefaultPrefilterConfig(), DecisionText,
		},
		{
			// An embedded raster that is scanned text → OCR, not a VL model.
			"ocr-dense raster routes to ocr",
			imageOf("img-scan", 900, 900), areap(1_000_000.0), true, DefaultPrefilterConfig(), DecisionOCR,
		},
		{
			// Clears area and aspect, is not OCR-dense: the only row that spends
			// a model call.
			"meaningful figure routes to vision",
			imageOf("img-fig", 600, 400), areap(1_000_000.0), false, DefaultPrefilterConfig(), DecisionVision,
		},
		{
			// area_ratio = 0.0064 < 0.05.
			"tiny decoration below the area ratio skips",
			imageOf("img-deco", 80, 80), areap(1_000_000.0), false, DefaultPrefilterConfig(), DecisionSkip,
		},
		{
			// area_ratio = 0.05 clears the area guard; aspect = 20 does not.
			"banner aspect skips",
			imageOf("img-banner", 2000, 100), areap(4_000_000.0), false, DefaultPrefilterConfig(), DecisionSkip,
		},
		{
			// The toggle is honored: with it off, an OCR-dense but meaningful
			// image is sent to vision instead of OCR.
			"skip_if_ocr_dense=false routes meaningful to vision",
			imageOf("img-scan", 900, 900), areap(1_000_000.0), true, noOCRSkip, DecisionVision,
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := Decide(tc.image, tc.pageArea, tc.ocrDense, tc.config); got != tc.want {
				t.Fatalf("got %q, want %q", got, tc.want)
			}
		})
	}
}

func TestZeroPageAreaIsNotADivideByZero(t *testing.T) {
	// pageArea == 0 yields ratio 0.0 in the reference (prefilter.py:83), which
	// falls below min_area_ratio — skip, not NaN and not a panic.
	zero := 0.0
	got := Decide(imageOf("img", 100, 100), &zero, false, DefaultPrefilterConfig())
	if got != DecisionSkip {
		t.Fatalf("got %q, want %q", got, DecisionSkip)
	}
}
