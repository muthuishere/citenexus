package models

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"os"
	"strings"
	"testing"
)

// OpenAIVision — describe an image over an injected VL endpoint (§9).
//
// Mirrors python/tests/vision/test_vision_client.py: injected transport,
// temperature always sent, the image base64-encoded into an OpenAI image_url
// data URI, a non-JSON reply degrading to a usable caption. Plus the two things
// only a port test can prove: that DescribePayload sends the emitted payload
// VERBATIM, and that no key VALUE ever lives on the client.

var visionPNG = []byte("\x89PNG\r\n\x1a\n fake image bytes")

type recordingVisionTransport struct {
	description map[string]any
	calls       []struct {
		url     string
		body    []byte
		headers map[string]string
	}
}

func (r *recordingVisionTransport) send(url string, body []byte, headers map[string]string) ([]byte, error) {
	r.calls = append(r.calls, struct {
		url     string
		body    []byte
		headers map[string]string
	}{url, body, headers})
	content, err := json.Marshal(r.description)
	if err != nil {
		return nil, err
	}
	return json.Marshal(map[string]any{
		"choices": []any{map[string]any{"message": map[string]any{"content": string(content)}}},
	})
}

func (r *recordingVisionTransport) lastBody(t *testing.T) map[string]any {
	t.Helper()
	if len(r.calls) == 0 {
		t.Fatal("no call recorded")
	}
	var body map[string]any
	if err := json.Unmarshal(r.calls[len(r.calls)-1].body, &body); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	return body
}

func newRecordingVisionTransport() *recordingVisionTransport {
	return &recordingVisionTransport{description: map[string]any{
		"short_caption":        "Revenue chart",
		"detailed_description": "A line chart of revenue over four quarters.",
		"objects":              []any{"axis", "line"},
		"relationships":        []any{"revenue rises each quarter"},
		"ocr_text":             "Q1 Q2 Q3 Q4",
	}}
}

func TestVisionDescribeReturnsRecordFields(t *testing.T) {
	transport := newRecordingVisionTransport()
	client := NewOpenAIVision("http://vl.test/v1", "gemini-2.5-flash", 0.0, nil, "", transport.send)
	out, err := client.Describe(visionPNG, "describe it")
	if err != nil {
		t.Fatalf("describe: %v", err)
	}
	if out["short_caption"] != "Revenue chart" {
		t.Fatalf("short_caption: got %v", out["short_caption"])
	}
	if out["ocr_text"] != "Q1 Q2 Q3 Q4" {
		t.Fatalf("ocr_text: got %v", out["ocr_text"])
	}
}

func TestVisionPostsImageAsBase64DataURIWithTemperature(t *testing.T) {
	transport := newRecordingVisionTransport()
	client := NewOpenAIVision("http://vl.test/v1/", "m", 0.0, nil, "", transport.send)
	if _, err := client.Describe(visionPNG, "describe it"); err != nil {
		t.Fatalf("describe: %v", err)
	}
	call := transport.calls[0]
	if call.url != "http://vl.test/v1/chat/completions" {
		t.Fatalf("url: got %q", call.url)
	}
	blob := string(call.body)
	if !strings.Contains(blob, "data:image/png;base64,") {
		t.Fatal("the payload does not carry a data URI")
	}
	if !strings.Contains(blob, base64.StdEncoding.EncodeToString(visionPNG)) {
		t.Fatal("the payload does not carry the image bytes")
	}
	// Always sent — a grounded description must be deterministic (§9).
	if got := transport.lastBody(t)["temperature"]; got != 0.0 {
		t.Fatalf("temperature: got %v, want 0", got)
	}
	if _, present := transport.lastBody(t)["max_tokens"]; present {
		t.Fatal("max_tokens must be omitted when unset")
	}
}

func TestVisionDescribePayloadSendsTheEmittedPayloadVerbatim(t *testing.T) {
	// The ADR-0005 seam: the core already assembled the data URI, so the host
	// must NOT re-encode it — otherwise what goes on the wire is not what the
	// conformance fixture pinned.
	transport := newRecordingVisionTransport()
	client := NewOpenAIVision("http://vl.test/v1", "m", 0.0, nil, "", transport.send)
	emitted := "data:image/jpeg;base64,QUJD"
	if _, err := client.DescribePayload(emitted, "the pinned prompt"); err != nil {
		t.Fatalf("describe payload: %v", err)
	}
	blob := string(transport.calls[0].body)
	if !strings.Contains(blob, emitted) {
		t.Fatalf("the emitted image_url was not sent verbatim: %s", blob)
	}
	if !strings.Contains(blob, "the pinned prompt") {
		t.Fatal("the emitted prompt was not sent verbatim")
	}
}

func TestVisionAuthIsAnEnvTemplateNeverAValue(t *testing.T) {
	// The hard rule: a key VALUE never enters the client. It holds a ${ENV}
	// template and the transport expands it at the request boundary.
	t.Setenv("CITENEXUS_TEST_VL_KEY", "super-secret-value")
	transport := newRecordingVisionTransport()
	client := NewOpenAIVision("http://vl.test/v1", "m", 0.0, nil, "",
		transport.send, WithHeaders(map[string]string{"Authorization": "Bearer ${CITENEXUS_TEST_VL_KEY}"}))
	if _, err := client.Describe(visionPNG, "p"); err != nil {
		t.Fatalf("describe: %v", err)
	}
	// What the client hands the transport is the TEMPLATE, unexpanded.
	if got := transport.calls[0].headers["Authorization"]; got != "Bearer ${CITENEXUS_TEST_VL_KEY}" {
		t.Fatalf("client materialized a secret: %q", got)
	}
	// Only the transport resolves it, for one request.
	resolved := NewHTTPClient(nil, 0).ResolveHeaders(transport.calls[0].headers)
	if resolved["Authorization"] != "Bearer "+os.Getenv("CITENEXUS_TEST_VL_KEY") {
		t.Fatalf("transport did not expand the template: %q", resolved["Authorization"])
	}
}

func TestVisionTransportErrorPropagates(t *testing.T) {
	// A failed call must be an ERROR the fulfiller can drop the request on —
	// never a silently empty description that assembles into a fabricated unit.
	failing := func(string, []byte, map[string]string) ([]byte, error) {
		return nil, errors.New("boom")
	}
	client := NewOpenAIVision("http://vl.test/v1", "m", 0.0, nil, "", failing)
	if _, err := client.DescribePayload("data:image/png;base64,QQ==", "p"); err == nil {
		t.Fatal("a transport failure must surface as an error")
	}
}

func TestParseVisionDescription(t *testing.T) {
	cases := []struct {
		name    string
		content string
		want    map[string]any
	}{
		{
			"plain json",
			`{"short_caption": "A chart"}`,
			map[string]any{"short_caption": "A chart"},
		},
		{
			// A model that wraps its JSON in a markdown fence still parses.
			"fenced json",
			"```json\n{\"short_caption\": \"A chart\"}\n```",
			map[string]any{"short_caption": "A chart"},
		},
		{
			// A model that ignores the JSON instruction still yields a usable
			// caption — degrade, not fail, and nothing invented beyond the
			// model's own words.
			"prose degrades to a caption",
			"Just a plain sentence.",
			map[string]any{"short_caption": "Just a plain sentence."},
		},
		{
			// A JSON array is not a record; the reference falls back too.
			"non-object json degrades to a caption",
			`["a", "b"]`,
			map[string]any{"short_caption": `["a", "b"]`},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := ParseVisionDescription(tc.content)
			gotJSON, _ := json.Marshal(got)
			wantJSON, _ := json.Marshal(tc.want)
			if string(gotJSON) != string(wantJSON) {
				t.Fatalf("got %s, want %s", gotJSON, wantJSON)
			}
		})
	}
}
