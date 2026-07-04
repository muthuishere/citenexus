// Structure Index — best-effort, source-type-aware document structure (spec §7b).
// Byte-identical port of the Python arbiter citenexus.evidence.structure.
// build_structure. Structure is polymorphic and optional: a heading document is
// a nested heading tree, a deck is a flat slide sequence, and every other type
// (including "none", or a heading document with no headings) degrades to zero
// nodes — a normal outcome, never a failure. All nodes share one uniform shape.

/** One extracted block of a document. */
export interface StructureBlock {
  order: number;
  kind: string;
  text: string;
  level: number | null;
}

/** The extracted document fed to the structure builder. */
export interface StructureDoc {
  document_id: string;
  structure_type: string;
  blocks: StructureBlock[];
}

/** One node of a document's structure, uniform across all types. */
export interface StructureNode {
  node_id: string;
  parent_id: string | null;
  label: string;
  kind: string;
  eu_ref: string;
}

/** The structure of one document: its type plus uniform-shape nodes. */
export interface StructureIndex {
  document_id: string;
  structure_type: string;
  nodes: StructureNode[];
}

function euRef(doc: StructureDoc, block: StructureBlock): string {
  return `${doc.document_id}::${block.order}`;
}

/** Nest heading blocks by level; no headings ⇒ zero nodes. */
function headingTree(doc: StructureDoc): StructureNode[] {
  const nodes: StructureNode[] = [];
  // Stack of [level, node_id] ancestors; pop until the top is a strict parent.
  const stack: Array<[number, string]> = [];
  for (const block of doc.blocks) {
    if (block.kind !== "heading" || block.text.trim() === "") continue;
    const level = block.level ?? 1;
    while (stack.length > 0 && stack[stack.length - 1]![0] >= level) {
      stack.pop();
    }
    const parentId = stack.length > 0 ? stack[stack.length - 1]![1] : null;
    const nodeId = euRef(doc, block);
    nodes.push({
      node_id: nodeId,
      parent_id: parentId,
      label: block.text,
      kind: "heading",
      eu_ref: nodeId,
    });
    stack.push([level, nodeId]);
  }
  return nodes;
}

/** One flat node per slide block, in document order. */
function slideSequence(doc: StructureDoc): StructureNode[] {
  const nodes: StructureNode[] = [];
  for (const block of doc.blocks) {
    if (block.kind !== "slide" || block.text.trim() === "") continue;
    const nodeId = euRef(doc, block);
    nodes.push({
      node_id: nodeId,
      parent_id: null,
      label: block.text,
      kind: "slide",
      eu_ref: nodeId,
    });
  }
  return nodes;
}

/** Build the best-effort Structure Index for `doc` (§7b). */
export function buildStructure(doc: StructureDoc): StructureIndex {
  let nodes: StructureNode[];
  if (doc.structure_type === "heading_tree") {
    nodes = headingTree(doc);
  } else if (doc.structure_type === "slide_sequence") {
    nodes = slideSequence(doc);
  } else {
    nodes = [];
  }
  return {
    document_id: doc.document_id,
    structure_type: doc.structure_type,
    nodes,
  };
}
