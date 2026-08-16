package models

import (
	"testing"

	"github.com/muthuishere/citenexus/golang/contracts"
)

// The compile-time assertions in contracts.go are the real check — this test
// exists so the declaration is visible in the test output too, and so a reader
// scanning `go test -v` can see WHICH client claims WHICH seam.
func TestShippedClientsSatisfyThePublishedContracts(t *testing.T) {
	var (
		embedding = NewOpenAIEmbedding("http://x/v1", "bge-m3", nil)
		openai    = NewOpenAIChatGenerator("http://x/v1", "qwen", 0, nil, nil)
		anthropic = NewAnthropicGenerator("", "claude", 0, DefaultAnthropicMaxTokens, nil)
	)

	if _, ok := any(embedding).(contracts.EmbeddingProvider); !ok {
		t.Error("OpenAIEmbedding does not satisfy contracts.EmbeddingProvider")
	}
	for name, client := range map[string]any{
		"OpenAIChatGenerator": openai,
		"AnthropicGenerator":  anthropic,
	} {
		if _, ok := client.(contracts.GeneratorProvider); !ok {
			t.Errorf("%s does not satisfy contracts.GeneratorProvider", name)
		}
	}

	// The batch client also plugs into the deprecated single-text ingest seam
	// through the published adapter, with no glue written by the caller.
	if _, ok := any(contracts.SingleFrom(embedding)).(contracts.SingleTextEmbedder); !ok {
		t.Error("contracts.SingleFrom(OpenAIEmbedding) is not a SingleTextEmbedder")
	}
}

// R3, checked on a real client: the transport lives in the CONSTRUCTOR, so the
// contract a provider implements says nothing about HTTP. A provider that never
// opens a socket satisfies exactly the same interface these clients do.
func TestTheContractSaysNothingAboutTheTransport(t *testing.T) {
	var provider contracts.GeneratorProvider = NewOpenAIChatGenerator(
		"http://example.invalid/v1", "qwen", 0, nil,
		func(string, []byte, map[string]string) ([]byte, error) {
			return []byte(`{"choices":[{"message":{"content":"the passage"}}]}`), nil
		},
	)
	got, err := provider.Answer("q", "the passage", "en")
	if err != nil || got != "the passage" {
		t.Fatalf("Answer through the contract: %q %v", got, err)
	}
}
