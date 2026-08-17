// Probe A, run against the Go port's ASK FLOW.
//
// It used to call gate.IsSupported / gate.IsSupportedV2 directly and report
// "0/9 accepted". That was true of the FUNCTION and false of the library: the
// shipped flow (answer.AskWith) was still calling the frozen v1 predicate, so
// all nine lies came out of `Ask` as grounded answers while this probe printed
// a clean sheet. A probe that can pass while the shipped path is broken is worse
// than no probe — it is the "green suite as camouflage" failure ADR-0014
// documents.
//
// So the probe now drives the FLOW. Each case is a one-document corpus holding
// the true passage plus an injected generator that returns the falsified answer;
// the question shares content tokens with the passage, so retrieval and the
// relevance gate both pass and the ONLY thing between the lie and the caller is
// the faithfulness gate the flow actually calls.
//
// The predicates are still reported per case, as context for the verdict — but
// the verdict itself is now the flow's decision, not theirs.
package main

import (
	"fmt"
	"os"

	"github.com/muthuishere/citenexus/golang/answer"
	"github.com/muthuishere/citenexus/golang/gate"
	"github.com/muthuishere/citenexus/golang/result"
)

type kase struct{ domain, attack, question, passage, answer string }

var cases = []kase{
	{"legal", "role inversion", "Who shall indemnify whom for damage to the property?", "The tenant shall indemnify the landlord for damage to the property.", "The landlord shall indemnify the tenant for damage to the property."},
	{"finance", "role inversion", "Who pays the fee of 400 basis points?", "The borrower pays the lender a fee of 400 basis points.", "The lender pays the borrower a fee of 400 basis points."},
	{"medical", "role inversion", "Which drug increases the effect of the other in adult patients?", "Ibuprofen increases the effect of warfarin in adult patients.", "Warfarin increases the effect of ibuprofen in adult patients."},
	{"legal", "negation deletion", "May the employee disclose confidential information?", "The employee shall not disclose confidential information.", "The employee shall disclose confidential information."},
	{"operations", "negation deletion", "May the reactor be restarted without a signed safety review?", "The reactor must not be restarted without a signed safety review.", "The reactor must be restarted without a signed safety review."},
	{"medical", "negation deletion", "Is this medication approved for patients under twelve years?", "This medication is not approved for patients under twelve years.", "This medication is approved for patients under twelve years."},
	{"finance", "value swap", "What revenue did region A and region B report?", "Region A reported 40 million in revenue and region B reported 12 million.", "Region A reported 12 million in revenue and region B reported 40 million."},
	{"physics", "value swap", "At what temperature does the sample melt and boil?", "The sample melts at 240 kelvin and boils at 610 kelvin.", "The sample melts at 610 kelvin and boils at 240 kelvin."},
	{"physics", "comparator inversion", "Which chamber has the greater pressure?", "Pressure in chamber one is greater than pressure in chamber two.", "Pressure in chamber two is greater than pressure in chamber one."},
}

// sayer is a generator that says exactly what it is told to say — a stand-in for
// a model that hallucinates a plausible inversion of its own evidence.
type sayer struct{ reply string }

func (s sayer) Answer(question, passage, answerLanguage string) (string, error) {
	return s.reply, nil
}

func main() {
	holes := 0
	blindControls := 0
	for _, c := range cases {
		corpus := []answer.Doc{{DocumentID: "d1", Text: c.passage}}

		// The attack: the flow must refuse.
		res, err := answer.AskWith(corpus, c.question, answer.DefaultTopK,
			answer.Providers{Generator: sayer{c.answer}})
		if err != nil {
			fmt.Fprintf(os.Stderr, "askwith: %v\n", err)
			os.Exit(2)
		}
		answered := res.Evidence.Decision == result.DecisionAnswered

		// The control: quoting the passage back must still be answered, or the
		// "0 holes" reading is just a gate that refuses everything.
		ctl, err := answer.AskWith(corpus, c.question, answer.DefaultTopK,
			answer.Providers{Generator: sayer{c.passage}})
		if err != nil {
			fmt.Fprintf(os.Stderr, "askwith (control): %v\n", err)
			os.Exit(2)
		}
		controlOK := ctl.Evidence.Decision == result.DecisionAnswered

		if answered {
			holes++
		}
		if !controlOK {
			blindControls++
		}

		verdict := "REFUSED   (ok)"
		if answered {
			verdict = "ANSWERED (hole)"
		}
		control := "quote answered"
		if !controlOK {
			control = "QUOTE REFUSED (gate is blind)"
		}
		fmt.Printf("  [%-10s] %-19s predicate v1=%s v2=%s -> flow %s, %s\n",
			c.domain, c.attack,
			label(gate.IsSupported(c.answer, c.passage)),
			label(gate.IsSupportedV2(c.answer, c.passage)),
			verdict, control)
	}

	fmt.Printf("\n  go (FLOW, answer.AskWith): %d/%d false answers emitted to the caller.\n",
		holes, len(cases))
	fmt.Printf("  go (FLOW control): %d/%d verbatim quotes wrongly refused.\n",
		blindControls, len(cases))
	if holes > 0 || blindControls > 0 {
		os.Exit(1)
	}
}

func label(accept bool) string {
	if accept {
		return "accept"
	}
	return "reject"
}
