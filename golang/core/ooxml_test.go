//go:build citenexus_ffi

package core

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

func docxOf(t *testing.T, documentXML string) []byte {
	t.Helper()
	var buf bytes.Buffer
	w := zip.NewWriter(&buf)
	f, err := w.Create("word/document.xml")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.Write([]byte(documentXML)); err != nil {
		t.Fatal(err)
	}
	if err := w.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

const goDocx = `<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Scope</w:t></w:r></w:p>
<w:tbl><w:tblGrid><w:gridCol/><w:gridCol/></w:tblGrid>
<w:tr><w:tc><w:p><w:r><w:t>k</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>v</w:t></w:r></w:p></w:tc></w:tr>
<w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr><w:p><w:r><w:t>both</w:t></w:r></w:p></w:tc></w:tr>
</w:tbl></w:body></w:document>`

func TestOoxmlUnits(t *testing.T) {
	units, err := OoxmlUnits(docxOf(t, goDocx), "docx")
	if err != nil {
		t.Fatalf("OoxmlUnits: %v", err)
	}
	if len(units) != 2 {
		t.Fatalf("got %d units, want 2: %+v", len(units), units)
	}
	h := units[0]
	if h.Kind != "heading" || h.Markdown != "# Scope" || h.Level == nil || *h.Level != 1 ||
		h.Provenance.Route != "ooxml" || h.Provenance.HeadingSource == nil || *h.Provenance.HeadingSource != "style" {
		t.Fatalf("heading unit wrong: %+v", h)
	}
	tbl := units[1]
	if tbl.Kind != "table" || tbl.Markdown != "| k | v |\n| --- | --- |\n| both |  |" ||
		tbl.Provenance.TableSource == nil || *tbl.Provenance.TableSource != "ooxml" || !tbl.Provenance.TableUncertain {
		t.Fatalf("table unit wrong: %+v", tbl)
	}

	// determinism: byte-identical across calls
	again, _ := OoxmlUnits(docxOf(t, goDocx), "docx")
	a, _ := json.Marshal(units)
	b, _ := json.Marshal(again)
	if !bytes.Equal(a, b) {
		t.Fatalf("non-deterministic output:\n%s\n%s", a, b)
	}

	if _, err := OoxmlUnits([]byte("not a zip"), "docx"); err == nil || !strings.Contains(err.Error(), "zip") {
		t.Fatalf("want zip error, got %v", err)
	}
	if _, err := OoxmlUnits(docxOf(t, goDocx), "xlsx"); err == nil {
		t.Fatal("want error for xlsx hint")
	}
}
