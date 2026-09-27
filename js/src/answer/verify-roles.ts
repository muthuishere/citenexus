// The role guard: WHO pays, receives or must — port of golang/answer/verify_roles.go.
//
// Actors are language-independent ids ("employee", "employer", "intern") with
// terms in any language. A fact is a number (ADR-0015 key) or a slot word; it
// binds per clause to the nearest slot word and actor within small windows.
// The guard REFUSES when no occurrence of the same slot in the unit has the
// claim's actor and at least one has a different one. Can only refuse.

import { isStopword } from "../gate/gate.js";
import { tokenizeV2 } from "../tokenize/tokenize-v2.js";
import { GS, findAllStrings, goLower, goSplit, goTrim, goTrimSpace, runeLen, trimSuffix } from "./gotext.js";
import { type VerbatimNumbers, numbersIn, verbatimIn } from "./numbers.js";
import { CONTEXT_STOP, softJoin } from "./verify-guards-model.js";
import type { EvidenceUnit } from "./verify-answer.js";

// Role slots: what the actor of a fact does with it.
export const SLOT_SOURCE = "source";
export const SLOT_RECIPIENT = "recipient";
export const SLOT_DUTY = "duty";
export const SLOT_PERMISSION = "permission";

/** What the role guard reads. All terms are lowercase single words. */
export interface ActorLexicon {
  /** actor id -> its terms, in any language */
  actors: Readonly<Record<string, readonly string[]>>;
  /** the actor the reader's own pronouns stand for; "" binds nothing */
  secondPerson: string;
  secondPersonTerms: readonly string[];
  /** fact word (a verb, or a noun like "bijdrage") -> its slot */
  slots: Readonly<Record<string, string>>;
  /** tails that make a Dutch compound an actor's share ("werkgeversbijdrage") */
  shareTails: readonly string[];
}

/** A small generic nl/en table. It names no organisation: hosts add theirs. */
export const DEFAULT_ACTOR_LEXICON: ActorLexicon = Object.freeze({
  actors: Object.freeze({
    employee: ["werknemer", "werknemers", "medewerker", "medewerkers", "employee", "employees"],
    employer: ["werkgever", "werkgevers", "employer", "employers"],
    intern: ["stagiair", "stagiairs", "stagiaire", "stagiaires", "intern", "interns"],
    agency: ["uitzendkracht", "uitzendkrachten", "agency"],
    contractor: ["inhuur", "freelancer", "freelancers", "zzp'er", "zzp'ers", "contractor", "contractors"],
    manager: ["leidinggevende", "leidinggevenden", "manager", "managers"],
  }),
  secondPerson: "employee",
  secondPersonTerms: ["je", "jij", "jou", "jouw", "u", "uw", "you", "your", "yours"],
  shareTails: ["bijdrage", "bijdragen", "deel", "aandeel", "premie"],
  slots: Object.freeze({
    betaalt: SLOT_SOURCE, betaal: SLOT_SOURCE, betalen: SLOT_SOURCE, betaald: SLOT_SOURCE,
    draagt: SLOT_SOURCE, dragen: SLOT_SOURCE, vergoedt: SLOT_SOURCE, vergoed: SLOT_SOURCE,
    vergoeden: SLOT_SOURCE, bijdrage: SLOT_SOURCE, bijdragen: SLOT_SOURCE, stort: SLOT_SOURCE,
    verstrekt: SLOT_SOURCE, biedt: SLOT_SOURCE, geeft: SLOT_SOURCE,
    pays: SLOT_SOURCE, pay: SLOT_SOURCE, paid: SLOT_SOURCE, contributes: SLOT_SOURCE,
    contribute: SLOT_SOURCE, contribution: SLOT_SOURCE, reimburses: SLOT_SOURCE,
    reimburse: SLOT_SOURCE, provides: SLOT_SOURCE, share: SLOT_SOURCE, offers: SLOT_SOURCE, bears: SLOT_SOURCE,
    ontvangt: SLOT_RECIPIENT, ontvang: SLOT_RECIPIENT, ontvangen: SLOT_RECIPIENT,
    krijgt: SLOT_RECIPIENT, krijg: SLOT_RECIPIENT, krijgen: SLOT_RECIPIENT, recht: SLOT_RECIPIENT,
    receives: SLOT_RECIPIENT, receive: SLOT_RECIPIENT, gets: SLOT_RECIPIENT, get: SLOT_RECIPIENT,
    entitled: SLOT_RECIPIENT, earns: SLOT_RECIPIENT,
    moet: SLOT_DUTY, moeten: SLOT_DUTY, verplicht: SLOT_DUTY, must: SLOT_DUTY,
    mag: SLOT_PERMISSION, mogen: SLOT_PERMISSION, may: SLOT_PERMISSION,
  }),
});

/** An empty lexicon: the role guard switched off. */
export const EMPTY_ACTOR_LEXICON: ActorLexicon = Object.freeze({
  actors: {},
  secondPerson: "",
  secondPersonTerms: [],
  slots: {},
  shareTails: [],
});

/** A copy of the lexicon with extra terms for one actor id (a new id registers
 * a new role) — golang ActorLexicon.With. */
export function withActorTerms(lexicon: ActorLexicon, id: string, ...terms: string[]): ActorLexicon {
  const actors: Record<string, string[]> = {};
  for (const [k, v] of Object.entries(lexicon.actors)) actors[k] = [...v];
  for (const t of terms) (actors[id] ??= []).push(goLower(goTrimSpace(t)));
  return { ...lexicon, actors };
}

export interface RoleWord {
  norm: string;
  actor: string;
  pronoun: boolean;
  slot: string;
  numbers: string[];
  content: boolean;
  position: number;
}

export const ROLE_TRIM = "\"'“”‘’()[]{}.,;:!?*_|€$£";

/** golang listLeadToken: `\S+` with Go's ASCII \s. */
export const LIST_LEAD_TOKEN = new RegExp(`[^${GS}]+`, "dgu");

function hasOwn(o: Readonly<Record<string, unknown>>, k: string): boolean {
  return Object.hasOwn(o, k);
}

export function classify(l: ActorLexicon, clause: string, language: string, verbatim?: VerbatimNumbers): RoleWord[] {
  const terms = new Map<string, string>();
  for (const [id, ts] of Object.entries(l.actors)) for (const t of ts) terms.set(t, id);
  const second = new Set(l.secondPersonTerms);
  const words = findAllStrings(LIST_LEAD_TOKEN, clause);
  const out: RoleWord[] = [];
  words.forEach((w, i) => {
    let norm = goLower(goTrim(w, ROLE_TRIM));
    norm = trimSuffix(trimSuffix(norm, "'s"), "’s");
    const rw: RoleWord = { norm, actor: "", pronoun: false, slot: "", numbers: [], content: false, position: i };
    for (const m of numbersIn(w, language, verbatim)) rw.numbers.push(m.reading.key);
    const id = terms.get(rw.norm);
    if (id !== undefined) {
      rw.actor = id;
    } else if (second.has(rw.norm) && l.secondPerson !== "") {
      rw.actor = l.secondPerson;
      rw.pronoun = true;
    } else {
      const [sid, ok] = share(l, rw.norm, terms);
      if (ok) {
        rw.actor = sid;
        rw.slot = SLOT_SOURCE;
      }
    }
    if (hasOwn(l.slots, rw.norm) && rw.slot === "") rw.slot = l.slots[rw.norm] as string;
    if (rw.actor === "" && rw.slot === "" && rw.numbers.length === 0 && runeLen(rw.norm) >= 4 && !isStopword(rw.norm)) {
      if (!CONTEXT_STOP.has(rw.norm)) rw.content = true;
    }
    out.push(rw);
  });
  return out;
}

/** "werkgeversdeel" as the employer's share: term + optional linking "s" + tail. */
function share(l: ActorLexicon, word: string, terms: ReadonlyMap<string, string>): [string, boolean] {
  for (const tail of l.shareTails) {
    if (!word.endsWith(tail)) continue;
    const head = word.slice(0, word.length - tail.length);
    if (head === "") continue;
    const id = terms.get(head);
    if (id !== undefined) return [id, true];
    if (head.endsWith("s")) {
      const id2 = terms.get(head.slice(0, -1));
      if (id2 !== undefined) return [id2, true];
    }
  }
  return ["", false];
}

const ROLE_NUMBER_WINDOW = 5;
const ROLE_ACTOR_WINDOW = 4;

const NON_SUBJECT: ReadonlySet<string> = new Set([
  "van", "voor", "aan", "bij", "met", "namens", "binnen", "in",
  "onder", "from", "for", "to", "with", "of", "on", "within",
  "at", "among",
]);

function nearest(ws: readonly RoleWord[], i: number, max: number, ok: (j: number) => boolean): number {
  for (let d = 0; d <= max && d < ws.length; d++) {
    let j = i - d;
    if (j >= 0 && ok(j)) return j;
    j = i + d;
    if (j < ws.length && ok(j)) return j;
  }
  return -1;
}

/** The (slot, actor, pronoun, ok) the fact at index i binds to. */
function binding(ws: readonly RoleWord[], i: number): [string, string, boolean, boolean] {
  const w = ws[i] as RoleWord;
  let s = i;
  if (w.slot === "") s = nearest(ws, i, ROLE_NUMBER_WINDOW, (j) => (ws[j] as RoleWord).slot !== "");
  if (s < 0) {
    if (w.numbers.length === 0 || nearest(ws, i, ws.length, (j) => (ws[j] as RoleWord).slot !== "") >= 0) {
      return ["", "", false, false];
    }
    const a = nearest(ws, i, ROLE_NUMBER_WINDOW, (j) => (ws[j] as RoleWord).actor !== "");
    if (a < 0) return ["", "", false, false];
    return ["", (ws[a] as RoleWord).actor, (ws[a] as RoleWord).pronoun, true];
  }
  const sw = ws[s] as RoleWord;
  if (sw.actor !== "") return [sw.slot, sw.actor, sw.pronoun, true];
  const a = nearest(ws, s, ROLE_ACTOR_WINDOW, (j) => {
    const wj = ws[j] as RoleWord;
    if (wj.actor === "") return false;
    if (j > 0 && !wj.pronoun) {
      if (NON_SUBJECT.has((ws[j - 1] as RoleWord).norm)) return false;
      if (j > 1 && isArticle((ws[j - 1] as RoleWord).norm) && NON_SUBJECT.has((ws[j - 2] as RoleWord).norm)) return false;
    }
    return true;
  });
  if (a < 0) return ["", "", false, false];
  return [sw.slot, (ws[a] as RoleWord).actor, (ws[a] as RoleWord).pronoun, true];
}

export function isArticle(w: string): boolean {
  switch (w) {
    case "de":
    case "het":
    case "een":
    case "the":
    case "a":
    case "an":
    case "je":
    case "jouw":
    case "your":
    case "uw":
      return true;
  }
  return false;
}

/** clauseBreak without the colon: a label binds to its value. */
const ROLE_BREAK = new RegExp(`[.!?;]+([${GS}]|$)|,[${GS}]|[${GS}]*[\\u2014\\u2013][${GS}]*|[${GS}]-[${GS}]|\\n`, "dgu");

export function roleClauses(text: string): string[] {
  return goSplit(ROLE_BREAK, softJoin(text));
}

/** A claim whose fact the unit states for a different actor. */
export function roleGuard(claim: string, claimLanguage: string, eu: EvidenceUnit, lexicon: ActorLexicon): string {
  if (Object.keys(lexicon.actors).length === 0 && lexicon.secondPerson === "") return "";
  const unit = roleClauses(eu.text).map((c) => classify(lexicon, c, eu.language));
  for (const c of roleClauses(claim)) {
    const ws = classify(lexicon, c, claimLanguage, verbatimIn(eu.text, eu.language));
    const content = new Set<string>();
    for (const w of ws) if (w.content) for (const tok of tokenizeV2(w.norm)) content.add(tok);
    for (let i = 0; i < ws.length; i++) {
      const w = ws[i] as RoleWord;
      let match: (u: RoleWord) => boolean;
      if (w.numbers.length > 0) {
        const keys = w.numbers;
        match = (u) => keys.some((k) => u.numbers.includes(k));
      } else if (w.slot !== "" && !hasNumber(ws)) {
        const slot = w.slot;
        match = (u) => u.slot === slot;
      } else {
        continue;
      }
      const [slot, actor, pronoun, ok] = binding(ws, i);
      if (!ok) continue;
      if (w.numbers.length === 0 && pronoun) continue;
      let agrees = false;
      let other = "";
      for (const uc of unit) {
        if (w.numbers.length === 0 && !sharesContent(uc, content)) continue;
        for (let j = 0; j < uc.length; j++) {
          if (!match(uc[j] as RoleWord)) continue;
          const [us, ua, , uok] = binding(uc, j);
          if (!uok || us !== slot) continue;
          if (ua === actor) agrees = true;
          else if (other === "") other = ua;
        }
      }
      if (!agrees && other !== "") return `role guard: ${actor} where the passage says ${other}`;
    }
  }
  return "";
}

function hasNumber(ws: readonly RoleWord[]): boolean {
  return ws.some((w) => w.numbers.length > 0);
}

/** The unit clause holds at least half of the claim clause's content words, and two. */
function sharesContent(ws: readonly RoleWord[], content: ReadonlySet<string>): boolean {
  const have = new Set<string>();
  for (const w of ws) if (w.content) for (const tok of tokenizeV2(w.norm)) have.add(tok);
  let shared = 0;
  for (const tok of content) if (have.has(tok)) shared++;
  return shared >= 2 && 2 * shared >= content.size;
}
