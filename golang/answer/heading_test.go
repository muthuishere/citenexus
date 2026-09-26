package answer

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"testing"
)

// TestHeadingCheckVectors drives the two heading questions and simulates the
// host that asks them (rag_go's post-pass): VerifyAnswer first, then exempt a
// refused heading only when neither question says it must stay a claim.
func TestHeadingCheckVectors(t *testing.T) {
	var file struct {
		Cases []struct {
			Name       string `json:"name"`
			MustRefuse bool   `json:"must_refuse"`
			Heading    string `json:"heading"`
			Language   string `json:"language"`
			Cite       string `json:"cite"`
			Evidence   []struct {
				ID         string `json:"id"`
				DocumentID string `json:"document_id"`
				Language   string `json:"language"`
				Text       string `json:"text"`
			} `json:"evidence"`
			Expect struct {
				NeedsCheck bool   `json:"needs_check"`
				Reason     string `json:"reason"`
				NameReason string `json:"name_reason"`
				Outcome    string `json:"outcome"`
			} `json:"expect"`
		} `json:"cases"`
	}
	raw, err := os.ReadFile("../../conformance/cases/heading_check.json")
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(raw, &file); err != nil {
		t.Fatal(err)
	}
	if len(file.Cases) != 14 {
		t.Fatalf("heading_check.json: got %d cases, want 14", len(file.Cases))
	}
	refuse := 0
	for _, c := range file.Cases {
		if c.MustRefuse {
			refuse++
		}
		t.Run(c.Name, func(t *testing.T) {
			evidence := make([]EvidenceUnit, len(c.Evidence))
			for i, e := range c.Evidence {
				evidence[i] = EvidenceUnit{ID: e.ID, DocumentID: e.DocumentID, Language: e.Language, Text: e.Text}
			}
			claim, reason := HeadingNeedsCheck(c.Heading, c.Language)
			if claim != c.Expect.NeedsCheck || !strings.HasPrefix(reason, c.Expect.Reason) || (c.Expect.Reason == "" && reason != "") {
				t.Fatalf("HeadingNeedsCheck = %v %q, want %v %q", claim, reason, c.Expect.NeedsCheck, c.Expect.Reason)
			}
			nameReason := HeadingNameUnsupported(c.Heading, evidence, nil)
			if !strings.HasPrefix(nameReason, c.Expect.NameReason) || (c.Expect.NameReason == "" && nameReason != "") {
				t.Fatalf("HeadingNameUnsupported = %q, want %q", nameReason, c.Expect.NameReason)
			}
			answer := c.Heading
			if c.Cite != "" {
				answer += " [eu:" + c.Cite + "]"
			}
			res, err := VerifyAnswer(context.Background(), answer, evidence, VerifyOptions{AnswerLanguage: c.Language, RequireCitations: true})
			if err != nil {
				t.Fatal(err)
			}
			if len(res.Claims) != 1 {
				t.Fatalf("%d claims, want the heading as 1: %+v", len(res.Claims), res.Claims)
			}
			outcome := "exempt"
			switch {
			case res.Claims[0].Supported:
				outcome = "admitted"
			case claim || nameReason != "":
				outcome = "refused"
			}
			if outcome != c.Expect.Outcome {
				t.Fatalf("outcome %q, want %q (claim %+v)", outcome, c.Expect.Outcome, res.Claims[0])
			}
			if c.MustRefuse && outcome != "refused" {
				t.Fatalf("must-refuse heading was %s", outcome)
			}
		})
	}
	if refuse < 3 {
		t.Fatalf("only %d must-refuse heading controls", refuse)
	}
}

func TestHeadingRulesAreInjectable(t *testing.T) {
	rules := HeadingRules{Modals: map[string][]string{"nl": {"dient"}}}
	if claim, _ := HeadingNeedsCheckWith("Wat de werknemer dient te doen", "nl", rules); !claim {
		t.Fatal("a host-supplied modal must make the heading a claim")
	}
	if claim, _ := HeadingNeedsCheckWith("De werknemer moet betalen", "nl", rules); claim {
		t.Fatal("host rules replace the defaults: 'moet' is not in them")
	}
}
