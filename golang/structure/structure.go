// Package structure builds the best-effort, source-type-aware Structure Index
// for a document (SPEC §7b), ported byte-identical to the Python arbiter
// citenexus.evidence.structure.build_structure.
//
// Structure is polymorphic and optional: a heading_tree nests heading blocks by
// level; a slide_sequence yields one flat node per slide; every other type
// (including "none") yields zero nodes. The result is always a valid Index; an
// empty one is a normal outcome, never an error.
package structure

import "strings"

// Block is one extracted document block. Level is nil (defaults to 1) for
// non-heading blocks.
type Block struct {
	Order int    `json:"order"`
	Kind  string `json:"kind"`
	Text  string `json:"text"`
	Level *int   `json:"level"`
}

// Doc is the input document: its id, structure type, and ordered blocks.
type Doc struct {
	DocumentID    string  `json:"document_id"`
	StructureType string  `json:"structure_type"`
	Blocks        []Block `json:"blocks"`
}

// Node is one node of a document's structure, in a shape uniform across all types.
type Node struct {
	NodeID   string  `json:"node_id"`
	ParentID *string `json:"parent_id"`
	Label    string  `json:"label"`
	Kind     string  `json:"kind"`
	EURef    string  `json:"eu_ref"`
}

// Index is the structure of one document: its type plus uniform-shape nodes.
type Index struct {
	DocumentID    string `json:"document_id"`
	StructureType string `json:"structure_type"`
	Nodes         []Node `json:"nodes"`
}

func euRef(doc Doc, block Block) string {
	return doc.DocumentID + "::" + itoa(block.Order)
}

// itoa avoids importing strconv for a single use; orders are small non-negative
// ints in practice but this handles the general signed case.
func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	neg := n < 0
	if neg {
		n = -n
	}
	var buf [20]byte
	i := len(buf)
	for n > 0 {
		i--
		buf[i] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		i--
		buf[i] = '-'
	}
	return string(buf[i:])
}

type stackEntry struct {
	level  int
	nodeID string
}

// headingTree nests heading blocks by their level; no headings => zero nodes.
func headingTree(doc Doc) []Node {
	nodes := make([]Node, 0)
	stack := make([]stackEntry, 0)
	for _, block := range doc.Blocks {
		if block.Kind != "heading" || strings.TrimSpace(block.Text) == "" {
			continue
		}
		level := 1
		if block.Level != nil {
			level = *block.Level
		}
		for len(stack) > 0 && stack[len(stack)-1].level >= level {
			stack = stack[:len(stack)-1]
		}
		var parentID *string
		if len(stack) > 0 {
			p := stack[len(stack)-1].nodeID
			parentID = &p
		}
		id := euRef(doc, block)
		nodes = append(nodes, Node{
			NodeID:   id,
			ParentID: parentID,
			Label:    block.Text,
			Kind:     "heading",
			EURef:    id,
		})
		stack = append(stack, stackEntry{level: level, nodeID: id})
	}
	return nodes
}

// slideSequence yields one flat node per slide block, in document order.
func slideSequence(doc Doc) []Node {
	nodes := make([]Node, 0)
	for _, block := range doc.Blocks {
		if block.Kind != "slide" || strings.TrimSpace(block.Text) == "" {
			continue
		}
		id := euRef(doc, block)
		nodes = append(nodes, Node{
			NodeID:   id,
			ParentID: nil,
			Label:    block.Text,
			Kind:     "slide",
			EURef:    id,
		})
	}
	return nodes
}

// BuildStructure builds the best-effort Structure Index for doc (§7b). Dispatch
// is by doc.StructureType; every type other than heading_tree / slide_sequence
// (including "none") degrades to zero nodes.
func BuildStructure(doc Doc) Index {
	var nodes []Node
	switch doc.StructureType {
	case "heading_tree":
		nodes = headingTree(doc)
	case "slide_sequence":
		nodes = slideSequence(doc)
	default:
		nodes = make([]Node, 0)
	}
	return Index{
		DocumentID:    doc.DocumentID,
		StructureType: doc.StructureType,
		Nodes:         nodes,
	}
}
