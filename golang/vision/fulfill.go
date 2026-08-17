// Fulfil phase — the host makes the model call (ADR-0005, §9).
//
// The two-phase seam has the HOST make every model call. This package emits
// credential-free PendingRequests; a Fulfiller — models.OpenAIVision in
// production, a closure in tests — POSTs each payload with its own transport,
// auth and concurrency and hands back the parsed reply. Two invariants live
// here:
//
//   - Credential containment: the fulfiller only ever sees a PendingRequest
//     (image content, no key); the key stays inside the client's transport.
//   - Per-request isolation: a request whose fulfillment FAILS is dropped from
//     the result — degrade-to-text — never failing the ones that succeeded, and
//     never fabricating a caption to stand in for the missing one.

package vision

import "strings"

// Fulfiller is the host-side seam, deliberately the thin "POST payload → return
// the parsed reply" shape ADR-0005 prescribes for a non-Python port. It is a
// plain func type, not an interface: there is nothing to subclass, and any
// model client with a matching method value satisfies it.
type Fulfiller func(imageURL, prompt string) (map[string]any, error)

// imageID parses the image's own id back out of a request_id
// ({document}::img::{image_id}); the assemble join keys on request_id.
func imageID(requestID string) string {
	if idx := strings.LastIndex(requestID, "::img::"); idx >= 0 {
		return requestID[idx+len("::img::"):]
	}
	return requestID
}

// FulfillRequests runs each pending request through fulfill and joins the
// results by request_id.
//
// The emitted payload is handed over VERBATIM (no re-encode), so the host POSTs
// exactly what this package emitted and every port reproduces the same bytes. A
// request whose fulfillment returns an error — or a nil mapping — is SKIPPED, so
// one failing image never fails the ingest of the rest and never yields an
// invented description. Port of vision/fulfill.py:56.
func FulfillRequests(requests []PendingRequest, fulfill Fulfiller) map[string]Record {
	fulfilled := map[string]Record{}
	for _, request := range requests {
		mapping, err := fulfill(request.Payload.ImageURL, request.Payload.Prompt)
		if err != nil || mapping == nil {
			continue
		}
		fulfilled[request.RequestID] = RecordFromMapping(imageID(request.RequestID), mapping)
	}
	return fulfilled
}
