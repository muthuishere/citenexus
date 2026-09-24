//go:build citenexus_ffi

package core

import (
	"encoding/json"
	"fmt"
	"os"
)

func jsonUnmarshal(s string, v any) error { return json.Unmarshal([]byte(s), v) }

// A model client the host already has: returns (text, finishReason, error).
// Stubbed here; in production this is the host's own LLM / vision call.
type modelClient func(prompt string, req PdfRequest, seed int) (string, string, error)

// Example_harness is the whole host loop of the PDF model contract
// (docs/pdf-model-contract.md): PdfPrepare -> fulfil every request -> PdfAssemble.
// Compiled with `go test -tags citenexus_ffi`, so the documented loop cannot rot.
func Example_harness() {
	pdf, err := os.ReadFile("../../rust/tests/data/pdf/assemble-mixed.pdf")
	if err != nil {
		return
	}
	opts := PdfOptions{Language: "nl"}

	prep, err := PdfPrepare(pdf, opts)
	if err != nil {
		return // no pdfium / not a PDF: nothing to do
	}

	var tableModel, visionModelA, visionModelB modelClient // the host's clients
	var responses []PdfResponse
	for _, req := range prep.Requests {
		switch req.Kind {
		case "table_structure":
			// Send req.Words (IDs + boxes); expect a grid of WORD IDS back.
			if tableModel == nil {
				continue // no model: base output stays
			}
			raw, finish, err := tableModel(req.Prompt, req, 0)
			if err != nil {
				continue // error/timeout: omit the response -> base output
			}
			var grids struct {
				Tables []PdfGrid `json:"tables"`
			}
			if jsonErr := jsonUnmarshal(raw, &grids); jsonErr != nil {
				continue
			}
			responses = append(responses, PdfResponse{RequestID: req.ID, FinishReason: finish, Tables: grids.Tables})
		case "vision_page", "vision_region":
			// Two variants per region: fulfil EACH with an independent call
			// (a different model, or the same model with a different seed).
			client, seed := visionModelA, 1
			if req.Variant != nil && *req.Variant == 2 {
				client, seed = visionModelB, 2
			}
			if client == nil {
				continue
			}
			md, finish, err := client(req.Prompt, req, seed)
			if err != nil {
				continue // the other variant alone -> the unit is all disputed
			}
			responses = append(responses, PdfResponse{RequestID: req.ID, FinishReason: finish, Markdown: &md})
		}
	}

	res, err := PdfAssemble(pdf, opts, responses)
	if err != nil {
		return
	}
	for _, u := range res.Units {
		cite := CitableText(u.Markdown) // never cite <!-- vision_disputed --> text
		_ = cite
		if u.Provenance.FailedCheck != nil {
			fmt.Fprintln(os.Stderr, "fell back to base text:", *u.Provenance.FailedCheck)
		}
	}
}
