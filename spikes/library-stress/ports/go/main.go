// Probe A, run against the Go port's faithfulness gates.
// Same nine adversarial fixtures as the Python harness — if the ports are truly
// conformance-identical, both the hole and its fix must appear identically here.
//
// v1 = gate.IsSupported, the frozen SPEC-PORTS-v1 §4 predicate (kept for the
//
//	conformance vectors; known unsound — it accepts all nine).
//
// v2 = gate.IsSupportedV2, the ADR-0009 ordered-containment + polarity gate.
package main

import (
	"fmt"

	"github.com/muthuishere/citenexus/golang/gate"
)

type kase struct{ domain, attack, passage, answer string }

var cases = []kase{
	{"legal", "role inversion", "The tenant shall indemnify the landlord for damage to the property.", "The landlord shall indemnify the tenant for damage to the property."},
	{"finance", "role inversion", "The borrower pays the lender a fee of 400 basis points.", "The lender pays the borrower a fee of 400 basis points."},
	{"medical", "role inversion", "Ibuprofen increases the effect of warfarin in adult patients.", "Warfarin increases the effect of ibuprofen in adult patients."},
	{"legal", "negation deletion", "The employee shall not disclose confidential information.", "The employee shall disclose confidential information."},
	{"operations", "negation deletion", "The reactor must not be restarted without a signed safety review.", "The reactor must be restarted without a signed safety review."},
	{"medical", "negation deletion", "This medication is not approved for patients under twelve years.", "This medication is approved for patients under twelve years."},
	{"finance", "value swap", "Region A reported 40 million in revenue and region B reported 12 million.", "Region A reported 12 million in revenue and region B reported 40 million."},
	{"physics", "value swap", "The sample melts at 240 kelvin and boils at 610 kelvin.", "The sample melts at 610 kelvin and boils at 240 kelvin."},
	{"physics", "comparator inversion", "Pressure in chamber one is greater than pressure in chamber two.", "Pressure in chamber two is greater than pressure in chamber one."},
}

func main() {
	holes := 0
	v1Holes := 0
	for _, c := range cases {
		v1 := gate.IsSupported(c.answer, c.passage)
		v2 := gate.IsSupportedV2(c.answer, c.passage)
		if v1 {
			v1Holes++
		}
		verdict := "rejected  (ok)"
		if v2 {
			holes++
			verdict = "ACCEPTED (hole)"
		}
		v1Label := "reject"
		if v1 {
			v1Label = "accept"
		}
		fmt.Printf("  [%-10s] %-19s v1=%s -> v2 %s\n", c.domain, c.attack, v1Label, verdict)
	}
	fmt.Printf("\n  go (v1, frozen): %d/%d false answers accepted as grounded.\n", v1Holes, len(cases))
	fmt.Printf("  go: %d/%d false answers accepted as grounded.\n", holes, len(cases))
}
