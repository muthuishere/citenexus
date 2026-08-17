package models

import (
	"encoding/base64"
	"encoding/json"
	"strings"
)

// OpenAIVision is the injected VL endpoint behind §9 conditional vision.
//
// CiteNexus bundles no models: image description comes from an injected,
// OpenAI-compatible VISION endpoint (Gemini's OpenAI-compat endpoint, GPT-4o, a
// local VL server). Vision is a model like the generator and the embedder, so it
// sits in this package with them, behind the same Transport seam and the same
// rule: a key/secret NEVER enters this struct — auth is ${ENV} templates in
// headers, expanded by the transport at the request boundary (http.go:22).
//
// Its DescribePayload method is exactly the ADR-0005 host-side fulfiller shape,
// so it drops straight into vision.FulfillRequests as a method value:
//
//	fulfilled := vision.FulfillRequests(requests, client.DescribePayload)
//
// Mirrors python/src/citenexus/vision/client.py:66 OpenAICompatibleVision.
type OpenAIVision struct {
	baseURL     string
	model       string
	temperature float64
	maxTokens   *int
	mimeType    string
	transport   Transport
	headers     map[string]string
}

// DefaultVisionMimeType is the media type Describe stamps on raw bytes it is
// handed directly. The two-phase emit path does NOT use it — vision.ImageDataURI
// sniffs the true subtype from the magic bytes.
const DefaultVisionMimeType = "image/png"

// NewOpenAIVision builds a vision client. Trailing "/" is stripped from baseURL;
// maxTokens is nil to omit it from the request body; an empty mimeType defaults
// to image/png. Pass WithHeaders(...) for first-class ${ENV} auth headers.
func NewOpenAIVision(baseURL, model string, temperature float64, maxTokens *int, mimeType string, transport Transport, opts ...Option) *OpenAIVision {
	if mimeType == "" {
		mimeType = DefaultVisionMimeType
	}
	return &OpenAIVision{
		baseURL:     strings.TrimRight(baseURL, "/"),
		model:       model,
		temperature: temperature,
		maxTokens:   maxTokens,
		mimeType:    mimeType,
		transport:   transport,
		headers:     applyOptions(opts),
	}
}

func (v *OpenAIVision) endpoint() string {
	return v.baseURL + "/chat/completions"
}

// Describe encodes raw image bytes with this client's configured mimeType and
// the given prompt, then completes. The standalone (non-two-phase) entry.
func (v *OpenAIVision) Describe(data []byte, prompt string) (map[string]any, error) {
	dataURI := "data:" + v.mimeType + ";base64," + base64.StdEncoding.EncodeToString(data)
	return v.complete(dataURI, prompt)
}

// DescribePayload fulfills a two-phase vision.PendingRequest: it POSTs the
// core's already-assembled image_url data URI + prompt VERBATIM (no re-encode),
// so what goes on the wire is exactly the emitted payload every port reproduces.
func (v *OpenAIVision) DescribePayload(imageURL, prompt string) (map[string]any, error) {
	return v.complete(imageURL, prompt)
}

// complete POSTs one prompt + image_url to /chat/completions and parses the reply.
func (v *OpenAIVision) complete(imageURL, prompt string) (map[string]any, error) {
	request := map[string]any{
		"model": v.model,
		"messages": []any{
			map[string]any{
				"role": "user",
				"content": []any{
					map[string]any{"type": "text", "text": prompt},
					map[string]any{"type": "image_url", "image_url": map[string]any{"url": imageURL}},
				},
			},
		},
		// Always sent — a grounded description must be deterministic (§9).
		"temperature": v.temperature,
	}
	if v.maxTokens != nil {
		request["max_tokens"] = *v.maxTokens
	}
	body, err := json.Marshal(request)
	if err != nil {
		return nil, err
	}
	raw, err := v.transport(v.endpoint(), body, wireHeaders(v.headers))
	if err != nil {
		return nil, err
	}
	var payload struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}
	if err := json.Unmarshal(raw, &payload); err != nil {
		return nil, err
	}
	if len(payload.Choices) == 0 {
		return ParseVisionDescription(""), nil
	}
	return ParseVisionDescription(payload.Choices[0].Message.Content), nil
}

// ParseVisionDescription parses a model's reply into a record mapping.
//
// A well-behaved model returns JSON; a model that ignores the instruction and
// returns prose still yields a usable short_caption rather than failing — the
// degrade path, which must never invent structure the model did not produce.
// Port of vision/client.py:145 _parse_description, fence handling included.
func ParseVisionDescription(content string) map[string]any {
	text := strings.TrimSpace(content)
	if strings.HasPrefix(text, "```") {
		// strip a ```json … ``` fence if present
		text = strings.Trim(text, "`")
		if strings.HasPrefix(strings.ToLower(text), "json") {
			text = text[4:]
		}
		text = strings.TrimSpace(text)
	}
	var parsed any
	if err := json.Unmarshal([]byte(text), &parsed); err != nil {
		return map[string]any{"short_caption": strings.TrimSpace(content)}
	}
	mapping, ok := parsed.(map[string]any)
	if !ok {
		return map[string]any{"short_caption": strings.TrimSpace(content)}
	}
	return mapping
}
