package answer

import (
	"context"
	"testing"
)

// TestNumberFormsInRunningText: every way a policy writes 4000 in its own
// language matches every other, on the claim side and on the unit side, in
// running text ("€ 4 000" = "€ 4.000" since 38259a5).
//
// rag_go Lex5 L-R20 ("4 is not in the passage") is NOT a split separator: it
// is an English-declared claim writing the Dutch "€ 4.000". Until the ADR-0015
// amendment of 2026-09-27 each side was read only in its own declared
// language, so that claim read 4.0 and was refused. The owner-approved
// amendment: a number the claim copies VERBATIM from its cited unit keeps the
// UNIT's locale (4000); a number the writer formats itself follows the claim's
// language. The cases below pin both halves and the whole-number bound.
func TestNumberFormsInRunningText(t *testing.T) {
	nlUnit := func(f string) string {
		return "Huur. De maandhuur van de bedrijfsruimte bedraagt " + f + " per maand. De huur wordt jaarlijks geïndexeerd."
	}
	nlClaim := func(f string) string { return "De maandhuur van de bedrijfsruimte bedraagt " + f + " per maand." }
	enUnit := func(f string) string {
		return "Rent. The monthly rent of the business premises is " + f + " per month. The rent is indexed yearly."
	}
	enClaim := func(f string) string { return "The monthly rent of the business premises is " + f + " per month." }
	type tc struct {
		name, unitLang, claimLang, unit, claim string
		refuse                                 bool
	}
	var cases []tc
	for _, f := range []string{"4.000", "4.000,00", "€ 4.000", "€ 4 000", "€4.000,-"} {
		cases = append(cases,
			tc{"nl claim " + f, "nl", "nl", nlUnit("€ 4.000"), nlClaim(f), false},
			tc{"nl unit " + f, "nl", "nl", nlUnit(f), nlClaim("€ 4.000"), false})
	}
	for _, f := range []string{"4,000", "4,000.00", "€ 4,000"} {
		cases = append(cases,
			tc{"en claim " + f, "en", "en", enUnit("€ 4,000"), enClaim(f), false},
			tc{"en unit " + f, "en", "en", enUnit(f), enClaim("€ 4,000"), false})
	}
	// Narrow no-break (U+202F) and no-break (U+00A0) space grouping, as
	// French-style and typeset Dutch documents write it: "€ 1 012".
	for _, sp := range []string{"\u202f", "\u00a0", " "} {
		cases = append(cases,
			tc{"nl claim € 1" + sp + "012", "nl", "nl", nlUnit("€ 1.012"), nlClaim("€" + sp + "1" + sp + "012"), false},
			tc{"nl unit € 1" + sp + "012", "nl", "nl", nlUnit("€" + sp + "1" + sp + "012"), nlClaim("€ 1.012"), false},
			tc{"nl € 1" + sp + "012 is not 1.021", "nl", "nl", nlUnit("€ 1.021"), nlClaim("€ 1" + sp + "012"), true})
	}
	// The decimal comma: "€ 0,23" = "0,23 euro" = "23 cent"; never 23 or 0,32.
	cases = append(cases,
		tc{"nl € 0,23 = 0,23 euro", "nl", "nl", nlUnit("€ 0,23"), nlClaim("0,23 euro"), false},
		tc{"nl € 0,23 = 23 cent", "nl", "nl", nlUnit("€ 0,23"), nlClaim("23 cent"), false},
		tc{"en € 0.23 = nl € 0,23", "nl", "en", nlUnit("€ 0,23"), enClaim("€ 0.23"), false},
		tc{"nl € 0,23 is not € 23", "nl", "nl", nlUnit("€ 0,23"), nlClaim("€ 23"), true},
		tc{"nl € 0,23 is not € 0,32", "nl", "nl", nlUnit("€ 0,23"), nlClaim("€ 0,32"), true},
	)
	cases = append(cases,
		// L-R20, ADR-0015 amendment 2026-09-27: a number copied verbatim from
		// the unit keeps the unit's locale — admitted (these were refusals).
		tc{"en claim copies the dutch amount verbatim", "nl", "en", nlUnit("€ 4.000"), enClaim("€ 4.000"), false},
		tc{"en claim copies the dutch amount before euro", "nl", "en", nlUnit("€ 4.000"), enClaim("4.000 euro"), false},
		tc{"en claim copies 4.000,00 verbatim", "nl", "en", nlUnit("€ 4.000,00"), enClaim("€ 4.000,00"), false},
		tc{"en claim copies €4.000,- verbatim", "nl", "en", nlUnit("€4.000,-"), enClaim("€4.000,-"), false},
		tc{"nl claim copies the english amount verbatim", "en", "nl", enUnit("€ 4,000"), nlClaim("€ 4,000"), false},
		// A number the writer formats itself follows the claim's language.
		tc{"en claim in english format over the dutch unit", "nl", "en", nlUnit("€ 4.000"), enClaim("€ 4,000"), false},
		tc{"nl claim in dutch format over the english unit", "en", "nl", enUnit("€ 4,000"), nlClaim("€ 4.000"), false},
		tc{"en 4.000 not in the unit is 4", "nl", "en", nlUnit("€ 4000"), enClaim("€ 4.000"), true},
		tc{"en 4.000 over a unit spelling 4.000,50", "nl", "en", nlUnit("€ 4.000,50"), enClaim("€ 4.000"), true},
		tc{"en 4.000 over a unit spelling 14.000", "nl", "en", nlUnit("€ 14.000"), enClaim("€ 4.000"), true},
		// The whole-number bound: a claim number never takes a reading from
		// inside a longer unit number.
		tc{"en € 23 over nl € 0,23", "nl", "en", nlUnit("€ 0,23"), enClaim("€ 23"), true},
		tc{"en 12 over en 12.75", "en", "en", enUnit("€ 12.75"), enClaim("€ 12"), true},
		tc{"en 12 over nl 0,12", "nl", "en", nlUnit("€ 0,12"), enClaim("€ 12"), true},
		// Must refuse.
		tc{"4.000 is not 40.000", "nl", "nl", nlUnit("€ 40.000"), nlClaim("€ 4.000"), true},
		tc{"4.000 is not 4,5", "nl", "nl", nlUnit("€ 4,5"), nlClaim("€ 4.000"), true},
		tc{"en 4,000 is not 40,000", "en", "en", enUnit("€ 40,000"), enClaim("€ 4,000"), true},
		tc{"4.000 is not the count 4", "nl", "nl",
			"Parkeren. De huurder krijgt 4 parkeerplaatsen bij de bedrijfsruimte. De huur wordt jaarlijks geïndexeerd.",
			"De huurder krijgt 4.000 parkeerplaatsen bij de bedrijfsruimte.", true},
		// ADR-0015 amendment: outside a money amount too, "4.000" copied
		// verbatim from a Dutch unit keeps the unit's reading (4000) —
		// admitted; this was a refusal. Not copied, it is English 4.0.
		tc{"en-declared 4.000 copied from a dutch unit outside money", "nl", "en",
			"Personeel. Het bedrijf heeft 4.000 medewerkers in dienst. Zij werken in drie vestigingen.",
			"The company employs 4.000 staff.", false},
		tc{"en-declared 4.000 outside money not in the unit", "nl", "en",
			"Personeel. Het bedrijf heeft 4000 medewerkers in dienst. Zij werken in drie vestigingen.",
			"The company employs 4.000 staff.", true},
	)
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			res, err := VerifyAnswer(context.Background(), c.claim+" [eu:a]",
				[]EvidenceUnit{{ID: "a", DocumentID: "d", Language: c.unitLang, Text: c.unit}},
				VerifyOptions{AnswerLanguage: c.claimLang, AdmitParaphrase: true, Checker: admitAll{}, CheckerName: "admit"})
			if err != nil {
				t.Fatal(err)
			}
			got := res.Claims[0]
			if c.refuse && got.Supported {
				t.Fatalf("admitted %q over %q", c.claim, c.unit)
			}
			if !c.refuse && !got.Supported {
				t.Fatalf("refused (%s)", got.Reason)
			}
		})
	}
}
