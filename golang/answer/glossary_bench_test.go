package answer

import (
	"context"
	"encoding/json"
	"fmt"
	"runtime"
	"sync"
	"testing"
)

// syntheticGlossary builds ~n entries of made-up NL/EN forms with lemmas.
func syntheticGlossary(n int) []GlossaryEntry {
	out := make([]GlossaryEntry, 0, n)
	for i := 0; len(out) < n; i++ {
		lemma := fmt.Sprintf("woord%d", i)
		for k := 0; k < 4 && len(out) < n; k++ {
			out = append(out, GlossaryEntry{NL: fmt.Sprintf("%sen%d", lemma, k), EN: fmt.Sprintf("word%ds%d", i, k),
				LemmaNL: lemma, LemmaEN: fmt.Sprintf("word%d", i), Class: "noun"})
		}
	}
	return append(out, GlossaryEntry{NL: "verlof", EN: "leave", LemmaNL: "verlof", LemmaEN: "leave", Class: "other"})
}

const benchAnswer = "You apply for the leave four weeks in advance [eu:a]."

func benchSetup(opts VerifyOptions) ([]EvidenceUnit, VerifyOptions) {
	ev := []EvidenceUnit{{ID: "a", DocumentID: "a", Language: "nl", Text: "De werknemer vraagt het verlof ten minste vier weken van tevoren aan bij de leidinggevende."}}
	opts.AnswerLanguage, opts.AdmitParaphrase = "en", true
	opts.Checker, opts.CheckerName = &fakeChecker{scores: map[string][2]float64{ev[0].Text: {0.999, 0}}}, "fake"
	return ev, opts
}

func benchmarkGlossary(b *testing.B, opts VerifyOptions) {
	ev, opts := benchSetup(opts)
	if _, err := VerifyAnswer(context.Background(), benchAnswer, ev, opts); err != nil { // warm the lazy cache
		b.Fatal(err)
	}
	b.ReportAllocs()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		if _, err := VerifyAnswer(context.Background(), benchAnswer, ev, opts); err != nil {
			b.Fatal(err)
		}
	}
}

// BenchmarkVerifyAnswerWithGlossary: a ~100k-row glossary on a one-claim
// answer. The glossary must be prepared once, not per call.
func BenchmarkVerifyAnswerWithGlossary(b *testing.B) {
	benchmarkGlossary(b, VerifyOptions{GlossaryPrepared: PrepareGlossary(nil, syntheticGlossary(100_000))})
}

// BenchmarkVerifyAnswerWithGlossaryLazy: the legacy GlossaryEntries field,
// prepared on first use and cached by slice identity.
func BenchmarkVerifyAnswerWithGlossaryLazy(b *testing.B) {
	benchmarkGlossary(b, VerifyOptions{GlossaryEntries: syntheticGlossary(100_000)})
}

func BenchmarkVerifyAnswerNoGlossary(b *testing.B) {
	benchmarkGlossary(b, VerifyOptions{})
}

// TestGlossaryPerCallAllocation pins the perf fix: with a 100k-row glossary,
// prepared or passed as the legacy slice, the glossary adds under 100 KB per
// VerifyAnswer call over the same call with no glossary (before the fix it
// added ~6 GB: the glossary was re-expanded on every call). The no-glossary
// call itself is ~113 KB, so the bound is on the glossary's share.
func TestGlossaryPerCallAllocation(t *testing.T) {
	if testing.Short() {
		t.Skip("builds a 100k-row glossary")
	}
	if raceEnabled {
		t.Skip("the race detector inflates allocations (~+400 KB per call); the bound holds without it")
	}
	perCall := func(o VerifyOptions) uint64 {
		ev, opts := benchSetup(o)
		if _, err := VerifyAnswer(context.Background(), benchAnswer, ev, opts); err != nil {
			t.Fatal(err)
		}
		const runs = 20
		var before, after runtime.MemStats
		runtime.GC()
		runtime.ReadMemStats(&before)
		for i := 0; i < runs; i++ {
			if _, err := VerifyAnswer(context.Background(), benchAnswer, ev, opts); err != nil {
				t.Fatal(err)
			}
		}
		runtime.ReadMemStats(&after)
		return (after.TotalAlloc - before.TotalAlloc) / runs
	}
	base := perCall(VerifyOptions{})
	entries := syntheticGlossary(100_000)
	for name, o := range map[string]VerifyOptions{
		"prepared": {GlossaryPrepared: PrepareGlossary(nil, entries)},
		"lazy":     {GlossaryEntries: entries},
	} {
		if per := perCall(o); per > base+100_000 {
			t.Errorf("%s: %d B per VerifyAnswer call vs %d B without a glossary; the glossary may add < 100 KB (re-expanded per call?)", name, per, base)
		}
	}
}

func BenchmarkPrepareGlossary(b *testing.B) {
	entries := syntheticGlossary(100_000)
	b.ReportAllocs()
	for i := 0; i < b.N; i++ {
		PrepareGlossary(nil, entries)
	}
}

// TestPreparedGlossaryConcurrent: one PreparedGlossary, and the lazy cache
// behind the legacy slices, are shared by concurrent VerifyAnswer calls
// (run under -race) and give the verdict a fresh preparation gives.
func TestPreparedGlossaryConcurrent(t *testing.T) {
	entries := syntheticGlossary(200)
	pairs := [][2]string{{"leidinggevende", "manager"}}
	ev, want := benchSetup(VerifyOptions{GlossaryPrepared: PrepareGlossary(pairs, entries)})
	verdict := func(o VerifyOptions) string {
		r, err := VerifyAnswer(context.Background(), benchAnswer, ev, o)
		if err != nil {
			return "error: " + err.Error()
		}
		j, _ := json.Marshal(r)
		return string(j)
	}
	ref := verdict(want)
	var wg sync.WaitGroup
	for i := 0; i < 16; i++ {
		_, o := benchSetup(want) // a fresh fake checker per goroutine: the fake counts calls
		if i%2 == 1 {
			o.GlossaryPrepared, o.Glossary, o.GlossaryEntries = nil, pairs, entries
		}
		wg.Add(1)
		go func(o VerifyOptions) {
			defer wg.Done()
			if got := verdict(o); got != ref {
				t.Errorf("concurrent verdict %s differs from %s", got, ref)
			}
		}(o)
	}
	wg.Wait()
}
