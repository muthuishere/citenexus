// Package conform loads the shared cross-language conformance fixtures that live
// at <repo>/conformance/ (SPEC-PORTS-v1 §10). The fixtures are the real port
// contract: every deterministic algorithm (§4) is proven identical to the
// Python reference by making these cases pass, byte-for-byte.
package conform

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

// dir returns the absolute path of the repo's conformance/ directory, resolved
// relative to THIS source file so tests work from any working directory.
func dir() string {
	_, self, _, _ := runtime.Caller(0)
	// self = <repo>/ports/go/internal/conform/conform.go → up 4 to <repo>.
	repo := filepath.Join(filepath.Dir(self), "..", "..", "..", "..")
	return filepath.Join(repo, "conformance")
}

// Case unmarshals conformance/cases/<name> into v (e.g. "tokenize.json").
func Case(t *testing.T, name string, v any) {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(dir(), "cases", name))
	if err != nil {
		t.Fatalf("read fixture %s: %v", name, err)
	}
	if err := json.Unmarshal(raw, v); err != nil {
		t.Fatalf("unmarshal fixture %s: %v", name, err)
	}
}

// Data unmarshals a top-level conformance file (e.g. "stopwords.json").
func Data(t *testing.T, name string, v any) {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(dir(), name))
	if err != nil {
		t.Fatalf("read %s: %v", name, err)
	}
	if err := json.Unmarshal(raw, v); err != nil {
		t.Fatalf("unmarshal %s: %v", name, err)
	}
}
