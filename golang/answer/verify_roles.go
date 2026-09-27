// The role guard: WHO pays, receives or must.
//
// Entailment models are weakest on role swaps. rag_go measured a fine-tuned
// checker admitting employees -> employers at P(E) 1.00, and a Dutch "De
// werkgever betaalt 4,5%" over a unit saying "je eigen bijdrage is 4,5% … de
// resterende premie betaalt <Org>". The qualifier guard compares werkgever /
// werknemer within ONE language by neighbouring words; the role guard binds
// each fact to its actor, across languages, and runs on the gate path too.
//
// Actors are language-independent ids ("employee", "employer", "intern")
// with terms in any language (ActorLexicon). A fact is a number (read by
// ADR-0015 key) or a slot word — a verb or noun that says what the actor does
// with it:
//
//   - source: pays, contributes, reimburses, provides (betaalt, bijdrage, vergoedt);
//   - recipient: receives, gets, is entitled (ontvangt, krijgt, recht);
//   - duty: must (moet, verplicht); permission: may (mag).
//
// Binding, per clause (the other guards' clause splitter, except that a colon
// does not end a clause: a label binds to its value):
//
//   - a number binds to the nearest slot word within 5 words; in a clause with
//     no slot word at all, to the nearest actor within 5 words (and is then
//     compared only with numbers bound the same way);
//   - a slot word binds to the nearest actor within 4 words, the earlier one on
//     a tie (the subject, in both languages' main clauses), skipping a named
//     actor right after a preposition ("… van Ploum", "Binnen Ploum krijgt
//     elke medewerker …"); "door"/"by" mark a passive's agent and are kept;
//   - a share compound ("werkgeversdeel", "werknemersbijdrage") is its own
//     actor and source.
//
// Explicit roles and the reader's own pronouns ("je", "you") are both actors;
// pronouns stand for ActorLexicon.SecondPerson. Beyond the windows a fact is
// unresolved: rag_go's answers bound modifiers ("the internal Ploum
// conditions") by nearest word alone.
//
// The claim's fact is looked for in the unit: the SAME number (any clause
// holding it), or — for a fact without a number — a clause with a slot word of
// the same slot holding at least half (and two) of the claim clause's content
// words. Each occurrence resolves to a (slot, actor) or to nothing. The guard
// REFUSES when no occurrence of the same slot has the claim's actor and at
// least one has a different one. It never refuses:
//
//   - when the unit's actor is unresolved (the checker decides);
//   - across slots: "je ontvangt € 25" over "de werkgever vergoedt € 25" is the
//     same fact from the other side;
//   - when any occurrence agrees ("De werkgever betaalt 4,5%; je betaalt ook 4,5%");
//   - on a fact without a number whose claim actor is the reader's pronoun:
//     who "you" is depends on who asked ("U mag niet informeren" answers a
//     manager).
//
// A registered subset role ("intern") is its own id, so "all employees" over
// a stagiairs passage is a mismatch like any other.
//
// Like every guard it can only refuse.

package answer

import (
	"fmt"
	"regexp"
	"strings"

	"github.com/muthuishere/citenexus/golang/gate"
	"github.com/muthuishere/citenexus/golang/tokenize"
)

// Role slots: what the actor of a fact does with it.
const (
	SlotSource     = "source"
	SlotRecipient  = "recipient"
	SlotDuty       = "duty"
	SlotPermission = "permission"
)

// ActorLexicon is what the role guard reads. All terms are lowercase single
// words.
type ActorLexicon struct {
	// Actors maps an actor id to its terms, in any language:
	// "employer" -> werkgever, employer, and the host's organisation names.
	Actors map[string][]string
	// SecondPerson is the actor the reader's own pronouns (SecondPersonTerms:
	// je, jij, u, you, your, …) stand for; "" means pronouns bind nothing.
	SecondPerson      string
	SecondPersonTerms []string
	// Slots maps a fact word (a verb, or a noun like "bijdrage") to its slot.
	Slots map[string]string
	// ShareTails make a Dutch compound an actor's share, and so a source fact
	// bound to that actor: actor term + optional linking "s" + tail
	// ("werkgeversbijdrage", "werknemersdeel"). Only exact tails count — a
	// word that merely starts with a term ("internal") is not an actor.
	ShareTails []string
}

// DefaultActorLexicon is a small generic nl/en table: employee, employer and
// intern, the reader addressed as the employee, and the common pay / receive /
// must / may words. It names no organisation: hosts add theirs.
var DefaultActorLexicon = ActorLexicon{
	Actors: map[string][]string{
		"employee":   {"werknemer", "werknemers", "medewerker", "medewerkers", "employee", "employees"},
		"employer":   {"werkgever", "werkgevers", "employer", "employers"},
		"intern":     {"stagiair", "stagiairs", "stagiaire", "stagiaires", "intern", "interns"},
		"agency":     {"uitzendkracht", "uitzendkrachten", "agency"},
		"contractor": {"inhuur", "freelancer", "freelancers", "zzp'er", "zzp'ers", "contractor", "contractors"},
		"manager":    {"leidinggevende", "leidinggevenden", "manager", "managers"},
	},
	SecondPerson:      "employee",
	SecondPersonTerms: []string{"je", "jij", "jou", "jouw", "u", "uw", "you", "your", "yours"},
	ShareTails:        []string{"bijdrage", "bijdragen", "deel", "aandeel", "premie"},
	Slots: map[string]string{
		"betaalt": SlotSource, "betaal": SlotSource, "betalen": SlotSource, "betaald": SlotSource,
		"draagt": SlotSource, "dragen": SlotSource, "vergoedt": SlotSource, "vergoed": SlotSource,
		"vergoeden": SlotSource, "bijdrage": SlotSource, "bijdragen": SlotSource, "stort": SlotSource,
		"verstrekt": SlotSource, "biedt": SlotSource, "geeft": SlotSource,
		"pays": SlotSource, "pay": SlotSource, "paid": SlotSource, "contributes": SlotSource,
		"contribute": SlotSource, "contribution": SlotSource, "reimburses": SlotSource,
		"reimburse": SlotSource, "provides": SlotSource, "share": SlotSource, "offers": SlotSource, "bears": SlotSource,
		"ontvangt": SlotRecipient, "ontvang": SlotRecipient, "ontvangen": SlotRecipient,
		"krijgt": SlotRecipient, "krijg": SlotRecipient, "krijgen": SlotRecipient, "recht": SlotRecipient,
		"receives": SlotRecipient, "receive": SlotRecipient, "gets": SlotRecipient, "get": SlotRecipient,
		"entitled": SlotRecipient, "earns": SlotRecipient,
		"moet": SlotDuty, "moeten": SlotDuty, "verplicht": SlotDuty, "must": SlotDuty,
		"mag": SlotPermission, "mogen": SlotPermission, "may": SlotPermission,
	},
}

// With returns a copy of the lexicon with extra terms for one actor id (a new
// id registers a new role). Hosts extend the default with it:
// DefaultActorLexicon.With("employer", "acme").
func (l ActorLexicon) With(id string, terms ...string) ActorLexicon {
	actors := make(map[string][]string, len(l.Actors)+1)
	for k, v := range l.Actors {
		actors[k] = append([]string{}, v...)
	}
	for _, t := range terms {
		actors[id] = append(actors[id], strings.ToLower(strings.TrimSpace(t)))
	}
	l.Actors = actors
	return l
}

// roleWord is one word of a clause, classified.
type roleWord struct {
	norm     string
	actor    string // actor id, or ""
	pronoun  bool   // the actor is the reader's pronoun, not a named role
	slot     string // slot, or ""
	numbers  []string
	content  bool // a content word for fact matching
	position int
}

var roleTrim = "\"'“”‘’()[]{}.,;:!?*_|€$£"

func (l ActorLexicon) classify(clause, language string, vb ...verbatimNumbers) []roleWord {
	terms := map[string]string{}
	for id, ts := range l.Actors {
		for _, t := range ts {
			terms[t] = id
		}
	}
	second := map[string]bool{}
	for _, t := range l.SecondPersonTerms {
		second[t] = true
	}
	words := listLeadToken.FindAllString(clause, -1)
	out := make([]roleWord, 0, len(words))
	for i, w := range words {
		norm := strings.ToLower(strings.Trim(w, roleTrim))
		norm = strings.TrimSuffix(strings.TrimSuffix(norm, "'s"), "’s") // "employer's"
		rw := roleWord{norm: norm, position: i}
		for _, m := range numbersIn(w, language, vb...) {
			rw.numbers = append(rw.numbers, m.reading.Key)
		}
		if id, ok := terms[rw.norm]; ok {
			rw.actor = id
		} else if second[rw.norm] && l.SecondPerson != "" {
			rw.actor, rw.pronoun = l.SecondPerson, true
		} else if id, ok := l.share(rw.norm, terms); ok {
			rw.actor, rw.slot = id, SlotSource
		}
		if s, ok := l.Slots[rw.norm]; ok && rw.slot == "" {
			rw.slot = s
		}
		if rw.actor == "" && rw.slot == "" && len(rw.numbers) == 0 && len([]rune(rw.norm)) >= 4 &&
			!gate.IsStopword(rw.norm) {
			if _, stop := contextStop[rw.norm]; !stop {
				rw.content = true
			}
		}
		out = append(out, rw)
	}
	return out
}

// share reads "werkgeversdeel" as the employer's share: term + optional
// linking "s" + an exact ShareTail.
func (l ActorLexicon) share(word string, terms map[string]string) (string, bool) {
	for _, tail := range l.ShareTails {
		head, ok := strings.CutSuffix(word, tail)
		if !ok || head == "" {
			continue
		}
		if id, ok := terms[head]; ok {
			return id, true
		}
		if id, ok := terms[strings.TrimSuffix(head, "s")]; ok && strings.HasSuffix(head, "s") {
			return id, true
		}
	}
	return "", false
}

// Binding distances, in words. Beyond them a fact is unresolved: nearest-word
// binding over a long clause picks modifiers ("… from the internal Ploum
// conditions"), and an unresolved fact decides nothing.
const (
	roleNumberWindow = 5 // a number to its slot word, or to its actor without one
	roleActorWindow  = 4 // a slot word to its actor
)

// nonSubject precede a named actor that is not the one doing the slot:
// "krijgt … van Ploum", "aan de werknemer", "Binnen Ploum krijgt elke
// medewerker …". "door"/"by" are absent:
// they mark the agent of a passive.
var nonSubject = map[string]struct{}{
	"van": {}, "voor": {}, "aan": {}, "bij": {}, "met": {}, "namens": {}, "binnen": {}, "in": {},
	"onder": {}, "from": {}, "for": {}, "to": {}, "with": {}, "of": {}, "on": {}, "within": {},
	"at": {}, "among": {},
}

// nearest is the index of the nearest word in ws within max words of i
// satisfying ok; the earlier on a tie; -1 when none.
func nearest(ws []roleWord, i, max int, ok func(int) bool) int {
	for d := 0; d <= max && d < len(ws); d++ {
		if j := i - d; j >= 0 && ok(j) {
			return j
		}
		if j := i + d; j < len(ws) && ok(j) {
			return j
		}
	}
	return -1
}

// binding: the (slot, actor) the fact at index i binds to; ok=false when
// either is unresolved.
func binding(ws []roleWord, i int) (slot, actor string, pronoun, ok bool) {
	s := i
	if ws[i].slot == "" {
		s = nearest(ws, i, roleNumberWindow, func(j int) bool { return ws[j].slot != "" })
	}
	if s < 0 {
		// No slot word in the whole clause: a number binds to its nearest
		// actor ("contracten met werknemers die jonger dan 18 jaar zijn"), and
		// is compared only with numbers that bind without a slot too. A slot
		// word out of reach leaves the number unresolved.
		if len(ws[i].numbers) == 0 || nearest(ws, i, len(ws), func(j int) bool { return ws[j].slot != "" }) >= 0 {
			return "", "", false, false
		}
		a := nearest(ws, i, roleNumberWindow, func(j int) bool { return ws[j].actor != "" })
		if a < 0 {
			return "", "", false, false
		}
		return "", ws[a].actor, ws[a].pronoun, true
	}
	if ws[s].actor != "" { // a share compound: "werkgeversdeel"
		return ws[s].slot, ws[s].actor, ws[s].pronoun, true
	}
	a := nearest(ws, s, roleActorWindow, func(j int) bool {
		if ws[j].actor == "" {
			return false
		}
		// A pronoun after a preposition is usually a possessive ("van jouw
		// bijdrage"): it still names whose the slot is.
		if j > 0 && !ws[j].pronoun {
			if _, ok := nonSubject[ws[j-1].norm]; ok {
				return false
			}
			if j > 1 && isArticle(ws[j-1].norm) {
				if _, ok := nonSubject[ws[j-2].norm]; ok {
					return false
				}
			}
		}
		return true
	})
	if a < 0 {
		return "", "", false, false
	}
	return ws[s].slot, ws[a].actor, ws[a].pronoun, true
}

func isArticle(w string) bool {
	switch w {
	case "de", "het", "een", "the", "a", "an", "je", "jouw", "your", "uw":
		return true
	}
	return false
}

// roleBreak is clauseBreak without the colon: a label binds to its value
// ("Eigen bijdrage werkgever: 2,5%", "Werkgever: 2/3 van de premie").
var roleBreak = regexp.MustCompile(`[.!?;]+(\s|$)|,\s|\s*[\x{2014}\x{2013}]\s*|\s-\s|\n`)

func roleClauses(text string) []string {
	return roleBreak.Split(softJoin(text), -1)
}

// roleGuard refuses a claim whose fact the unit states for a different actor.
func roleGuard(claim, claimLanguage string, eu EvidenceUnit, lexicon ActorLexicon) string {
	if len(lexicon.Actors) == 0 && lexicon.SecondPerson == "" {
		return ""
	}
	type clause struct{ words []roleWord }
	var unit []clause
	for _, c := range roleClauses(eu.Text) {
		unit = append(unit, clause{lexicon.classify(c, eu.Language)})
	}
	for _, c := range roleClauses(claim) {
		ws := lexicon.classify(c, claimLanguage, verbatimIn(eu.Text, eu.Language))
		content := map[string]bool{}
		for _, w := range ws {
			if w.content {
				for _, tok := range tokenize.TokenizeV2(w.norm) {
					content[tok] = true
				}
			}
		}
		for i, w := range ws {
			var match func(roleWord) bool
			switch {
			case len(w.numbers) > 0:
				keys := w.numbers
				match = func(u roleWord) bool {
					for _, k := range keys {
						for _, n := range u.numbers {
							if n == k {
								return true
							}
						}
					}
					return false
				}
			case w.slot != "" && !hasNumber(ws):
				slot := w.slot
				match = func(u roleWord) bool { return u.slot == slot }
			default:
				continue
			}
			slot, actor, pronoun, ok := binding(ws, i)
			if !ok {
				continue
			}
			// Without a number, the fact is found only by its words, and who
			// "you" is depends on who asked: the reader's pronoun decides
			// nothing there ("U mag niet informeren" answers a manager).
			if len(w.numbers) == 0 && pronoun {
				continue
			}
			agrees, other := false, ""
			for _, uc := range unit {
				if len(w.numbers) == 0 && !sharesContent(uc.words, content) {
					continue
				}
				for j, u := range uc.words {
					if !match(u) {
						continue
					}
					us, ua, _, ok := binding(uc.words, j)
					if !ok || us != slot {
						continue
					}
					if ua == actor {
						agrees = true
					} else if other == "" {
						other = ua
					}
				}
			}
			if !agrees && other != "" {
				return fmt.Sprintf("role guard: %s where the passage says %s", actor, other)
			}
		}
	}
	return ""
}

func hasNumber(ws []roleWord) bool {
	for _, w := range ws {
		if len(w.numbers) > 0 {
			return true
		}
	}
	return false
}

// sharesContent: the unit clause holds at least half of the claim clause's
// content words, and at least two — the "same fact" for a fact without a
// number is a clause saying nearly the same thing.
func sharesContent(ws []roleWord, content map[string]bool) bool {
	have := map[string]bool{}
	for _, w := range ws {
		if w.content {
			for _, tok := range tokenize.TokenizeV2(w.norm) {
				have[tok] = true
			}
		}
	}
	shared := 0
	for tok := range content {
		if have[tok] {
			shared++
		}
	}
	return shared >= 2 && 2*shared >= len(content)
}
