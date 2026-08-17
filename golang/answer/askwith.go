// The injectable twin of Ask (ADR-0014 R4).
//
// golang/contracts publishes the model seam; this file is what makes that
// publication mean something. Before it, `Ask` constructed fakes.FakeEmbedding
// and fakes.FakeLLM INSIDE itself, so the port's only end-to-end path could not
// be reached by any provider a third party wrote — and a contract with no call
// site is decoration.
//
// `Ask` keeps its exact signature and behaviour: it is pinned byte-for-byte by
// conformance/cases/e2e_hermetic.json, which this change must not regenerate. It
// is now defined as AskWith with an empty provider set.

package answer

import (
	"fmt"
	"sort"
	"strings"

	"github.com/muthuishere/citenexus/golang/contracts"
	"github.com/muthuishere/citenexus/golang/fakes"
	"github.com/muthuishere/citenexus/golang/gate"
	"github.com/muthuishere/citenexus/golang/lang"
	"github.com/muthuishere/citenexus/golang/result"
	"github.com/muthuishere/citenexus/golang/tokenize"
)

// Providers are the models the flow runs on. A nil field falls back to this
// port's deterministic fake, so a PARTIAL set is valid — a caller with a real
// generator and no embedding model, or the reverse, is a supported shape (the
// Python reference proves the same case in
// test_a_third_party_provider_answers_without_an_embedding_model).
//
// Only the two seams the Go port consumes appear here. There is no Vision,
// Completion or Reranker field because there is nothing in this port that would
// call one; see golang/contracts.
type Providers struct {
	// Embedding ranks the corpus against the question. Batch is the primitive.
	Embedding contracts.EmbeddingProvider
	// Generator turns the selected passage into an answer. It is NOT trusted:
	// its output goes through the faithfulness gate below before it can be
	// emitted, which is why an extractive generator is the best kind.
	Generator contracts.GeneratorProvider
	// AnswerLanguage is the CALLER's answer-language request — rung 1 of the
	// §11a chain (lang.ResolveAnswerLanguage), the same slot Python's
	// `ask(answer_language=...)` fills. Empty means "unspecified", which falls
	// through to the pinned default below, and the "auto" sentinel is not a
	// request (this port has no detector to resolve it with, so it also falls
	// through). It rides on Providers to keep AskWith's arity — and therefore
	// conformance/cases/e2e_hermetic.json — untouched.
	AnswerLanguage string
}

// defaultAnswerLanguage is rung 4 of the §11a chain: the dumb configured
// default. It is NOT the answer language — the answer language is whatever
// lang.ResolveAnswerLanguage returns, and this is only what it returns when
// nothing above it fired.
//
// Until 2026-08-17 this port had a `const answerLanguage = "en"` used for the
// answer language AND every passage_language AND languages_in_evidence. The
// chain shipped in golang/lang with zero callers on the answer path, so all
// three fields were a constant wearing a signal's name.
const defaultAnswerLanguage = "en"

// undeclaredLanguage is what a SourceRef reports when the cited document
// declared no language — the pinned Python value for `candidate.language or
// "und"`. Note it is deliberately NOT the answer language: "I do not know what
// language this passage is in" and "I answered in English" are different facts,
// and the old code collapsed them.
const undeclaredLanguage = "und"

// AskWith answers question grounded in corpus using the injected providers, or
// refuses. Same flow as Ask — embed, rank by cosine, keep topK, require a shared
// content token, then require the generated answer to pass the faithfulness
// gate — with the models supplied by the caller.
//
// FAILURE IS AN ERROR, NOT A REFUSAL. A refusal is a finding: "we searched the
// evidence and it does not support an answer." A timed-out embedding model is
// not a finding about the evidence, and reporting it as one would be the same
// class of lie as the zero vector ADR-0014 R2 removed — a failure wearing the
// costume of a successful negative result. On error the returned Result is the
// zero value, deliberately NOT a refusal.
func AskWith(corpus []Doc, question string, topK int, providers Providers) (result.Result, error) {
	embedding, injectedEmbedding := providers.Embedding, providers.Embedding != nil
	if !injectedEmbedding {
		embedding = hermeticEmbedding{}
	}
	generator := providers.Generator
	if generator == nil {
		generator = hermeticGenerator{}
	}

	texts := make([]string, len(corpus))
	for i, doc := range corpus {
		texts[i] = doc.Text
	}

	// ONE batch call for the whole corpus — the contract's primitive.
	docVectors, err := contracts.EmbedTexts(embedding, texts)
	if err != nil {
		return result.Result{}, fmt.Errorf("answer: embed corpus: %w", err)
	}

	dim := 0
	rows := make([]row, len(corpus))
	for i, doc := range corpus {
		vec := docVectors[i]
		// The write-path guard, applied to the ask path. It runs only for an
		// INJECTED provider: the hermetic fake is this port's own reference
		// implementation, pinned by the conformance fixture, and validating our
		// own pinned output would only be able to disagree with the fixture.
		// (A token-less document legitimately embeds to zeros there, and must
		// still lead to a refusal rather than an error.)
		if injectedEmbedding {
			if err := contracts.CheckVector(doc.DocumentID, vec, dim); err != nil {
				return result.Result{}, fmt.Errorf("answer: %w", err)
			}
			dim = len(vec)
		}
		rows[i] = row{
			euID:       doc.DocumentID + "::0",
			documentID: doc.DocumentID,
			text:       doc.Text,
			language:   doc.Language,
			vector:     vec,
			order:      i,
		}
	}

	// A single text is a batch of one — the contract has no second method.
	qvec, err := contracts.EmbedOne(embedding, question)
	if err != nil {
		return result.Result{}, fmt.Errorf("answer: embed question: %w", err)
	}
	if injectedEmbedding {
		if err := contracts.CheckVector("question", qvec, dim); err != nil {
			return result.Result{}, fmt.Errorf("answer: %w", err)
		}
	}

	scores := make([]float64, len(rows))
	for i := range rows {
		scores[i] = dot(qvec, rows[i].vector)
	}

	ranked := make([]row, len(rows))
	copy(ranked, rows)
	sort.SliceStable(ranked, func(i, j int) bool {
		return scores[ranked[i].order] > scores[ranked[j].order]
	})
	if topK < len(ranked) {
		ranked = ranked[:topK]
	}

	// `ranked` is this port's analogue of the Python reference's `candidates`:
	// the post-retrieval, post-topK pool the flow is handed. Everything below
	// mirrors answer/flow.py over that pool, in flow.py's order.

	// The evidence languages are OBSERVED and REPORTED, never an input to the
	// chain below (flow.py:167 and the lang/fallback.py docstring: the fourth
	// rung used to read them, which stamped 15 of 22 English questions Telugu
	// or Tamil). Distinct, in pool order, undeclared entries skipped.
	languages := make([]string, 0, len(ranked))
	seenLanguage := make(map[string]struct{}, len(ranked))
	for _, r := range ranked {
		if r.language == "" {
			continue
		}
		if _, ok := seenLanguage[r.language]; ok {
			continue
		}
		seenLanguage[r.language] = struct{}{}
		languages = append(languages, r.language)
	}
	// The answer language follows the CALLER, then the question — never the
	// evidence. This port has no detector, so rung 2 is nil; `languages` is
	// passed for signature parity and is ignored by construction.
	answerLanguage := lang.ResolveAnswerLanguage(
		nil, providers.AnswerLanguage, "", languages, defaultAnswerLanguage,
	)

	// Which scripts in play the tokenizer does not CLAIM (ADR-0011). Note
	// "claim", not "process": the bigram path will mechanically produce tokens
	// for Khmer, Lao or Myanmar, and the gate will then accept a verbatim quote
	// in them. That is worse than refusing, because it looks exactly like a
	// verified answer while resting on a segmentation no fixture has ever
	// checked. An unclaimed script therefore ABSTAINS, and says why.
	//
	// The pool is PARTITIONED rather than unioned, because the two halves answer
	// different questions: `readable` decides what may be cited, and `blocked`
	// is the only thing a script-attributed refusal may be blamed on. Unioning
	// them is the measured mis-attribution defect (flow.py:186-189).
	questionGap := tokenize.UnsupportedScripts(question)
	readable := make([]row, 0, len(ranked))
	blocked := make([]blockedRow, 0, len(ranked))
	for _, r := range ranked {
		if gap := tokenize.UnsupportedScripts(r.text); len(gap) > 0 {
			blocked = append(blocked, blockedRow{row: r, scripts: gap})
		} else {
			readable = append(readable, r)
		}
	}
	blockedLists := make([][]string, 0, len(blocked))
	for _, b := range blocked {
		blockedLists = append(blockedLists, b.scripts)
	}
	blockedScripts := sortedUnique(blockedLists...)
	// The SIGNAL still reports everything observed — narrowing it would lose the
	// very fact the unreachable-authority signal needs. Only the reason string
	// is attributed.
	unsupported := sortedUnique(questionGap, blockedScripts)

	// A question we cannot read is not answerable from anything.
	if len(questionGap) > 0 {
		return refusal(
			answerLanguage, capabilityReason(sortedUnique(questionGap)), unsupported, nil,
		), nil
	}

	// Relevance gate: keep only rows sharing a content token with the question.
	// V2 (ADR-0011) tokenizes 14 scripts, not ASCII alone; under v1 a CJK or
	// Devanagari question and its own passage both tokenized to the empty set,
	// so this gate abstained before the faithfulness gate ever ran. Matches the
	// Python reference, which calls has_relevance_overlap_v2 here.
	grounded := make([]row, 0, len(readable))
	for _, r := range readable {
		if gate.HasRelevanceOverlapV2(question, r.text) {
			grounded = append(grounded, r)
		}
	}
	if len(grounded) == 0 {
		// Blame the script gap as the PRIMARY reason only when it is the only
		// thing between us and the pool — i.e. every candidate we got back was
		// unreadable. If we could read some of the pool and none of it was
		// relevant, the corpus is silent on this question, and saying otherwise
		// sends the caller after a phantom. The gap is still reported,
		// additively, by the unreachable note.
		onlyBlocked := len(blocked) > 0 && len(readable) == 0
		if onlyBlocked {
			return refusal(answerLanguage, unreadableReason(blockedScripts), unsupported, nil), nil
		}
		return refusal(
			answerLanguage,
			"no sufficiently relevant evidence found",
			unsupported,
			unreachableNote(blocked),
		), nil
	}

	// Conflict detection runs over the grounded candidates, BEFORE anything is
	// generated (ADR-0007), exactly as the Python reference does in
	// answer/flow.py. It reports and never resolves: picking a winner by rank,
	// recency or score is a policy decision belonging to the caller and to
	// authority (ADR-0004), and rank order deciding which of two contradictory
	// truths the caller sees is the defect this closes.
	window := grounded
	if k := ConflictTopK(); k < len(window) {
		window = window[:k]
	}
	conflictPairs := FindConflicts(textsOf(window))

	// Near-duplicate collapse feeds the corroboration signals only. The same
	// pairwise comparison that finds "same subject, opposite polarity" finds
	// "same subject, same text" — clones ingested under different document ids —
	// and those are one piece of evidence, not N.
	independent := make([]row, 0, len(grounded))
	for _, i := range CollapseNearDuplicates(textsOf(grounded)) {
		independent = append(independent, grounded[i])
	}

	top := grounded[0]
	const topIndex = 0 // this port generates from the first grounded candidate only
	passage := top.text
	ans, err := generator.Answer(question, passage, answerLanguage)
	if err != nil {
		return result.Result{}, fmt.Errorf("answer: generate: %w", err)
	}

	// Faithfulness gate: never emit an ungrounded claim. It runs on injected
	// output exactly as it runs on the fake's — this gate is the product, and it
	// does not soften because the caller supplied the model.
	//
	// V2 (ADR-0009), the predicate the Python reference uses at
	// answer/flow.py. The frozen v1 gate.IsSupported is SET CONTAINMENT, and a
	// set is closed under reordering and deletion: it accepted all nine
	// adversarial false answers (role inversion, negation deletion, value swap,
	// comparator inversion) because a lie built by permuting the passage's own
	// words has no token the passage lacks. V2 requires the claim's tokens to
	// appear IN ORDER within a bounded window and forbids a dropped polarity
	// marker. gate.IsSupported stays exported and frozen for the conformance
	// vectors; it is no longer what stands between a caller and a lie.
	// Verification is PER ATOMIC CLAIM (ADR-0009). The answer is segmented and
	// each claim is checked independently against the cited passage; unsupported
	// claims are DROPPED rather than failing the answer whole, so a half-true
	// generation returns its true half instead of nothing. The candidate is
	// accepted as soon as at least one of its claims survives — flow.py:307-315.
	//
	// SplitClaims shipped in this port, pinned by conformance/cases/
	// segmentation.json, with zero non-test callers: the port gated the entire
	// answer string as ONE claim, so a two-sentence answer with one fabricated
	// sentence refused BOTH sentences while Python kept the true one.
	claimTexts := SplitClaims(ans)
	verdicts := make([]claimVerdict, 0, len(claimTexts))
	anySupported := false
	for _, c := range claimTexts {
		supported := gate.IsSupportedV2(c, passage)
		anySupported = anySupported || supported
		verdicts = append(verdicts, claimVerdict{text: c, supported: supported})
	}
	if !anySupported {
		// The gate owns this refusal. What was elsewhere in the pool did not
		// cause it, so it does not get blamed for it — an unreadable sibling is
		// reported AFTER the real reason, never instead of it (flow.py:327-333).
		gateRefusal := refusal(
			answerLanguage,
			"generated answer failed the faithfulness gate",
			unsupported,
			unreachableNote(blocked),
		)
		// The conflict count is a signal about the evidence pool and it was
		// already computed. Python carries it onto the same refusal.
		gateRefusal.Evidence.ConflictsDetected = len(conflictPairs)
		return gateRefusal, nil
	}

	// TrustMode coupling. An unresolved conflict touching the answer's own claim
	// — one whose two sides include the passage we are about to cite — is not
	// answerable in strict mode: the honest output is "these sources disagree,
	// here are both", not a coin flip on rank order. This can only ever produce
	// MORE abstention, so it cannot admit an ungrounded claim. Go is strict-only,
	// so unlike Python there is no normal/exploratory branch that surfaces the
	// conflict alongside an answer.
	touching := make([]ConflictPair, 0, len(conflictPairs))
	for _, pair := range conflictPairs {
		if pair.Left == topIndex || pair.Right == topIndex {
			touching = append(touching, pair)
		}
	}
	if len(touching) > 0 {
		return conflictAbstention(
			window, touching, len(conflictPairs), independent, answerLanguage, languages, unsupported,
		), nil
	}

	// Count the INDEPENDENT evidence, not the retrieved rows. Clones of one
	// sentence ingested under several document ids are one fact, and reporting
	// them as N corroborating sources rewards a poisoned corpus: inject N copies,
	// earn N-fold confidence. The abstention path above already counts
	// `independent`; counting `grounded` here left the two paths disagreeing and
	// the answered path claiming more support than it listed sources for.
	distinct := make(map[string]struct{}, len(independent))
	for _, r := range independent {
		distinct[r.documentID] = struct{}{}
	}

	// Only SUPPORTED claims reach the answer; every atomic claim keeps its own
	// verdict, so a drop is auditable rather than silent (flow.py:357-374). The
	// decision stays `answered` even when a claim was dropped — Python's strict
	// flow never emits `partial` (that value is agentic.py's, for deep-ask); the
	// drop is reported by AllClaimsVerified=false + UnsupportedClaimsRemoved.
	supported := make([]string, 0, len(verdicts))
	claims := make([]result.Claim, 0, len(verdicts))
	for _, v := range verdicts {
		sources := []string{}
		if v.supported {
			supported = append(supported, v.text)
			sources = []string{top.euID}
		}
		claims = append(claims, result.Claim{Claim: v.text, Supported: v.supported, Sources: sources})
	}
	removed := len(verdicts) - len(supported)

	return result.Result{
		Answer:         strings.Join(supported, " "),
		AnswerLanguage: answerLanguage,
		Mode:           result.TrustModeStrict,
		Evidence: result.EvidenceSignals{
			Decision:                 result.DecisionAnswered,
			SupportingSources:        len(independent),
			DistinctDocuments:        len(distinct),
			AllClaimsVerified:        removed == 0,
			UnsupportedClaimsRemoved: removed,
			ConflictsDetected:        len(conflictPairs),
			LanguagesInEvidence:      languages,
			UnsupportedScripts:       unsupported,
		},
		Claims: claims,
		Sources: []result.SourceRef{
			{Document: top.documentID, Passage: passage, PassageLanguage: passageLanguage(top)},
		},
		// "I answered, but there is material here I cannot read." Empty on every
		// corpus without an unclaimed script, so those Results are unchanged.
		MissingEvidence: unreachableNote(blocked),
		Conflicts:       []string{},
		Provenance:      []result.ProvenanceEntry{},
	}, nil
}

// blockedRow is one candidate the tokenizer cannot read, with the unclaimed
// scripts that made it unreadable.
type blockedRow struct {
	row     row
	scripts []string
}

// claimVerdict is one atomic claim and whether the cited passage supports it.
type claimVerdict struct {
	text      string
	supported bool
}

// passageLanguage is the cited passage's DECLARED language, or the pinned "und"
// when the document declared none — `candidate.language or "und"` in the Python
// reference (flow.py:364). Never the answer language.
func passageLanguage(r row) string {
	if r.language == "" {
		return undeclaredLanguage
	}
	return r.language
}

// sortedUnique is the sorted set union of the given script lists, always non-nil
// so it marshals as [] rather than null.
func sortedUnique(lists ...[]string) []string {
	seen := map[string]struct{}{}
	out := []string{}
	for _, list := range lists {
		for _, s := range list {
			if _, ok := seen[s]; ok {
				continue
			}
			seen[s] = struct{}{}
			out = append(out, s)
		}
	}
	sort.Strings(out)
	return out
}

// refusal is the localized refusal shell, mirroring answer/flow.py:50.
//
// `reason` is the ONE cause that actually produced the refusal; `unreachable` is
// an additive note about material that was present but could not be read. The
// two are separate on purpose — the second must never overwrite the first.
func refusal(answerLanguage, reason string, unsupported, unreachable []string) result.Result {
	res := result.Refused(result.TrustModeStrict)
	res.AnswerLanguage = answerLanguage
	res.Evidence.UnsupportedScripts = unsupported
	res.MissingEvidence = append([]string{reason}, unreachable...)
	return res
}

// capabilityReason is the refusal reason when the tokenizer cannot read the
// QUESTION at all (ADR-0011, flow.py:78).
//
// It is reserved for the QUESTION on purpose. Applying it to the whole pool ran
// the conflation backwards: one unreadable row anywhere in the top-k rewrote the
// reason for an unrelated, purely-English refusal (measured: 11 of 14 refusals
// reported "unsupported script: unknown" over an English-only corpus).
func capabilityReason(scripts []string) string {
	return "unsupported script: " + strings.Join(scripts, ", ")
}

// unreadableReason is the refusal reason when the script gap genuinely explains
// the abstain: there WAS material, and we could not read it (flow.py:99).
func unreadableReason(scripts []string) string {
	return "no readable evidence found; unsupported script: " + strings.Join(scripts, ", ")
}

// unreachableNote is the additive line naming material present but unreadable
// (flow.py:108). Measured: a Telugu annexure that capped leave at 5 days and
// stated it overrode was silently skipped while the English handbook answered
// "a maximum of 10 days" — correctly cited, 100% grounded, and superseded.
//
// We cannot read that annexure, so we assert nothing about it and we do not
// delete a correct, grounded answer over it. What we can do is say it is there.
func unreachableNote(blocked []blockedRow) []string {
	if len(blocked) == 0 {
		return []string{}
	}
	order := []string{}
	byDocument := map[string][]string{}
	for _, b := range blocked {
		document := b.row.documentID
		if document == "" {
			document = b.row.euID
		}
		if _, ok := byDocument[document]; !ok {
			order = append(order, document)
		}
		byDocument[document] = sortedUnique(byDocument[document], b.scripts)
	}
	named := make([]string, 0, len(order))
	for _, document := range order {
		named = append(named, fmt.Sprintf("%s (%s)", document, strings.Join(byDocument[document], ", ")))
	}
	return []string{fmt.Sprintf(
		"%d candidate document(s) could not be read and were excluded: %s",
		len(order), strings.Join(named, ", "),
	)}
}

// textsOf is the citable text of each row, in order. The Python reference
// compares `citable_text` — the VERBATIM chunk — never the contextualized text;
// this port has no contextual-retrieval layer, so row.text IS the verbatim
// chunk.
func textsOf(rows []row) []string {
	out := make([]string, len(rows))
	for i, r := range rows {
		out[i] = r.text
	}
	return out
}

// conflictAbstention is the strict-mode abstention that CITES BOTH SIDES of the
// disagreement.
//
// A refusal that hides the evidence is only marginally better than a confident
// pick: the caller cannot check the library's reasoning or resolve the conflict
// themselves. Both passages are returned as sources, verbatim.
func conflictAbstention(
	window []row,
	touching []ConflictPair,
	totalConflicts int,
	independent []row,
	answerLanguage string,
	languages []string,
	unsupported []string,
) result.Result {
	documents := make([]string, len(window))
	for i, r := range window {
		documents[i] = r.documentID
	}

	cited := []result.SourceRef{}
	seen := map[string]struct{}{}
	for _, pair := range touching {
		for _, r := range [2]row{window[pair.Left], window[pair.Right]} {
			if _, ok := seen[r.euID]; ok {
				continue
			}
			seen[r.euID] = struct{}{}
			cited = append(cited, result.SourceRef{
				Document:        r.documentID,
				Passage:         r.text,
				PassageLanguage: passageLanguage(r),
			})
		}
	}

	distinct := map[string]struct{}{}
	for _, r := range independent {
		distinct[r.documentID] = struct{}{}
	}

	return result.Result{
		Answer:         result.ConflictRefusalAnswer,
		AnswerLanguage: answerLanguage,
		Mode:           result.TrustModeStrict,
		Evidence: result.EvidenceSignals{
			Decision:          result.DecisionRefused,
			SupportingSources: len(independent),
			DistinctDocuments: len(distinct),
			// RetrievalScoreSpread stays 0: this port's answered path does not
			// populate it either, and inventing a number on one path only would
			// make the two disagree about what the field means.
			ConflictsDetected:   totalConflicts,
			LanguagesInEvidence: languages,
			UnsupportedScripts:  unsupported,
		},
		Claims:          []result.Claim{},
		Sources:         cited,
		MissingEvidence: []string{"cited sources disagree and the conflict is unresolved"},
		Conflicts:       DescribeConflicts(touching, documents),
		Provenance:      []result.ProvenanceEntry{},
	}
}

// dot is the cosine of two already-L2-normalized vectors, guarded against a
// length mismatch. fakes.Cosine indexes b[i] for every i in a and would panic on
// a shorter b; the dimension guard should make that unreachable, but
// "unreachable" is not a memory-safety argument when the vectors come from an
// arbitrary third-party provider.
func dot(a, b []float64) float64 {
	n := len(a)
	if len(b) < n {
		n = len(b)
	}
	var sum float64
	for i := 0; i < n; i++ {
		sum += a[i] * b[i]
	}
	return sum
}

// hermeticEmbedding wraps this port's deterministic fake in the published batch
// contract, so the fallback path and the injected path are ONE code path rather
// than two branches that can drift.
type hermeticEmbedding struct{}

func (hermeticEmbedding) Embed(texts []string) ([][]float64, error) {
	out := make([][]float64, len(texts))
	for i, text := range texts {
		out[i] = fakes.FakeEmbedding{}.Embed(text)
	}
	return out, nil
}

// hermeticGenerator wraps the evidence-echoing fake in the published contract.
// It cannot fail, which is why Ask can drop the error return.
type hermeticGenerator struct{}

func (hermeticGenerator) Answer(question, passage, _ string) (string, error) {
	return fakes.FakeLLM{}.Answer(question, passage), nil
}

// Compile-time proof that the fallbacks are the published contracts, not a
// private shortcut around them.
var (
	_ contracts.EmbeddingProvider = hermeticEmbedding{}
	_ contracts.GeneratorProvider = hermeticGenerator{}
)
