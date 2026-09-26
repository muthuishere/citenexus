// Glossary entries with lemmas, separable particles and classes — port of
// golang/answer/glossary.go.
//
// VerifyOptions.glossary is a list of term pairs. GlossaryEntry adds what a
// matcher needs to read a form through its lemma: every NL form of a lemma
// translates to every EN form of it; `sep` is the particle of a Dutch separable
// verb; `class` is party | group | verb | hedge | qualifier.

import { byteLen, goLower, goTrimSpace } from "./gotext.js";
import { glossaryIndex } from "./verify-conditions.js";

/** One NL/EN surface pair with its lemmas, particle and class. */
export interface GlossaryEntry {
  nl: string;
  en: string;
  lemmaNL?: string;
  lemmaEN?: string;
  sep?: string;
  class?: string;
}

/** Read a tab-separated glossary with a header row (nl, en, lemma_nl,
 * lemma_en, sep, class; other columns ignored). */
export function parseGlossaryTSV(text: string): GlossaryEntry[] {
  let col: Map<string, number> | null = null;
  const out: GlossaryEntry[] = [];
  const lines = text.split("\n");
  if (lines.length > 0 && lines[lines.length - 1] === "") lines.pop();
  for (let line of lines) {
    if (line.endsWith("\r")) line = line.slice(0, -1); // bufio.ScanLines drops a trailing \r
    const f = line.split("\t");
    if (col === null) {
      col = new Map();
      f.forEach((h, i) => col?.set(goLower(goTrimSpace(h)), i));
      if (!col.has("nl")) throw new Error("answer: glossary header has no nl column");
      if (!col.has("en")) throw new Error("answer: glossary header has no en column");
      continue;
    }
    const header = col;
    const get = (name: string): string => {
      const i = header.get(name);
      return i !== undefined && i < f.length ? goLower(goTrimSpace(f[i] as string)) : "";
    };
    const e: GlossaryEntry = {
      nl: get("nl"),
      en: get("en"),
      lemmaNL: get("lemma_nl"),
      lemmaEN: get("lemma_en"),
      sep: get("sep"),
      class: get("class"),
    };
    if (e.nl !== "" && e.en !== "") out.push(e);
  }
  return out;
}

function appendUnique(list: string[], ...items: string[]): string[] {
  for (const item of items) if (!list.includes(item)) list.push(item);
  return list;
}

/** Entries as term pairs, plus the particle and class of each NL form. */
function expandGlossary(entries: readonly GlossaryEntry[]): {
  pairs: [string, string][];
  sep: Map<string, string>;
  cls: Map<string, string>;
} {
  const pairs: [string, string][] = [];
  const sep = new Map<string, string>();
  const cls = new Map<string, string>();
  const nlForms = new Map<string, string[]>();
  const enForms = new Map<string, string[]>();
  const plain = new Set<string>();
  for (const e of entries) {
    const lemmaNL = e.lemmaNL ?? "";
    const lemmaEN = e.lemmaEN ?? "";
    const esep = e.sep ?? "";
    const eclass = e.class ?? "";
    pairs.push([e.nl, e.en]);
    if (esep !== "") sep.set(e.nl, esep);
    else plain.add(e.nl);
    if (eclass !== "") cls.set(e.nl, eclass);
    if (lemmaNL === "") continue;
    nlForms.set(lemmaNL, appendUnique(nlForms.get(lemmaNL) ?? [], e.nl, lemmaNL));
    enForms.set(lemmaNL, appendUnique(enForms.get(lemmaNL) ?? [], e.en));
    if (lemmaEN !== "") enForms.set(lemmaNL, appendUnique(enForms.get(lemmaNL) ?? [], lemmaEN));
    if (eclass !== "") cls.set(lemmaNL, eclass);
  }
  for (const form of plain) sep.delete(form);
  for (const [lemma, nls] of nlForms) {
    for (const n of nls) for (const en of enForms.get(lemma) ?? []) pairs.push([n, en]);
  }
  return { pairs, sep, cls };
}

export interface SepKey {
  /** the key after the particle: "sluiten" in "afsluiten" */
  rest: string;
  trs: string[][];
}

/** A glossary indexed once; immutable, safe to share across calls. */
export interface PreparedGlossary {
  readonly index: ReadonlyMap<string, string[][]>;
  readonly sepOf: ReadonlyMap<string, string>;
  readonly classOf: ReadonlyMap<string, string>;
  readonly sepKeys: ReadonlyMap<string, SepKey[]>;
}

/** Separable particles (golang separableParticles, verify_parties.go). */
export const SEPARABLE_PARTICLES: readonly string[] = [
  "af", "aan", "op", "in", "uit", "mee", "door", "over", "terug", "vast", "toe", "voor", "bij", "na",
];

/** Index term pairs and glossary entries once. */
export function prepareGlossary(
  pairs: readonly (readonly [string, string])[] | null | undefined,
  entries: readonly GlossaryEntry[] | null | undefined,
): PreparedGlossary {
  const expanded = expandGlossary(entries ?? []);
  const all: (readonly [string, string])[] = [...(pairs ?? []), ...expanded.pairs];
  const index = glossaryIndex(all);
  const sepKeys = new Map<string, SepKey[]>();
  for (const [key, trs] of index) {
    for (const p of SEPARABLE_PARTICLES) {
      if (key.startsWith(p) && byteLen(key) > byteLen(p) + 2) {
        const list = sepKeys.get(p);
        const sk = { rest: key.slice(p.length), trs };
        if (list === undefined) sepKeys.set(p, [sk]);
        else list.push(sk);
      }
    }
  }
  return { index, sepOf: expanded.sep, classOf: expanded.cls, sepKeys };
}

// Nil-safe readers: null is the empty glossary.
export function glossEmpty(g: PreparedGlossary | null): boolean {
  return g === null || g.index.size === 0;
}
export function glossIdx(g: PreparedGlossary | null): ReadonlyMap<string, string[][]> | null {
  return g === null ? null : g.index;
}
export function glossSep(g: PreparedGlossary | null): ReadonlyMap<string, string> {
  return g === null ? EMPTY : g.sepOf;
}
export function glossClass(g: PreparedGlossary | null): ReadonlyMap<string, string> {
  return g === null ? EMPTY : g.classOf;
}
export function glossSeps(g: PreparedGlossary | null): ReadonlyMap<string, SepKey[]> {
  return g === null ? EMPTY_SEPS : g.sepKeys;
}
const EMPTY: ReadonlyMap<string, string> = new Map();
const EMPTY_SEPS: ReadonlyMap<string, SepKey[]> = new Map();

// Prepared once per distinct (glossary, entries) array pair, keyed by identity:
// a host that passes the same arrays on every call pays for the index once.
// Editing an array IN PLACE after its first use is not seen — pass a new array,
// or prefer prepareGlossary + VerifyOptions.glossaryPrepared.
const NO_PAIRS: readonly (readonly [string, string])[] = [];
const cache = new WeakMap<object, WeakMap<object, PreparedGlossary>>();
const NO_ENTRIES: readonly GlossaryEntry[] = [];

/** The options' prepared glossary. */
export function preparedFor(opts: {
  glossary?: readonly (readonly [string, string])[] | null;
  glossaryEntries?: readonly GlossaryEntry[] | null;
  glossaryPrepared?: PreparedGlossary | null;
}): PreparedGlossary {
  if (opts.glossaryPrepared !== undefined && opts.glossaryPrepared !== null) return opts.glossaryPrepared;
  const pairs = opts.glossary ?? NO_PAIRS;
  const entries = opts.glossaryEntries ?? NO_ENTRIES;
  if (pairs.length === 0 && entries.length === 0) return prepareGlossary([], []);
  let inner = cache.get(pairs);
  if (inner === undefined) {
    inner = new WeakMap();
    cache.set(pairs, inner);
  }
  let g = inner.get(entries);
  if (g === undefined) {
    g = prepareGlossary(pairs, entries);
    inner.set(entries, g);
  }
  return g;
}
