package models

import (
	"encoding/json"
	"strings"
)

// OpenAIEmbedding posts to an OpenAI-compatible /embeddings endpoint (§4b) and
// parses data[].embedding into dense float vectors, preserving input order.
type OpenAIEmbedding struct {
	baseURL   string
	model     string
	transport Transport
}

// NewOpenAIEmbedding builds an embedding client. Trailing "/" is stripped.
func NewOpenAIEmbedding(baseURL, model string, transport Transport) *OpenAIEmbedding {
	return &OpenAIEmbedding{
		baseURL:   strings.TrimRight(baseURL, "/"),
		model:     model,
		transport: transport,
	}
}

func (e *OpenAIEmbedding) endpoint() string {
	return e.baseURL + "/embeddings"
}

// Embed embeds texts into dense vectors, preserving input order.
func (e *OpenAIEmbedding) Embed(texts []string) ([][]float64, error) {
	if texts == nil {
		texts = []string{}
	}
	body, err := json.Marshal(map[string]any{"model": e.model, "input": texts})
	if err != nil {
		return nil, err
	}
	raw, err := e.transport(e.endpoint(), body, jsonHeaders())
	if err != nil {
		return nil, err
	}
	var payload struct {
		Data []struct {
			Embedding []float64 `json:"embedding"`
		} `json:"data"`
	}
	if err := json.Unmarshal(raw, &payload); err != nil {
		return nil, err
	}
	out := make([][]float64, len(payload.Data))
	for i, item := range payload.Data {
		out[i] = item.Embedding
	}
	return out, nil
}

// EmbedQuery embeds a single text — the ingest convenience.
func (e *OpenAIEmbedding) EmbedQuery(text string) ([]float64, error) {
	vecs, err := e.Embed([]string{text})
	if err != nil {
		return nil, err
	}
	if len(vecs) == 0 {
		return nil, nil
	}
	return vecs[0], nil
}
