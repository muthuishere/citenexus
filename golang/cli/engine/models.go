package engine

import (
	"fmt"

	"github.com/muthuishere/citenexus/golang/cli/config"
	"github.com/muthuishere/citenexus/golang/fakes"
	"github.com/muthuishere/citenexus/golang/models"
)

// NewEmbedder builds an Embedder from a model config. provider "fake" is the
// deterministic offline double; anything else is an OpenAI-compatible HTTP client
// whose ${ENV} auth headers are expanded only at the request edge. nil config ⇒
// nil embedder (lexical-only).
func NewEmbedder(mc *config.ModelConfig) (Embedder, error) {
	if mc == nil {
		return nil, nil
	}
	if mc.Provider == "fake" {
		return fakeEmbedder{}, nil
	}
	if mc.BaseURL == "" || mc.Model == "" {
		return nil, fmt.Errorf("models: embedding needs base_url and model (or provider: fake)")
	}
	http := models.NewHTTPClient(nil, 0)
	client := models.NewOpenAIEmbedding(mc.BaseURL, mc.Model, http.Transport(), models.WithHeaders(mc.Headers))
	return openAIEmbedder{client: client}, nil
}

// NewGenerator builds a Generator from a model config, same rules as NewEmbedder.
// nil config ⇒ nil generator (Ask will report no llm configured).
func NewGenerator(mc *config.ModelConfig) (Generator, error) {
	if mc == nil {
		return nil, nil
	}
	if mc.Provider == "fake" {
		return fakeGenerator{}, nil
	}
	if mc.BaseURL == "" || mc.Model == "" {
		return nil, fmt.Errorf("models: llm needs base_url and model (or provider: fake)")
	}
	http := models.NewHTTPClient(nil, 0)
	client := models.NewOpenAIChatGenerator(mc.BaseURL, mc.Model, 0.0, nil, http.Transport(), models.WithHeaders(mc.Headers))
	return client, nil // *OpenAIChatGenerator already satisfies Generator
}

// --- fake doubles (hermetic) ---

type fakeEmbedder struct{}

func (fakeEmbedder) Embed(text string) ([]float64, error) {
	return fakes.FakeEmbedding{}.Embed(text), nil
}

type fakeGenerator struct{}

// Answer ignores answerLanguage — the fake echoes the passage verbatim so the
// faithfulness gate is exercised honestly.
func (fakeGenerator) Answer(question, passage, answerLanguage string) (string, error) {
	return fakes.FakeLLM{}.Answer(question, passage), nil
}

// --- real OpenAI-compatible adapter ---

type openAIEmbedder struct {
	client *models.OpenAIEmbedding
}

func (e openAIEmbedder) Embed(text string) ([]float64, error) {
	return e.client.EmbedQuery(text)
}
