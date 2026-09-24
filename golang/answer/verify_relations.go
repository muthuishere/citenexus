// Direction of a transfer: WHO informs, pays or gives WHOM.
//
// A swap of sender and recipient keeps every word and every number: "the
// employee must inform the employer in writing …" over "… dan deelt de
// werkgever dit … schriftelijk mee aan de werknemer" (rag_go adv rx-v2-20).
// The role guard binds a fact to ONE actor and needs a slot on both sides; it
// gave no verdict here (a duty in the claim, none in the unit). relationGuard
// binds a communication/transfer verb to BOTH its parties, whatever the
// modality, and compares the direction across languages through the actor
// lexicon's language-independent ids.
//
// Per clause with a verb of one class (inform: mededelen, informeren,
// melden, inform, notify, tell; pay: betalen, uitkeren, pay; give:
// verstrekken, overhandigen, provide, give), and exactly two named actors
// (pronouns are not used: who "you" is depends on who asked):
//
//   - the recipient is the actor after "aan"/"bij"/"to"; otherwise, in
//     English, the first actor after the verb ("inform the employer"), in
//     Dutch the actor that is not the sender;
//   - the sender is the other actor — in Dutch the one before the verb, or,
//     with the verb first ("dan deelt de werkgever … mee aan …"), the first
//     one after it.
//
// Refused when a unit clause of the same class has the two parties the other
// way round and none has them the claim's way. Unresolved means no verdict.
// Can only refuse.

package answer

import "fmt"

var relationVerbs = map[string]string{
	"deelt": "inform", "delen": "inform", "meedelen": "inform", "mededelen": "inform", "informeert": "inform",
	"informeren": "inform", "informeer": "inform", "meldt": "inform", "melden": "inform",
	"inform": "inform", "informs": "inform", "informed": "inform", "notify": "inform", "notifies": "inform",
	"notified": "inform", "tell": "inform", "tells": "inform", "told": "inform",
	"betaalt": "pay", "betalen": "pay", "uitkeren": "pay", "keert": "pay", "pay": "pay", "pays": "pay", "paid": "pay",
	"verstrekt": "give", "verstrekken": "give", "overhandigt": "give", "overhandigen": "give",
	"provide": "give", "provides": "give", "provided": "give", "give": "give", "gives": "give", "gave": "give",
}

var recipientMarkers = map[string]struct{}{"aan": {}, "bij": {}, "to": {}}

type direction struct{ class, sender, recipient string }

// directionsIn: the resolved transfers of a text, one per clause at most.
func directionsIn(text, language string, lexicon ActorLexicon) []direction {
	english := primaryLanguage(language) == "en"
	var out []direction
	for _, clause := range roleClauses(text) {
		ws := lexicon.classify(clause, language)
		verb, class := -1, ""
		for i, w := range ws {
			if c, ok := relationVerbs[w.norm]; ok {
				if verb >= 0 && c != class {
					verb = -2 // two different transfers: unresolved
					break
				}
				verb, class = i, c
			}
		}
		if verb < 0 {
			continue
		}
		type mention struct {
			at          int
			id          string
			markedRecip bool
		}
		var ms []mention
		ids := map[string]bool{}
		for i, w := range ws {
			if w.actor == "" || w.pronoun {
				continue
			}
			marked := false
			for k := i - 1; k >= 0 && k >= i-2; k-- {
				if _, ok := recipientMarkers[ws[k].norm]; ok {
					marked = true
					break
				}
				if !isArticle(ws[k].norm) {
					break
				}
			}
			ms = append(ms, mention{i, w.actor, marked})
			ids[w.actor] = true
		}
		if len(ids) != 2 {
			continue
		}
		recipient, sender := "", ""
		for _, m := range ms {
			if m.markedRecip {
				recipient = m.id
			}
		}
		if recipient == "" && english {
			for _, m := range ms {
				if m.at > verb {
					recipient = m.id
					break
				}
			}
		}
		if recipient == "" {
			// Dutch without "aan": the sender is the actor before the verb, or the
			// first after a verb-first clause; the recipient is the other one.
			for _, m := range ms {
				if m.at < verb {
					sender = m.id
				}
			}
			if sender == "" {
				sender = ms[0].id
			}
			for id := range ids {
				if id != sender {
					recipient = id
				}
			}
		} else {
			for id := range ids {
				if id != recipient {
					sender = id
				}
			}
		}
		if sender == "" || recipient == "" || sender == recipient {
			continue
		}
		out = append(out, direction{class, sender, recipient})
	}
	return out
}

// relationGuard: see the file comment.
func relationGuard(claim, claimLanguage string, eu EvidenceUnit, lexicon ActorLexicon) string {
	unit := directionsIn(eu.Text, eu.Language, lexicon)
	if len(unit) == 0 {
		return ""
	}
	for _, c := range directionsIn(claim, claimLanguage, lexicon) {
		agrees, swapped := false, false
		for _, u := range unit {
			if u.class != c.class {
				continue
			}
			if u.sender == c.sender && u.recipient == c.recipient {
				agrees = true
			}
			if u.sender == c.recipient && u.recipient == c.sender {
				swapped = true
			}
		}
		if swapped && !agrees {
			return fmt.Sprintf("role guard: %s %ss %s where the passage says %s %ss %s",
				c.sender, c.class, c.recipient, c.recipient, c.class, c.sender)
		}
	}
	return ""
}
