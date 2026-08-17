package vision

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"reflect"
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// The §9 two-phase vision vectors, asserted as a BINDING contract.
//
// conformance/cases/vision_orchestration.json is the cross-port contract for
// vision ORCHESTRATION — emit -> fulfil -> assemble, with only the raw model
// call in the middle per-host (ADR-0005). Vision is an injected model like the
// generator and the embedder, so everything around the call is deterministic and
// ports natively (ADR-0010 tier 1).
// python/tests/conformance/test_vision_orchestration_vectors.py holds the
// reference to exactly this file and js/src/vision/vision-conformance.test.ts
// holds JS; this holds Go, reading the committed JSON as OPAQUE DATA and
// asserting every expectation with counts pinned exactly.

type visionCase struct {
	DocumentID string `json:"document_id"`
	SourceURI  string `json:"source_uri"`
	Language   string `json:"language"`
	Images     []struct {
		ImageID  string `json:"image_id"`
		BytesB64 string `json:"bytes_b64"`
	} `json:"images"`
	Emit         []json.RawMessage          `json:"emit"`
	Fulfilled    map[string]json.RawMessage `json:"fulfilled"`
	AssembledEUs []json.RawMessage          `json:"assembled_eus"`
	Degrade      struct {
		Fulfilled      map[string]json.RawMessage `json:"fulfilled"`
		AssembledEUIDs []string                   `json:"assembled_eu_ids"`
	} `json:"degrade"`
}

// The emitted request, decoded only as far as this test needs to replay it.
type emittedShape struct {
	RequestID string `json:"request_id"`
	Payload   struct {
		Prompt   string `json:"prompt"`
		ImageURL string `json:"image_url"`
	} `json:"payload"`
	SourceRef struct {
		Page *int  `json:"page"`
		BBox *BBox `json:"bbox"`
	} `json:"source_ref"`
}

// Pinned EXACTLY. A vector silently dropped from the fixture is a weakened
// contract that no per-case assertion can see.
const (
	expectedImages        = 2
	expectedEmitted       = 2
	expectedFulfilled     = 2
	expectedAssembled     = 2
	expectedDegradedUnits = 1
)

func loadVisionCase(t *testing.T) visionCase {
	t.Helper()
	var c visionCase
	conform.Case(t, "vision_orchestration.json", &c)
	return c
}

func decodeEmitted(t *testing.T, raw []json.RawMessage) []emittedShape {
	t.Helper()
	out := make([]emittedShape, 0, len(raw))
	for _, item := range raw {
		var shape emittedShape
		if err := json.Unmarshal(item, &shape); err != nil {
			t.Fatalf("decode emitted: %v", err)
		}
		out = append(out, shape)
	}
	return out
}

// jsonEqual compares a Go value's serialization to a committed fixture blob by
// value, not by byte order — key order in a JSON object is not part of the
// contract, but every key and every value is.
func jsonEqual(t *testing.T, got any, want json.RawMessage, label string) {
	t.Helper()
	gotBytes, err := json.Marshal(got)
	if err != nil {
		t.Fatalf("%s: marshal: %v", label, err)
	}
	var gotAny, wantAny any
	if err := json.Unmarshal(gotBytes, &gotAny); err != nil {
		t.Fatalf("%s: re-decode: %v", label, err)
	}
	if err := json.Unmarshal(want, &wantAny); err != nil {
		t.Fatalf("%s: decode fixture: %v", label, err)
	}
	if !reflect.DeepEqual(gotAny, wantAny) {
		t.Fatalf("%s mismatch:\n got: %s\nwant: %s", label, gotBytes, want)
	}
}

// emitFromFixture drives the fixture's IMAGES (not its expectations) through the
// real emit phase, taking the prompt from the port's own embedded copy so a
// paraphrase fails here instead of quietly agreeing with itself.
func emitFromFixture(t *testing.T, c visionCase) []PendingRequest {
	t.Helper()
	expected := decodeEmitted(t, c.Emit)
	requests := make([]PendingRequest, 0, len(c.Images))
	for i, image := range c.Images {
		data, err := base64.StdEncoding.DecodeString(image.BytesB64)
		if err != nil {
			t.Fatalf("decode image %s: %v", image.ImageID, err)
		}
		sourceURI := c.SourceURI
		requests = append(requests, BuildPendingRequest(
			c.DocumentID, image.ImageID, data, DescribePrompt(),
			BuildRequestOptions{
				Page:      expected[i].SourceRef.Page,
				BBox:      expected[i].SourceRef.BBox,
				SourceURI: &sourceURI,
			},
		))
	}
	return requests
}

// fixtureFulfiller replays the fixture's own responses in place of the model,
// keyed on the EMITTED image_url — a port that emitted a different data URI
// would not find its response here, which is what makes the substitution honest.
func fixtureFulfiller(t *testing.T, c visionCase, failing map[string]bool) Fulfiller {
	t.Helper()
	byImageURL := map[string]map[string]any{}
	for _, emitted := range decodeEmitted(t, c.Emit) {
		var mapping map[string]any
		if err := json.Unmarshal(c.Fulfilled[emitted.RequestID], &mapping); err != nil {
			t.Fatalf("decode fulfilled %s: %v", emitted.RequestID, err)
		}
		byImageURL[emitted.Payload.ImageURL] = mapping
	}
	return func(imageURL, prompt string) (map[string]any, error) {
		if failing[imageURL] {
			return nil, errors.New("vision endpoint failed for this image")
		}
		if prompt != DescribePrompt() {
			t.Fatalf("the host must be handed the emitted prompt verbatim")
		}
		mapping, ok := byImageURL[imageURL]
		if !ok {
			t.Fatalf("no fixture response for emitted image_url %q", imageURL)
		}
		return mapping, nil
	}
}

func fixturePartition(t *testing.T, c visionCase) PartitionPath {
	t.Helper()
	var eu struct {
		Partition PartitionPath `json:"partition"`
	}
	if err := json.Unmarshal(c.AssembledEUs[0], &eu); err != nil {
		t.Fatalf("decode partition: %v", err)
	}
	return eu.Partition
}

func TestVisionVectorCountsArePinned(t *testing.T) {
	c := loadVisionCase(t)
	if len(c.Images) != expectedImages {
		t.Fatalf("images: got %d, want %d", len(c.Images), expectedImages)
	}
	if len(c.Emit) != expectedEmitted {
		t.Fatalf("emit: got %d, want %d", len(c.Emit), expectedEmitted)
	}
	if len(c.Fulfilled) != expectedFulfilled {
		t.Fatalf("fulfilled: got %d, want %d", len(c.Fulfilled), expectedFulfilled)
	}
	if len(c.AssembledEUs) != expectedAssembled {
		t.Fatalf("assembled_eus: got %d, want %d", len(c.AssembledEUs), expectedAssembled)
	}
	if len(c.Degrade.AssembledEUIDs) != expectedDegradedUnits {
		t.Fatalf("degrade units: got %d, want %d", len(c.Degrade.AssembledEUIDs), expectedDegradedUnits)
	}
}

func TestVisionPromptIsThePinnedPrompt(t *testing.T) {
	// The embedded copy must equal the canonical conformance/prompts.json…
	var prompts map[string]string
	conform.Data(t, "prompts.json", &prompts)
	if DescribePrompt() != prompts["vision_describe"] {
		t.Fatalf("embedded vision prompt drifted from conformance/prompts.json")
	}
	// …and the prompt actually pinned inside every emitted payload.
	c := loadVisionCase(t)
	for _, emitted := range decodeEmitted(t, c.Emit) {
		if emitted.Payload.Prompt != prompts["vision_describe"] {
			t.Fatalf("%s: emitted prompt is not the pinned prompt", emitted.RequestID)
		}
	}
}

func TestEmittedRequestsMatchTheFixture(t *testing.T) {
	c := loadVisionCase(t)
	requests := emitFromFixture(t, c)
	if len(requests) != len(c.Emit) {
		t.Fatalf("emitted %d requests, fixture pins %d", len(requests), len(c.Emit))
	}
	for i, request := range requests {
		jsonEqual(t, request, c.Emit[i], "emit["+request.RequestID+"]")
	}
}

func TestEmittedPayloadDeclaresTheTrueMediaType(t *testing.T) {
	// The fixture's value is that the payload declares each image's TRUE type,
	// sniffed from the magic bytes — a port that hardcoded image/png passes the
	// first vector and fails the second.
	c := loadVisionCase(t)
	requests := emitFromFixture(t, c)
	want := []string{"data:image/png;base64,", "data:image/jpeg;base64,"}
	for i, request := range requests {
		if len(request.Payload.ImageURL) < len(want[i]) || request.Payload.ImageURL[:len(want[i])] != want[i] {
			t.Fatalf("request %d: image_url does not start with %q", i, want[i])
		}
	}
}

func TestFulfilJoinsEveryResponseByRequestID(t *testing.T) {
	c := loadVisionCase(t)
	requests := emitFromFixture(t, c)
	fulfilled := FulfillRequests(requests, fixtureFulfiller(t, c, nil))
	if len(fulfilled) != len(c.Fulfilled) {
		t.Fatalf("fulfilled %d, fixture pins %d", len(fulfilled), len(c.Fulfilled))
	}
	for requestID, want := range c.Fulfilled {
		record, ok := fulfilled[requestID]
		if !ok {
			t.Fatalf("missing fulfilled record for %s", requestID)
		}
		jsonEqual(t, record, want, "fulfilled["+requestID+"]")
	}
}

func TestAssembledUnitsMatchTheFixture(t *testing.T) {
	c := loadVisionCase(t)
	requests := emitFromFixture(t, c)
	fulfilled := FulfillRequests(requests, fixtureFulfiller(t, c, nil))
	units := BuildUnits(requests, fulfilled, BuildUnitOptions{
		Partition: fixturePartition(t, c),
		Language:  c.Language,
	})
	if len(units) != len(c.AssembledEUs) {
		t.Fatalf("assembled %d units, fixture pins %d", len(units), len(c.AssembledEUs))
	}
	for i, unit := range units {
		jsonEqual(t, unit, c.AssembledEUs[i], "assembled_eus["+unit.EuID+"]")
	}
}

func TestAFailingModelCallDegradesAndNeverFabricates(t *testing.T) {
	// The degrade path, driven end-to-end: the first image's model call FAILS.
	// Per-request isolation means the second image still produces its unit, and
	// the first produces none — not an empty caption, not a placeholder.
	c := loadVisionCase(t)
	requests := emitFromFixture(t, c)
	failing := map[string]bool{requests[0].Payload.ImageURL: true}
	fulfilled := FulfillRequests(requests, fixtureFulfiller(t, c, failing))

	if len(fulfilled) != len(c.Degrade.Fulfilled) {
		t.Fatalf("degrade fulfilled %d, fixture pins %d", len(fulfilled), len(c.Degrade.Fulfilled))
	}
	for requestID, want := range c.Degrade.Fulfilled {
		record, ok := fulfilled[requestID]
		if !ok {
			t.Fatalf("degrade: missing fulfilled record for %s", requestID)
		}
		jsonEqual(t, record, want, "degrade.fulfilled["+requestID+"]")
	}

	units := BuildUnits(requests, fulfilled, BuildUnitOptions{
		Partition: fixturePartition(t, c),
		Language:  c.Language,
	})
	got := make([]string, 0, len(units))
	for _, unit := range units {
		got = append(got, unit.EuID)
	}
	if !reflect.DeepEqual(got, c.Degrade.AssembledEUIDs) {
		t.Fatalf("degrade eu_ids: got %v, want %v", got, c.Degrade.AssembledEUIDs)
	}
	for _, id := range got {
		if id == requests[0].RequestID {
			t.Fatalf("fabricated a unit for the image whose model call failed")
		}
	}
}

func TestAnEmptyDescriptionYieldsNoUnit(t *testing.T) {
	// A model that returns junk (no caption, no description) must also degrade —
	// an EU whose text is empty is a citation to nothing.
	c := loadVisionCase(t)
	requests := emitFromFixture(t, c)
	fulfilled := FulfillRequests(requests, func(string, string) (map[string]any, error) {
		return map[string]any{}, nil
	})
	if len(fulfilled) != expectedFulfilled {
		t.Fatalf("fulfilled %d, want %d", len(fulfilled), expectedFulfilled)
	}
	units := BuildUnits(requests, fulfilled, BuildUnitOptions{
		Partition: fixturePartition(t, c),
		Language:  c.Language,
	})
	if len(units) != 0 {
		t.Fatalf("an empty description produced %d units, want 0", len(units))
	}
}
