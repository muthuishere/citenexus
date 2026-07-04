// Package graph is the deterministic, model-free co-mention graph over indexed
// Evidence Units (SPEC §10b), ported byte-identical to the Python arbiter
// citenexus.graph.store.build_comention_graph.
//
// A node is a content token of length >= 4; an edge is a within-EU co-mention,
// weighted by count. Nodes sort by label, edges by (source-label, target-label),
// so the artifact is byte-stable across languages.
package graph

import (
	"sort"

	"github.com/muthuishere/citenexus/golang/gate"
)

const minTokenLen = 4

// Row is one Evidence Unit input: {eu_id, text}.
type Row struct {
	EUID string `json:"eu_id"`
	Text string `json:"text"`
}

// Node is one canonical graph node and the EUs mentioning it.
type Node struct {
	NodeID string   `json:"node_id"`
	Label  string   `json:"label"`
	EURefs []string `json:"eu_refs"`
}

// Edge is a co-mention edge between graph nodes. Relation is nil for
// deterministic co-mention edges (Python emits relation: null).
type Edge struct {
	Source   string  `json:"source"`
	Target   string  `json:"target"`
	Weight   int     `json:"weight"`
	Relation *string `json:"relation"`
}

// Index is the graph artifact for one leaf partition.
type Index struct {
	Nodes []Node `json:"nodes"`
	Edges []Edge `json:"edges"`
}

// graphTokens returns the content tokens of text filtered to length >= 4.
func graphTokens(text string) []string {
	out := make([]string, 0)
	for tok := range gate.ContentTokens(text) {
		if len(tok) >= minTokenLen {
			out = append(out, tok)
		}
	}
	return out
}

func nodeID(label string) string {
	return "node:" + label
}

type pair struct {
	left  string
	right string
}

// BuildComentionGraph is the deterministic co-mention graph over EU rows (§10b).
//
// Each row is {eu_id, text}. Per row, tokens = sorted unique graph tokens; each
// token records the eu_id, and each ordered pair (i<j) increments the co-mention
// count. Nodes sort by label, edges by (left, right) token pair.
func BuildComentionGraph(rows []Row) Index {
	mentions := make(map[string]map[string]struct{})
	coMentions := make(map[pair]int)

	for _, row := range rows {
		// sorted unique tokens
		set := make(map[string]struct{})
		for _, tok := range graphTokens(row.Text) {
			set[tok] = struct{}{}
		}
		tokens := make([]string, 0, len(set))
		for tok := range set {
			tokens = append(tokens, tok)
		}
		sort.Strings(tokens)

		for _, tok := range tokens {
			if mentions[tok] == nil {
				mentions[tok] = make(map[string]struct{})
			}
			mentions[tok][row.EUID] = struct{}{}
		}
		for i, left := range tokens {
			for _, right := range tokens[i+1:] {
				coMentions[pair{left, right}]++
			}
		}
	}

	// Nodes sorted by label.
	labels := make([]string, 0, len(mentions))
	for label := range mentions {
		labels = append(labels, label)
	}
	sort.Strings(labels)

	nodes := make([]Node, 0, len(labels))
	for _, label := range labels {
		refs := make([]string, 0, len(mentions[label]))
		for ref := range mentions[label] {
			refs = append(refs, ref)
		}
		sort.Strings(refs)
		nodes = append(nodes, Node{
			NodeID: nodeID(label),
			Label:  label,
			EURefs: refs,
		})
	}

	// Edges sorted by (left, right) token pair.
	pairs := make([]pair, 0, len(coMentions))
	for p := range coMentions {
		pairs = append(pairs, p)
	}
	sort.Slice(pairs, func(a, b int) bool {
		if pairs[a].left != pairs[b].left {
			return pairs[a].left < pairs[b].left
		}
		return pairs[a].right < pairs[b].right
	})

	edges := make([]Edge, 0, len(pairs))
	for _, p := range pairs {
		w := coMentions[p]
		if w <= 0 {
			continue
		}
		edges = append(edges, Edge{
			Source:   nodeID(p.left),
			Target:   nodeID(p.right),
			Weight:   w,
			Relation: nil,
		})
	}

	return Index{Nodes: nodes, Edges: edges}
}
