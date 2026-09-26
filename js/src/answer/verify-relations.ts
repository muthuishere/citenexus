// Direction of a transfer: WHO informs, pays or gives WHOM — port of
// golang/answer/verify_relations.go. Refused when a unit clause of the same
// class has the two parties the other way round and none has them the claim's
// way. Unresolved means no verdict. Can only refuse.

import { primaryLanguage } from "./verify-answer.js";
import type { EvidenceUnit } from "./verify-answer.js";
import { classify, isArticle, roleClauses } from "./verify-roles.js";
import type { ActorLexicon, RoleWord } from "./verify-roles.js";

const RELATION_VERBS: ReadonlyMap<string, string> = new Map([
  ["deelt", "inform"], ["delen", "inform"], ["meedelen", "inform"], ["mededelen", "inform"], ["informeert", "inform"],
  ["informeren", "inform"], ["informeer", "inform"], ["meldt", "inform"], ["melden", "inform"],
  ["inform", "inform"], ["informs", "inform"], ["informed", "inform"], ["notify", "inform"], ["notifies", "inform"],
  ["notified", "inform"], ["tell", "inform"], ["tells", "inform"], ["told", "inform"],
  ["betaalt", "pay"], ["betalen", "pay"], ["uitkeren", "pay"], ["keert", "pay"], ["pay", "pay"], ["pays", "pay"], ["paid", "pay"],
  ["verstrekt", "give"], ["verstrekken", "give"], ["overhandigt", "give"], ["overhandigen", "give"],
  ["provide", "give"], ["provides", "give"], ["provided", "give"], ["give", "give"], ["gives", "give"], ["gave", "give"],
]);

const RECIPIENT_MARKERS: ReadonlySet<string> = new Set(["aan", "bij", "to"]);

interface Direction {
  cls: string;
  sender: string;
  recipient: string;
}

/** The resolved transfers of a text, one per clause at most. */
function directionsIn(text: string, language: string, lexicon: ActorLexicon): Direction[] {
  const english = primaryLanguage(language) === "en";
  const out: Direction[] = [];
  for (const clause of roleClauses(text)) {
    const ws = classify(lexicon, clause, language);
    let verb = -1;
    let cls = "";
    for (let i = 0; i < ws.length; i++) {
      const c = RELATION_VERBS.get((ws[i] as RoleWord).norm);
      if (c !== undefined) {
        if (verb >= 0 && c !== cls) {
          verb = -2; // two different transfers: unresolved
          break;
        }
        verb = i;
        cls = c;
      }
    }
    if (verb < 0) continue;
    const ms: { at: number; id: string; markedRecip: boolean }[] = [];
    // insertion-ordered like the Go map is not; only its SIZE and membership are read
    const ids = new Set<string>();
    for (let i = 0; i < ws.length; i++) {
      const w = ws[i] as RoleWord;
      if (w.actor === "" || w.pronoun) continue;
      let marked = false;
      for (let k = i - 1; k >= 0 && k >= i - 2; k--) {
        const nk = (ws[k] as RoleWord).norm;
        if (RECIPIENT_MARKERS.has(nk)) {
          marked = true;
          break;
        }
        if (!isArticle(nk)) break;
      }
      ms.push({ at: i, id: w.actor, markedRecip: marked });
      ids.add(w.actor);
    }
    if (ids.size !== 2) continue;
    let recipient = "";
    let sender = "";
    for (const m of ms) if (m.markedRecip) recipient = m.id;
    if (recipient === "" && english) {
      for (const m of ms) {
        if (m.at > verb) {
          recipient = m.id;
          break;
        }
      }
    }
    if (recipient === "") {
      for (const m of ms) if (m.at < verb) sender = m.id;
      if (sender === "") sender = (ms[0] as { id: string }).id;
      for (const id of ids) if (id !== sender) recipient = id;
    } else {
      for (const id of ids) if (id !== recipient) sender = id;
    }
    if (sender === "" || recipient === "" || sender === recipient) continue;
    out.push({ cls, sender, recipient });
  }
  return out;
}

/** relationGuard: see the file comment. */
export function relationGuard(claim: string, claimLanguage: string, eu: EvidenceUnit, lexicon: ActorLexicon): string {
  const unit = directionsIn(eu.text, eu.language, lexicon);
  if (unit.length === 0) return "";
  for (const c of directionsIn(claim, claimLanguage, lexicon)) {
    let agrees = false;
    let swapped = false;
    for (const u of unit) {
      if (u.cls !== c.cls) continue;
      if (u.sender === c.sender && u.recipient === c.recipient) agrees = true;
      if (u.sender === c.recipient && u.recipient === c.sender) swapped = true;
    }
    if (swapped && !agrees) {
      return `role guard: ${c.sender} ${c.cls}s ${c.recipient} where the passage says ${c.recipient} ${c.cls}s ${c.sender}`;
    }
  }
  return "";
}
