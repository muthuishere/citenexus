package models

import (
	"encoding/json"
	"strings"
)

// DefaultAnthropicBaseURL is used when the caller passes an empty base URL.
const DefaultAnthropicBaseURL = "https://api.anthropic.com"

// DefaultAnthropicMaxTokens is Anthropic's required max_tokens default (§4b).
const DefaultAnthropicMaxTokens = 1024

// AnthropicGenerator posts grounded answers to Anthropic's native /v1/messages
// endpoint (§4b): system is a top-level field, max_tokens is REQUIRED, and the
// reply is the concatenation of the text blocks in content[].
type AnthropicGenerator struct {
	baseURL     string
	model       string
	temperature float64
	maxTokens   int
	transport   Transport
	headers     map[string]string
}

// NewAnthropicGenerator builds an Anthropic generator. An empty baseURL defaults
// to https://api.anthropic.com; trailing "/" is stripped. Pass WithHeaders(...)
// for first-class ${ENV} auth headers (e.g. {"x-api-key": "${ANTHROPIC_API_KEY}"}).
func NewAnthropicGenerator(baseURL, model string, temperature float64, maxTokens int, transport Transport, opts ...Option) *AnthropicGenerator {
	if baseURL == "" {
		baseURL = DefaultAnthropicBaseURL
	}
	return &AnthropicGenerator{
		baseURL:     strings.TrimRight(baseURL, "/"),
		model:       model,
		temperature: temperature,
		maxTokens:   maxTokens,
		transport:   transport,
		headers:     applyOptions(opts),
	}
}

func (g *AnthropicGenerator) endpoint() string {
	return g.baseURL + "/v1/messages"
}

// Answer generates a grounded answer from passage in answerLanguage.
func (g *AnthropicGenerator) Answer(question, passage, answerLanguage string) (string, error) {
	request := map[string]any{
		"model":  g.model,
		"system": SystemPrompt,
		"messages": []any{
			map[string]any{"role": "user", "content": buildUserPrompt(question, passage, answerLanguage)},
		},
		// max_tokens is required; temperature keeps answers deterministic (§4b).
		"max_tokens":  g.maxTokens,
		"temperature": g.temperature,
	}
	body, err := json.Marshal(request)
	if err != nil {
		return "", err
	}
	raw, err := g.transport(g.endpoint(), body, wireHeaders(g.headers))
	if err != nil {
		return "", err
	}
	var payload struct {
		Content []struct {
			Type string `json:"type"`
			Text string `json:"text"`
		} `json:"content"`
	}
	if err := json.Unmarshal(raw, &payload); err != nil {
		return "", err
	}
	var sb strings.Builder
	for _, block := range payload.Content {
		if block.Type == "text" {
			sb.WriteString(block.Text)
		}
	}
	return sb.String(), nil
}
