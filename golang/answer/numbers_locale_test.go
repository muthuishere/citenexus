package answer

import "testing"

// TestNumbersInLocaleGrouping pins the ADR-0015 amendment's grouping forms
// (2026-09-27): space grouping in a decimal-comma language, Swiss apostrophe
// grouping in any language, Indian lakh grouping in a language that writes it.
// Anything ambiguous stays unread or stays several numbers.
func TestNumbersInLocaleGrouping(t *testing.T) {
	cases := []struct {
		text, language string
		want           []string
	}{
		{"Le montant est de 1 234,56.", "fr", []string{"1234.56"}},
		{"Le montant est de 1 234,56.", "fr", []string{"1234.56"}},
		{"Der Betrag ist 1 234 567,89.", "de", []string{"1234567.89"}},
		{"De prijs is 1.234,56.", "de", []string{"1234.56"}},
		{"The total is 1 234.", "en", []string{"1", "234"}},          // point language: two numbers
		{"Le total est 1 234 56.", "fr", []string{"1", "234", "56"}}, // not exact groups
		{"Der Preis ist 1'234.50.", "de-CH", []string{"1234.5"}},
		{"Der Preis ist 1’234.50.", "de", []string{"1234.5"}},
		{"The price is 1'234.50.", "en", []string{"1234.5"}},
		{"The price is 1'23.", "en", []string{"1", "23"}},
		{"The fee is 1,00,000.", "en-IN", []string{"100000"}},
		{"शुल्क 12,34,567.89 है", "hi", []string{"1234567.89"}},
		{"The fee is 1,00,000.", "", []string{"?1,00,000"}},
		{"De prijs is 1.500.", "sv", []string{"1500"}},
		{"The price is 1.500.", "xx", []string{"?1.500"}},
	}
	for _, c := range cases {
		var got []string
		for _, m := range numbersIn(c.text, c.language) {
			got = append(got, m.reading.Key)
		}
		if len(got) != len(c.want) {
			t.Errorf("%q (%s): got %v want %v", c.text, c.language, got, c.want)
			continue
		}
		for i := range got {
			if got[i] != c.want[i] {
				t.Errorf("%q (%s): got %v want %v", c.text, c.language, got, c.want)
				break
			}
		}
	}
}

// TestVerbatimNumbersAreWholeNumbers: a claim number takes the unit's reading
// only when it IS one of the unit's numbers, spelled the same.
func TestVerbatimNumbersAreWholeNumbers(t *testing.T) {
	vb := verbatimIn("Het budget is € 4.000, de toeslag € 0,12 en de fee € 12.750.", "nl")
	cases := []struct{ claim, want string }{
		{"4.000", "4000"},  // copied: the unit's reading
		{"12", "12"},       // not inside 0,12 or 12.750
		{"0,12", "0.12"},   // copied
		{"12.75", "12.75"}, // not a prefix of 12.750: English reading
		{"4.00", "4"},
	}
	for _, c := range cases {
		got := numbersIn("The amount is "+c.claim+" here.", "en", vb)
		if len(got) != 1 || got[0].reading.Key != c.want {
			t.Errorf("%q: got %+v want %s", c.claim, got, c.want)
		}
	}
}
