// The shipped clients' CONTRACT DECLARATIONS (ADR-0014 R4).
//
// Python declares a contract by inheriting the Protocol, so `mypy --strict`
// re-checks every client against the published shape on every run. Go has no
// inheritance, so the idiomatic equivalent is the compile-time assertion below:
// if a client ever drifts from the published seam, `go build` fails here rather
// than a caller failing at runtime.
//
// Note what does NOT appear in any contract: base URL, headers, transport. Those
// are constructor parameters of these clients — the seam is the operation only
// (ADR-0014 R3), which is exactly why an in-process provider that never opens a
// socket satisfies the same interface these HTTP clients do.
//
// Only the two seams the Go port consumes are declared, because only those two
// are published. See golang/contracts for why completion, vision and reranking
// are deliberately absent.

package models

import "github.com/muthuishere/citenexus/golang/contracts"

var (
	// Embed([]string) ([][]float64, error) — already the batch shape the
	// contract names, so no rename was needed to declare it.
	_ contracts.EmbeddingProvider = (*OpenAIEmbedding)(nil)

	// EmbedQuery is the single-text convenience; it satisfies the deprecated
	// shape through the standard function adapter rather than as a method, so
	// it is asserted the same way ingest wires it.
	_ contracts.SingleTextEmbedder = contracts.SingleFrom((*OpenAIEmbedding)(nil))

	// Answer(question, passage, answerLanguage) (string, error) — both
	// generators, one contract, spelled the same in both.
	_ contracts.GeneratorProvider = (*OpenAIChatGenerator)(nil)
	_ contracts.GeneratorProvider = (*AnthropicGenerator)(nil)
)
