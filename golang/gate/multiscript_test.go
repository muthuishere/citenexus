package gate

import (
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// The gate half of the ADR-0011 per-script golden matrix
// (conformance/cases/tokenize_v2.json). A script is only CLAIMED as supported
// when both halves hold: the gate accepts a verbatim quote of its own source in
// that script, AND it still rejects unrelated text. One without the other is
// either an over-determined abstention (the v1 defect) or a rubber stamp.
type scriptFixture struct {
	UnrelatedPassage string `json:"unrelated_passage"`
	Supported        []struct {
		Script             string `json:"script"`
		Text               string `json:"text"`
		SelfSupported      bool   `json:"self_supported"`
		UnrelatedSupported bool   `json:"unrelated_supported"`
	} `json:"supported"`
}

func loadScriptFixture(t *testing.T) scriptFixture {
	t.Helper()
	var f scriptFixture
	conform.Case(t, "tokenize_v2.json", &f)
	if len(f.Supported) == 0 {
		t.Fatal("no claimed-script cases loaded")
	}
	return f
}

func TestEveryClaimedScriptSupportsAVerbatimQuoteOfItsOwnSource(t *testing.T) {
	for _, c := range loadScriptFixture(t).Supported {
		if !c.SelfSupported {
			t.Fatalf("%s: fixture disagrees with itself", c.Script)
		}
		if !IsSupportedV2(c.Text, c.Text) {
			t.Fatalf("%s: IsSupportedV2 rejected a verbatim quote of its own source", c.Script)
		}
	}
}

func TestNoClaimedScriptTurnsTheGateIntoARubberStamp(t *testing.T) {
	f := loadScriptFixture(t)
	for _, c := range f.Supported {
		if c.UnrelatedSupported {
			t.Fatalf("%s: fixture disagrees with itself", c.Script)
		}
		if IsSupportedV2(c.Text, f.UnrelatedPassage) {
			t.Fatalf("%s: IsSupportedV2 accepted an unrelated passage", c.Script)
		}
	}
}
