// Package models is the Go port of CiteNexus's §5 injectable HTTP model clients:
// an OpenAI-compatible chat generator, an Anthropic generator, and an
// OpenAI-compatible embedding client. Each client takes an injected Transport so
// tests stay hermetic (no network). Auth is the endpoint layer's job — these
// clients NEVER carry a key/secret; headers are always just JSON.
package models

import (
	"encoding/json"
	"strings"
)

// Transport is the single seam every model client posts through:
// (url, jsonBody, headers) -> responseBytes. Tests inject a fake; there is no
// real net/http default at this stage (SPEC §5 — constructor takes a transport).
type Transport func(url string, body []byte, headers map[string]string) ([]byte, error)

// SystemPrompt is the pinned "grounded_answer" prompt (conformance/prompts.json).
// It must match byte-for-byte — both generators send it verbatim.
const SystemPrompt = "You are a strict, evidence-first assistant. Answer the question by quoting " +
	"the exact sentence or phrase from the provided passage that answers it — " +
	"VERBATIM, word for word, with no rephrasing, no added words, and no " +
	"commentary. If the passage does not contain the answer, say you cannot " +
	"answer from the evidence. The verifier rejects any word not present in the " +
	"passage, so never paraphrase. Quote in the passage's own language when it " +
	"matches the requested ISO code; otherwise still prefer the passage's exact " +
	"wording."

// jsonHeaders is the only header set these wire clients speak. Auth + provider
// headers belong to the endpoint layer, never here.
func jsonHeaders() map[string]string {
	return map[string]string{"Content-Type": "application/json"}
}

// buildUserPrompt is the shared user message for both generators.
func buildUserPrompt(question, passage, answerLanguage string) string {
	return "Answer language (ISO code): " + answerLanguage + "\n\n" +
		"Passage:\n" + passage + "\n\n" +
		"Question: " + question
}

// OpenAIChatGenerator posts grounded answers to an OpenAI-compatible
// /chat/completions endpoint (§4b). Temperature is ALWAYS sent (default 0.0);
// max_tokens rides along only when configured.
type OpenAIChatGenerator struct {
	baseURL     string
	model       string
	temperature float64
	maxTokens   *int
	transport   Transport
}

// NewOpenAIChatGenerator builds a chat generator. Trailing "/" is stripped from
// baseURL; maxTokens is nil to omit it from the request body.
func NewOpenAIChatGenerator(baseURL, model string, temperature float64, maxTokens *int, transport Transport) *OpenAIChatGenerator {
	return &OpenAIChatGenerator{
		baseURL:     strings.TrimRight(baseURL, "/"),
		model:       model,
		temperature: temperature,
		maxTokens:   maxTokens,
		transport:   transport,
	}
}

func (g *OpenAIChatGenerator) endpoint() string {
	return g.baseURL + "/chat/completions"
}

// Answer generates a grounded answer from passage in answerLanguage.
func (g *OpenAIChatGenerator) Answer(question, passage, answerLanguage string) (string, error) {
	request := map[string]any{
		"model": g.model,
		"messages": []any{
			map[string]any{"role": "system", "content": SystemPrompt},
			map[string]any{"role": "user", "content": buildUserPrompt(question, passage, answerLanguage)},
		},
		// Always sent — a grounded answer must be deterministic (§4b).
		"temperature": g.temperature,
	}
	if g.maxTokens != nil {
		request["max_tokens"] = *g.maxTokens
	}
	body, err := json.Marshal(request)
	if err != nil {
		return "", err
	}
	raw, err := g.transport(g.endpoint(), body, jsonHeaders())
	if err != nil {
		return "", err
	}
	var payload struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}
	if err := json.Unmarshal(raw, &payload); err != nil {
		return "", err
	}
	if len(payload.Choices) == 0 {
		return "", nil
	}
	return payload.Choices[0].Message.Content, nil
}
