// The nine adversarial false answers, driven through the FLOW — not through the
// predicate.
//
// spikes/library-stress/ports/go/main.go already ran these nine against
// gate.IsSupportedV2 and reported 0/9 accepted. That proved the FUNCTION was
// sound and nothing at all about `AskWith`, which was still calling the frozen
// v1 predicate. A probe that can pass while the shipped path is broken is the
// "green suite as camouflage" failure ADR-0014 documents, so the assertion that
// matters lives here, on the path a caller actually reaches.
//
// Each case is one corpus document (the true passage) plus a generator that
// returns the falsified answer. The question shares content tokens with the
// passage, so retrieval and the relevance gate both pass and the ONLY thing
// standing between the lie and the caller is the faithfulness gate.

package answer

import (
	"testing"

	"github.com/muthuishere/citenexus/golang/result"
)

type adversarialCase struct {
	name     string
	question string
	passage  string
	answer   string
}

// The nine attacks, byte-identical to conformance/cases/faithful_v2.json.
var adversarialCases = []adversarialCase{
	{
		"legal/role-inversion",
		"Who shall indemnify whom for damage to the property?",
		"The tenant shall indemnify the landlord for damage to the property.",
		"The landlord shall indemnify the tenant for damage to the property.",
	},
	{
		"finance/role-inversion",
		"Who pays the fee of 400 basis points?",
		"The borrower pays the lender a fee of 400 basis points.",
		"The lender pays the borrower a fee of 400 basis points.",
	},
	{
		"medical/role-inversion",
		"Which drug increases the effect of the other in adult patients?",
		"Ibuprofen increases the effect of warfarin in adult patients.",
		"Warfarin increases the effect of ibuprofen in adult patients.",
	},
	{
		"legal/negation-deletion",
		"May the employee disclose confidential information?",
		"The employee shall not disclose confidential information.",
		"The employee shall disclose confidential information.",
	},
	{
		"operations/negation-deletion",
		"May the reactor be restarted without a signed safety review?",
		"The reactor must not be restarted without a signed safety review.",
		"The reactor must be restarted without a signed safety review.",
	},
	{
		"medical/negation-deletion",
		"Is this medication approved for patients under twelve years?",
		"This medication is not approved for patients under twelve years.",
		"This medication is approved for patients under twelve years.",
	},
	{
		"finance/value-swap",
		"What revenue did region A and region B report?",
		"Region A reported 40 million in revenue and region B reported 12 million.",
		"Region A reported 12 million in revenue and region B reported 40 million.",
	},
	{
		"physics/value-swap",
		"At what temperature does the sample melt and boil?",
		"The sample melts at 240 kelvin and boils at 610 kelvin.",
		"The sample melts at 610 kelvin and boils at 240 kelvin.",
	},
	{
		"physics/comparator-inversion",
		"Which chamber has the greater pressure?",
		"Pressure in chamber one is greater than pressure in chamber two.",
		"Pressure in chamber two is greater than pressure in chamber one.",
	},
}

// TestAskWithRefusesEveryAdversarialAnswer is the flow-level guarantee: none of
// the nine falsified answers may reach a caller through AskWith.
func TestAskWithRefusesEveryAdversarialAnswer(t *testing.T) {
	for _, tc := range adversarialCases {
		t.Run(tc.name, func(t *testing.T) {
			corpus := []Doc{{DocumentID: "d1", Text: tc.passage}}
			gen := &stubGenerator{reply: tc.answer}

			res, err := AskWith(corpus, tc.question, DefaultTopK,
				Providers{Generator: gen})
			if err != nil {
				t.Fatalf("AskWith: %v", err)
			}
			if len(gen.calls) == 0 {
				t.Fatalf("the generator was never reached: the case does not "+
					"exercise the faithfulness gate at all (question %q)", tc.question)
			}
			if res.Evidence.Decision != result.DecisionRefused {
				t.Fatalf("the flow ANSWERED a falsified claim.\n  passage: %s\n  answer:  %s",
					tc.passage, res.Answer)
			}
		})
	}
}

// TestAskWithStillAnswersAVerbatimQuote is the control. A gate that refuses
// everything is not a gate, so the same flow must still answer when the
// generator quotes the passage back.
func TestAskWithStillAnswersAVerbatimQuote(t *testing.T) {
	for _, tc := range adversarialCases {
		t.Run(tc.name, func(t *testing.T) {
			corpus := []Doc{{DocumentID: "d1", Text: tc.passage}}
			gen := &stubGenerator{reply: tc.passage}

			res, err := AskWith(corpus, tc.question, DefaultTopK,
				Providers{Generator: gen})
			if err != nil {
				t.Fatalf("AskWith: %v", err)
			}
			if res.Evidence.Decision != result.DecisionAnswered {
				t.Fatalf("the flow refused a VERBATIM quote of its own passage: %s", tc.passage)
			}
		})
	}
}

// TestAskAnswersAVerbatimNonLatinQuote pins the OTHER half of the gate move.
//
// The v1 gates run on the v1 ASCII tokenizer, under which a Japanese (or Greek,
// or Devanagari) question and its own passage BOTH tokenize to the empty set: the
// relevance gate found no shared token and the flow abstained before the
// faithfulness gate ever ran, so this port refused every non-Latin question no
// matter how perfectly the evidence answered it. V2 tokenizes 14 scripts
// (ADR-0011), so a verbatim quote of the passage is now accepted here exactly as
// it already is in Latin script. Behaviour change, not just a bug fix — the ports
// are no longer ASCII-only on the ask path.
func TestAskAnswersAVerbatimNonLatinQuote(t *testing.T) {
	cases := []struct{ name, question, passage string }{
		{"japanese", "保証期間は何年ですか", "保証期間は二年です"},
		{"greek", "Ποια είναι η εγγύηση", "Η εγγύηση διαρκεί δύο χρόνια"},
		{"hindi", "वारंटी कितने साल की है", "वारंटी दो साल की है"},
		{"russian", "Какая гарантия", "Гарантия составляет два года"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			res := Ask([]Doc{{DocumentID: "d1", Text: tc.passage}}, tc.question, DefaultTopK)
			if res.Evidence.Decision != result.DecisionAnswered {
				t.Fatalf("refused a verbatim non-Latin quote: passage %q", tc.passage)
			}
			if res.Answer != tc.passage {
				t.Fatalf("answer = %q, want the verbatim passage %q", res.Answer, tc.passage)
			}
		})
	}
}
