package contracts

import (
	"encoding/json"
	"fmt"
	"math"
	"strings"
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// conformance/cases/vector_validation.json, asserted as a BINDING contract.
//
// This is the cross-port definition of A VALID EMBEDDING BATCH (ADR-0010 tier 1:
// structural/arithmetic, so implemented NATIVELY in each port — no Rust, no
// native library, plain `go build` unaffected). It exists because the three
// ports did not agree: Python validated NOTHING (a provider returning fewer
// vectors than texts shifted every text→vector pairing and silently corrupted
// the index), Go rejected empty/dimension/all-zero, and JS rejected those PLUS
// non-finite. Go's missing non-finite rejection is closed by the same change
// that added this file.
//
// python/tests/conformance/test_vector_validation_vectors.py holds the reference
// to exactly this file; js/src/contracts.vector.test.ts holds the JS port. This
// holds Go, reading the committed JSON as OPAQUE DATA. Nothing here re-derives
// an expectation by calling the code under test — a test that asks the
// implementation what it does can only ever agree with it, which is how this
// class of bug survived.

type vectorCase struct {
	Name string `json:"name"`
	// Components are numbers, or one of the pinned tokens "NaN"/"Infinity"/
	// "-Infinity" — JSON has no non-finite literal.
	Vector []any  `json:"vector"`
	Dim    int    `json:"dim"`
	Valid  bool   `json:"valid"`
	Reason string `json:"reason"`
}

type nonVectorCase struct {
	Name   string `json:"name"`
	Vector any    `json:"vector"`
	Dim    int    `json:"dim"`
	Valid  bool   `json:"valid"`
	Reason string `json:"reason"`
}

type arityCase struct {
	Name    string `json:"name"`
	Texts   int    `json:"texts"`
	Vectors int    `json:"vectors"`
	Valid   bool   `json:"valid"`
	Reason  string `json:"reason"`
}

type vectorValidationVectors struct {
	ReasonOrder     []string        `json:"reason_order"`
	NonFiniteTokens []string        `json:"non_finite_tokens"`
	CheckVector     []vectorCase    `json:"check_vector"`
	NonVector       []nonVectorCase `json:"non_vector"`
	BatchArity      []arityCase     `json:"batch_arity"`
}

// expectedVectorCounts pins the bucket sizes EXACTLY. A floor (len > 0) lets a
// shrunken file pass silently — every bucket is a distinct failure mode, and one
// silently dropped is a weakened contract no per-case assertion can see.
var expectedVectorCounts = map[string]int{
	"check_vector": 29,
	"non_vector":   10,
	"batch_arity":  9,
}

func loadVectorValidation(t *testing.T) vectorValidationVectors {
	t.Helper()
	var vectors vectorValidationVectors
	conform.Case(t, "vector_validation.json", &vectors)
	return vectors
}

// decodeComponent turns one fixture component into a float64, expanding the
// three pinned non-finite tokens.
func decodeComponent(t *testing.T, raw any) float64 {
	t.Helper()
	switch v := raw.(type) {
	case float64:
		return v
	case string:
		switch v {
		case "NaN":
			return math.NaN()
		case "Infinity":
			return math.Inf(1)
		case "-Infinity":
			return math.Inf(-1)
		}
		t.Fatalf("unknown non-finite token %q", v)
	}
	t.Fatalf("unexpected component %v (%T)", raw, raw)
	return 0
}

// classify maps an error back to the contract's rejection vocabulary by reading
// the MESSAGE THE PORT PRODUCES. A port whose message does not name the rule it
// applied cannot be held to the rejection ORDER, which is half of this contract.
func classifyVectorErr(err error) (string, error) {
	message := err.Error()
	switch {
	case strings.Contains(message, "empty vector"):
		return "empty", nil
	case strings.Contains(message, "-dim vector"):
		return "dimension", nil
	case strings.Contains(message, "non-finite"):
		return "non_finite", nil
	case strings.Contains(message, "zero vector"):
		return "zero", nil
	case strings.Contains(message, "vectors for"):
		return "cardinality", nil
	}
	return "", fmt.Errorf("error message names no rejection rule: %q", message)
}

func TestVectorValidationBucketNamesAndSizes(t *testing.T) {
	vectors := loadVectorValidation(t)
	got := map[string]int{
		"check_vector": len(vectors.CheckVector),
		"non_vector":   len(vectors.NonVector),
		"batch_arity":  len(vectors.BatchArity),
	}
	total := 0
	for name, want := range expectedVectorCounts {
		if got[name] != want {
			t.Errorf("bucket %q: got %d vectors, want %d", name, got[name], want)
		}
		total += want
	}
	if total != 48 {
		t.Fatalf("pinned bucket sizes sum to %d, want 48", total)
	}

	// Guard against a bucket the Go loader silently ignores: unmarshalling into a
	// struct drops unknown keys, so a new bucket would be invisible here.
	var raw map[string]json.RawMessage
	conform.Case(t, "vector_validation.json", &raw)
	if len(raw) != len(expectedVectorCounts)+2 {
		t.Fatalf("fixture has %d top-level keys, want %d (3 buckets + reason_order + non_finite_tokens)",
			len(raw), len(expectedVectorCounts)+2)
	}
}

func TestVectorValidationReasonOrderIsPinned(t *testing.T) {
	vectors := loadVectorValidation(t)
	wantOrder := []string{"non_vector", "empty", "dimension", "non_finite", "zero"}
	if len(vectors.ReasonOrder) != len(wantOrder) {
		t.Fatalf("reason_order = %v, want %v", vectors.ReasonOrder, wantOrder)
	}
	for i, want := range wantOrder {
		if vectors.ReasonOrder[i] != want {
			t.Errorf("reason_order[%d] = %q, want %q", i, vectors.ReasonOrder[i], want)
		}
	}
	wantTokens := []string{"NaN", "Infinity", "-Infinity"}
	if len(vectors.NonFiniteTokens) != len(wantTokens) {
		t.Fatalf("non_finite_tokens = %v, want %v", vectors.NonFiniteTokens, wantTokens)
	}
	for i, want := range wantTokens {
		if vectors.NonFiniteTokens[i] != want {
			t.Errorf("non_finite_tokens[%d] = %q, want %q", i, vectors.NonFiniteTokens[i], want)
		}
	}
}

// TestVectorValidationEveryRuleIsExercised makes coverage an assertion rather
// than a hope: a bucket can shrink to only its happy cases and every per-case
// assertion still passes.
func TestVectorValidationEveryRuleIsExercised(t *testing.T) {
	vectors := loadVectorValidation(t)
	seen := map[string]bool{}
	valid, invalid := 0, 0
	for _, c := range vectors.CheckVector {
		if c.Valid {
			valid++
			continue
		}
		invalid++
		seen[c.Reason] = true
	}
	for _, want := range []string{"empty", "dimension", "non_finite", "zero"} {
		if !seen[want] {
			t.Errorf("no check_vector case exercises rejection %q", want)
		}
	}
	if len(seen) != 4 {
		t.Errorf("check_vector rejections = %v, want exactly the four Go can represent", seen)
	}
	if valid == 0 || invalid == 0 {
		t.Fatalf("check_vector needs both accepted and rejected cases; got %d/%d", valid, invalid)
	}
}

// TestCheckVectorVectors asserts the verdict AND the rejection reason for every
// numeric vector in the file.
func TestCheckVectorVectors(t *testing.T) {
	vectors := loadVectorValidation(t)
	for _, c := range vectors.CheckVector {
		t.Run(c.Name, func(t *testing.T) {
			vec := make([]float64, len(c.Vector))
			for i, raw := range c.Vector {
				vec[i] = decodeComponent(t, raw)
			}
			err := CheckVector(c.Name, vec, c.Dim)
			if c.Valid {
				if c.Reason != "" {
					t.Fatalf("fixture marks %q valid but names reason %q", c.Name, c.Reason)
				}
				if err != nil {
					t.Fatalf("CheckVector rejected a valid vector: %v", err)
				}
				return
			}
			if err == nil {
				t.Fatalf("CheckVector accepted %q, which the contract rejects as %q", c.Name, c.Reason)
			}
			got, cerr := classifyVectorErr(err)
			if cerr != nil {
				t.Fatal(cerr)
			}
			if got != c.Reason {
				t.Errorf("rejected as %q, contract says %q (message: %v)", got, c.Reason, err)
			}
			// The rejection must name the offending unit, never just the run: a
			// corpus-wide "bad vector" tells an operator nothing about which EU
			// to fix.
			if !strings.Contains(err.Error(), c.Name) {
				t.Errorf("error does not name the offending unit %q: %v", c.Name, err)
			}
		})
	}
}

// TestNonVectorBucketIsUnrepresentableInGo documents, rather than skips, the one
// bucket Go cannot execute.
//
// CheckVector takes []float64, so "a payload that is not an array of numbers"
// cannot be constructed — the compiler rejects it at the call site, which is a
// STRONGER guarantee than the runtime TypeError Python and JS must raise. The
// bucket is still asserted for shape so that a port-parity reader can see the
// cases exist and why Go does not run them, and so a fixture that quietly
// stopped carrying them is caught here too.
func TestNonVectorBucketIsUnrepresentableInGo(t *testing.T) {
	vectors := loadVectorValidation(t)
	if len(vectors.NonVector) != expectedVectorCounts["non_vector"] {
		t.Fatalf("non_vector has %d cases, want %d",
			len(vectors.NonVector), expectedVectorCounts["non_vector"])
	}
	for _, c := range vectors.NonVector {
		if c.Valid {
			t.Errorf("case %q: non_vector payloads are never valid", c.Name)
		}
		if c.Reason != "non_vector" {
			t.Errorf("case %q: reason = %q, want %q", c.Name, c.Reason, "non_vector")
		}
	}
}

// arityEmbedder returns a fixed number of vectors regardless of how many texts
// it was given — a provider that reports success while breaking the contract.
type arityEmbedder struct{ vectors int }

func (a arityEmbedder) Embed(texts []string) ([][]float64, error) {
	out := make([][]float64, a.vectors)
	for i := range out {
		out[i] = []float64{1.0, 2.0}
	}
	return out, nil
}

// TestBatchArityVectors exercises the rule through the real EmbedTexts dispatch,
// not through a predicate. This is the rule Python missed entirely, and the most
// damaging of the five: it is the only one whose failure leaves the index
// PLAUSIBLY wrong, with every downstream signal still looking healthy.
func TestBatchArityVectors(t *testing.T) {
	vectors := loadVectorValidation(t)
	for _, c := range vectors.BatchArity {
		t.Run(c.Name, func(t *testing.T) {
			texts := make([]string, c.Texts)
			for i := range texts {
				texts[i] = fmt.Sprintf("text-%d", i)
			}
			got, err := EmbedTexts(arityEmbedder{c.Vectors}, texts)
			if c.Valid {
				if err != nil {
					t.Fatalf("EmbedTexts rejected a valid batch: %v", err)
				}
				if len(got) != c.Texts {
					t.Fatalf("got %d vectors for %d texts", len(got), c.Texts)
				}
				return
			}
			if err == nil {
				t.Fatalf("EmbedTexts accepted %d vectors for %d texts", c.Vectors, c.Texts)
			}
			reason, cerr := classifyVectorErr(err)
			if cerr != nil {
				t.Fatal(cerr)
			}
			if reason != c.Reason {
				t.Errorf("rejected as %q, contract says %q (message: %v)", reason, c.Reason, err)
			}
			// Both counts must appear, so the operator can see the shape of the
			// mismatch rather than only that there was one.
			for _, want := range []string{fmt.Sprint(c.Texts), fmt.Sprint(c.Vectors)} {
				if !strings.Contains(err.Error(), want) {
					t.Errorf("error omits count %s: %v", want, err)
				}
			}
		})
	}
}
