package models

import (
	"reflect"
	"testing"
)

// ${ENV} in a header resolves only at the request boundary (ResolveHeaders),
// never in the pure merge (BuildHeaders) — mirrors the Python HttpClient.
func TestHTTPClientExpandsEnvAtCallBoundary(t *testing.T) {
	t.Setenv("CN_TEST_KEY", "sk-secret-123")
	c := NewHTTPClient(nil, 0)
	call := map[string]string{"Authorization": "Bearer ${CN_TEST_KEY}"}

	if got := c.BuildHeaders(call)["Authorization"]; got != "Bearer ${CN_TEST_KEY}" {
		t.Errorf("BuildHeaders should keep the template, got %q", got)
	}
	if got := c.ResolveHeaders(call)["Authorization"]; got != "Bearer sk-secret-123" {
		t.Errorf("ResolveHeaders should expand at call time, got %q", got)
	}
	// The caller's dict is never mutated (no value leaks back).
	if call["Authorization"] != "Bearer ${CN_TEST_KEY}" {
		t.Errorf("caller header was mutated: %q", call["Authorization"])
	}
}

func TestExpandEnvMissingVarIsEmpty(t *testing.T) {
	if got := ExpandEnv("Bearer ${CN_ABSENT_VAR}"); got != "Bearer " {
		t.Errorf("missing var should expand to empty, got %q", got)
	}
}

// A model client with WithHeaders forwards the TEMPLATE (not a value) to its
// transport, alongside Content-Type; with no headers the wire set is unchanged.
func TestModelClientForwardsHeaderTemplates(t *testing.T) {
	var seen map[string]string
	recorder := func(_ string, _ []byte, headers map[string]string) ([]byte, error) {
		seen = headers
		return []byte(`{"data":[{"embedding":[0.1,0.2]}]}`), nil
	}

	e := NewOpenAIEmbedding("http://x/v1", "m", recorder,
		WithHeaders(map[string]string{"Authorization": "Bearer ${CN_MODEL_KEY}"}))
	if _, err := e.Embed([]string{"hi"}); err != nil {
		t.Fatalf("Embed: %v", err)
	}
	want := map[string]string{
		"Content-Type":  "application/json",
		"Authorization": "Bearer ${CN_MODEL_KEY}", // template, expansion is the transport's job
	}
	if !reflect.DeepEqual(seen, want) {
		t.Errorf("headers = %v, want %v", seen, want)
	}

	// No options → exactly the pinned wire header set (model_wire conformance).
	var bare map[string]string
	rec2 := func(_ string, _ []byte, h map[string]string) ([]byte, error) {
		bare = h
		return []byte(`{"data":[]}`), nil
	}
	_, _ = NewOpenAIEmbedding("http://x/v1", "m", rec2).Embed([]string{"hi"})
	if !reflect.DeepEqual(bare, map[string]string{"Content-Type": "application/json"}) {
		t.Errorf("bare headers = %v", bare)
	}
}
