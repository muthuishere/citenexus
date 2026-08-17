// Emit phase — the pure builder for a PendingRequest (ADR-0005, §9).
//
// The deterministic heart of the two-phase seam: the exact request bytes — the
// data URI encoding, the prompt, the request_id format — are computed here and
// pinned as conformance/cases/vision_orchestration.json. Credential-free by
// construction: the payload the host POSTs carries the image and the prompt and
// nothing else.

package vision

import (
	"bytes"
	"encoding/base64"
)

// BBox is a bounding box [x0, y0, x1, y1] in page coordinates.
// Mirrors python/src/citenexus/domain/vision.py:26.
type BBox [4]float64

// SourceRef is where an emitted request's figure lives — the citation target
// the assembled figure Evidence Unit points back at.
type SourceRef struct {
	Document  string  `json:"document"`
	Page      *int    `json:"page"`
	BBox      *BBox   `json:"bbox"`
	SourceURI *string `json:"source_uri"`
}

// Payload is the model-ready content the host POSTs: the prompt plus the base64
// image_url data URI, both assembled by the core. Provider-shaped (OpenAI
// image_url) and credential-free — the host wraps it in its own request with its
// own model, temperature and auth.
type Payload struct {
	Prompt   string `json:"prompt"`
	ImageURL string `json:"image_url"`
}

// PendingRequest is one figure awaiting host fulfillment — the two-phase seam's
// unit of work. RequestID is the figure's future eu_id ({document}::img::{image_id})
// and the sole key a fulfilled description is addressed back by.
type PendingRequest struct {
	RequestID string    `json:"request_id"`
	Payload   Payload   `json:"payload"`
	SourceRef SourceRef `json:"source_ref"`
}

// defaultSubtype is the fallback when the bytes carry no recognized magic —
// matches the extractor's default so unrecognized blobs stay stable.
const defaultSubtype = "png"

// SniffImageSubtype recognizes the image type from its magic bytes and returns
// the image/<subtype> subtype (png/jpeg/gif/webp), or "" if unrecognized.
// Byte-for-byte port of python/src/citenexus/extract/mime.py:13.
func SniffImageSubtype(data []byte) string {
	switch {
	case bytes.HasPrefix(data, []byte("\x89PNG\r\n\x1a\n")):
		return "png"
	case bytes.HasPrefix(data, []byte("\xff\xd8\xff")):
		return "jpeg"
	case bytes.HasPrefix(data, []byte("GIF87a")), bytes.HasPrefix(data, []byte("GIF89a")):
		return "gif"
	case len(data) >= 12 && bytes.Equal(data[0:4], []byte("RIFF")) && bytes.Equal(data[8:12], []byte("WEBP")):
		return "webp"
	}
	return ""
}

// ImageDataURI encodes image bytes as an OpenAI-shaped base64 image_url data URI.
//
// The core owns the payload, so it declares the image's TRUE format by sniffing
// the magic bytes (§9) — a JPEG figure emits data:image/jpeg — so a port that
// POSTs the pinned payload verbatim never mislabels the media type.
func ImageDataURI(data []byte) string {
	subtype := SniffImageSubtype(data)
	if subtype == "" {
		subtype = defaultSubtype
	}
	return "data:image/" + subtype + ";base64," + base64.StdEncoding.EncodeToString(data)
}

// BuildRequestOptions carries the optional citation geometry of an emitted request.
type BuildRequestOptions struct {
	Page      *int
	BBox      *BBox
	SourceURI *string
}

// BuildPendingRequest shapes one image + its bytes into a model-ready,
// credential-free request. Port of vision/requests.py:33.
func BuildPendingRequest(documentID, imageID string, data []byte, prompt string, opts BuildRequestOptions) PendingRequest {
	return PendingRequest{
		RequestID: documentID + "::img::" + imageID,
		Payload:   Payload{Prompt: prompt, ImageURL: ImageDataURI(data)},
		SourceRef: SourceRef{
			Document:  documentID,
			Page:      opts.Page,
			BBox:      opts.BBox,
			SourceURI: opts.SourceURI,
		},
	}
}
