// Go string and regexp semantics, spelled out for the VerifyAnswer port.
//
// verify-answer.ts and its guards are a byte-for-byte BEHAVIOURAL port of
// golang/answer/verify_*.go. Go and JS disagree on enough primitives that
// copying the Go text literally would silently change verdicts, so every
// divergence the port depends on is resolved once, here:
//
//   - `\s` in Go's RE2 is ASCII [\t\n\f\r ] only; JS's `\s` adds \v, U+00A0,
//     U+202F and the other Unicode spaces. Patterns use GS / GNS below instead.
//   - `\b` is ASCII-word in both (JS without the `iu` combination), so it is
//     kept as written.
//   - `strings.ToLower` maps each rune by SIMPLE case mapping; JS's
//     `toLowerCase` applies final-sigma context and U+0130 -> "i̇" (two code
//     points). `goLower` reproduces Go.
//   - `strings.Fields` / `strings.TrimSpace` split on `unicode.IsSpace`, which
//     includes U+0085 and excludes U+FEFF — neither JS `\s` nor `trim()`.
//   - `regexp.Split` never inserts capture groups (JS's `split` does) and keeps
//     Go's trailing-piece rule.
//   - `len(s)` is a UTF-8 BYTE count; `sort.Strings` and `<` compare bytes,
//     which is code-point order, not JS's UTF-16 order.
//   - `%q` is `strconv.Quote`; `%.3f` rounds the exact binary value half-even.
//   - `math/big.Rat` is exact; `Rat` below is its bigint twin, with Go's
//     `FloatString` rounding.

/** Go RE2's `\s`: ASCII [\t\n\f\r ] only. For use INSIDE a character class. */
export const GS = "\\t\\n\\f\\r ";

/** Go's `unicode.IsSpace`. */
export function isGoSpace(ch: string): boolean {
  switch (ch) {
    case "\t":
    case "\n":
    case "\v":
    case "\f":
    case "\r":
    case " ":
    case "\u0085":
    case " ":
    case " ":
    case " ":
    case " ":
    case " ":
    case " ":
    case "　":
      return true;
  }
  const cp = ch.codePointAt(0) ?? 0;
  return cp >= 0x2000 && cp <= 0x200a;
}

const ASCII_ONLY = /^[\x00-\x7f]*$/;

/** Go's `strings.ToLower`: per-rune simple lowercase mapping. */
export function goLower(s: string): string {
  if (ASCII_ONLY.test(s)) return s.toLowerCase();
  let out = "";
  for (const ch of s) {
    if (ch === "İ") out += "i";
    else if (ch === "Σ") out += "σ";
    else out += ch.toLowerCase();
  }
  return out;
}

/** Go's `unicode.ToLower` on one rune. */
export function goLowerRune(ch: string): string {
  return goLower(ch);
}

const UPPER = /^\p{Lu}$/u;
const LETTER = /^\p{L}$/u;
const DIGIT = /^\p{Nd}$/u;

/** Go's `unicode.IsUpper` (category Lu). */
export function isUpperRune(ch: string | undefined): boolean {
  return ch !== undefined && UPPER.test(ch);
}
/** Go's `unicode.IsLetter` (category L). */
export function isLetterRune(ch: string | undefined): boolean {
  return ch !== undefined && LETTER.test(ch);
}
/** Go's `unicode.IsDigit` (category Nd). */
export function isDigitRune(ch: string | undefined): boolean {
  return ch !== undefined && DIGIT.test(ch);
}

/** The runes (code points) of s. */
export function runes(s: string): string[] {
  return Array.from(s);
}

/** Go's `len([]rune(s))`. */
export function runeLen(s: string): number {
  let n = 0;
  for (const _ of s) n++;
  return n;
}

/** Go's `len(s)`: the UTF-8 byte length. */
export function byteLen(s: string): number {
  let n = 0;
  for (const ch of s) {
    const cp = ch.codePointAt(0) ?? 0;
    n += cp < 0x80 ? 1 : cp < 0x800 ? 2 : cp < 0x10000 ? 3 : 4;
  }
  return n;
}

/** Go's `strings.Trim(s, cutset)`. */
export function goTrim(s: string, cutset: string): string {
  return goTrimRight(goTrimLeft(s, cutset), cutset);
}
/** Go's `strings.TrimLeft(s, cutset)`. */
export function goTrimLeft(s: string, cutset: string): string {
  const cut = new Set(Array.from(cutset));
  const rs = Array.from(s);
  let i = 0;
  while (i < rs.length && cut.has(rs[i] as string)) i++;
  return rs.slice(i).join("");
}
/** Go's `strings.TrimRight(s, cutset)`. */
export function goTrimRight(s: string, cutset: string): string {
  const cut = new Set(Array.from(cutset));
  const rs = Array.from(s);
  let j = rs.length;
  while (j > 0 && cut.has(rs[j - 1] as string)) j--;
  return rs.slice(0, j).join("");
}
/** Go's `strings.TrimSpace`. */
export function goTrimSpace(s: string): string {
  const rs = Array.from(s);
  let i = 0;
  let j = rs.length;
  while (i < j && isGoSpace(rs[i] as string)) i++;
  while (j > i && isGoSpace(rs[j - 1] as string)) j--;
  return rs.slice(i, j).join("");
}

/** Go's `strings.Fields`. */
export function goFields(s: string): string[] {
  const out: string[] = [];
  let cur = "";
  for (const ch of s) {
    if (isGoSpace(ch)) {
      if (cur !== "") out.push(cur);
      cur = "";
    } else {
      cur += ch;
    }
  }
  if (cur !== "") out.push(cur);
  return out;
}

/** Go's `strings.ContainsAny(s, chars)`. */
export function containsAny(s: string, chars: string): boolean {
  for (const ch of chars) if (s.includes(ch)) return true;
  return false;
}

/** Go's `strings.IndexAny(s, chars) == 0`: s starts with one of chars. */
export function startsWithAny(s: string, chars: string): boolean {
  const first = s.codePointAt(0);
  if (first === undefined) return false;
  return chars.includes(String.fromCodePoint(first));
}

/** Go's `strings.TrimSuffix`. */
export function trimSuffix(s: string, suffix: string): string {
  return suffix !== "" && s.endsWith(suffix) ? s.slice(0, s.length - suffix.length) : s;
}
/** Go's `strings.TrimPrefix`. */
export function trimPrefix(s: string, prefix: string): string {
  return prefix !== "" && s.startsWith(prefix) ? s.slice(prefix.length) : s;
}

/** One regexp match: its [start, end) and each group's [start, end) or null. */
export interface GoMatch {
  start: number;
  end: number;
  groups: (readonly [number, number] | null)[];
  text: string;
  /** group text, or undefined when the group did not participate */
  group(i: number): string | undefined;
}

/**
 * Go's `FindAllStringSubmatchIndex(s, -1)`. `re` MUST carry the `g` and `d`
 * flags. Go's empty-match rule is kept: an empty match directly after the
 * previous match is skipped.
 */
export function findAll(re: RegExp, s: string): GoMatch[] {
  if (!re.global || !re.hasIndices) throw new Error(`findAll needs the g and d flags: ${re.source}`);
  re.lastIndex = 0;
  const out: GoMatch[] = [];
  let prevEnd = -1;
  for (;;) {
    const m = re.exec(s);
    if (m === null) break;
    const start = m.index;
    const end = start + m[0].length;
    if (m[0].length === 0) {
      // advance by one code point, as Go does by one rune
      const cp = s.codePointAt(end);
      re.lastIndex = end + (cp !== undefined && cp > 0xffff ? 2 : 1);
      if (start === prevEnd) continue;
    }
    const indices = m.indices ?? [];
    const groups: (readonly [number, number] | null)[] = [];
    for (let i = 1; i < m.length; i++) {
      const g = indices[i];
      groups.push(g === undefined ? null : [g[0], g[1]]);
    }
    const text = m[0];
    out.push({
      start,
      end,
      groups,
      text,
      group(i: number): string | undefined {
        const g = groups[i - 1];
        return g === null || g === undefined ? undefined : s.slice(g[0], g[1]);
      },
    });
    prevEnd = end;
    if (end > s.length) break;
  }
  re.lastIndex = 0;
  return out;
}

/** Go's `FindStringIndex`: the first match, or null. */
export function findFirst(re: RegExp, s: string): GoMatch | null {
  return findAll(re, s)[0] ?? null;
}

/** Go's `re.MatchString(s)` for a `gd` pattern. */
export function matches(re: RegExp, s: string): boolean {
  re.lastIndex = 0;
  const ok = re.test(s);
  re.lastIndex = 0;
  return ok;
}

/** Go's `re.Split(s, -1)` — no capture groups in the output. */
export function goSplit(re: RegExp, s: string): string[] {
  if (s === "") return [""];
  const out: string[] = [];
  let beg = 0;
  let end = 0;
  for (const m of findAll(re, s)) {
    end = m.start;
    if (m.end !== 0) out.push(s.slice(beg, end));
    beg = m.end;
  }
  if (end !== s.length) out.push(s.slice(beg));
  return out;
}

/** Go's `re.FindAllString(s, -1)`. */
export function findAllStrings(re: RegExp, s: string): string[] {
  return findAll(re, s).map((m) => m.text);
}

/** Go's `re.ReplaceAllString(s, repl)` where repl uses only `$n` groups. */
export function replaceAll(re: RegExp, s: string, repl: string): string {
  let out = "";
  let last = 0;
  for (const m of findAll(re, s)) {
    out += s.slice(last, m.start);
    out += repl.replace(/\$(\d)/g, (_, d: string) => m.group(Number(d)) ?? "");
    last = m.end;
  }
  return out + s.slice(last);
}

/** Go's string `<`: code-point (UTF-8 byte) order. */
export function cmpGo(a: string, b: string): number {
  if (a === b) return 0;
  const ra = Array.from(a);
  const rb = Array.from(b);
  const n = Math.min(ra.length, rb.length);
  for (let i = 0; i < n; i++) {
    const x = (ra[i] as string).codePointAt(0) as number;
    const y = (rb[i] as string).codePointAt(0) as number;
    if (x !== y) return x < y ? -1 : 1;
  }
  return ra.length < rb.length ? -1 : ra.length > rb.length ? 1 : 0;
}

/** Go's `sort.Strings` (returns a sorted copy). */
export function sortedGo(xs: Iterable<string>): string[] {
  return [...xs].sort(cmpGo);
}

const PRINTABLE = /^[\p{L}\p{M}\p{N}\p{P}\p{S}]$/u;

/** Go's `strconv.Quote` (`%q` of a string). */
export function goQuote(s: string): string {
  let out = '"';
  for (const ch of s) {
    const cp = ch.codePointAt(0) as number;
    if (ch === '"' || ch === "\\") {
      out += "\\" + ch;
    } else if (ch === " " || PRINTABLE.test(ch)) {
      out += ch;
    } else {
      switch (ch) {
        case "\x07":
          out += "\\a";
          break;
        case "\b":
          out += "\\b";
          break;
        case "\f":
          out += "\\f";
          break;
        case "\n":
          out += "\\n";
          break;
        case "\r":
          out += "\\r";
          break;
        case "\t":
          out += "\\t";
          break;
        case "\v":
          out += "\\v";
          break;
        default:
          if (cp < 0x20 || cp === 0x7f) out += "\\x" + cp.toString(16).padStart(2, "0");
          else if (cp < 0x10000) out += "\\u" + cp.toString(16).padStart(4, "0");
          else out += "\\U" + cp.toString(16).padStart(8, "0");
      }
    }
  }
  return out + '"';
}

/** Go's `fmt.Sprintf("%.3f", x)`: the exact binary value, rounded half-even. */
export function fmt3(x: number): string {
  const fixed = x.toFixed(3); // rounds the exact value; an exact tie goes up
  const scaled = x * 1000;
  if (Number.isFinite(scaled) && Math.abs(scaled - Math.trunc(scaled)) === 0.5) {
    // an exact binary tie: Go rounds half to even
    const lo = Math.trunc(scaled);
    const even = lo % 2 === 0 ? lo : lo + Math.sign(scaled);
    return (even / 1000).toFixed(3);
  }
  return fixed;
}

/** Go's `fmt.Sprintf("%02d", n)`. */
export function pad2(n: number): string {
  return n < 10 && n >= 0 ? "0" + String(n) : String(n);
}

// ─── math/big.Rat ────────────────────────────────────────────────────────────

function gcd(a: bigint, b: bigint): bigint {
  a = a < 0n ? -a : a;
  b = b < 0n ? -b : b;
  while (b !== 0n) [a, b] = [b, a % b];
  return a;
}

/** An exact rational, normalised (den > 0, lowest terms). */
export class Rat {
  readonly num: bigint;
  readonly den: bigint;
  constructor(num: bigint, den: bigint = 1n) {
    if (den === 0n) throw new Error("Rat: zero denominator");
    if (den < 0n) {
      num = -num;
      den = -den;
    }
    const g = gcd(num, den);
    this.num = g === 0n ? 0n : num / g;
    this.den = g === 0n ? 1n : den / g;
  }

  /** `big.Rat.SetString` for the decimal keys this package produces
   * ("25", "0.5", "-3.25"); null where Go's SetString fails. */
  static parse(s: string): Rat | null {
    const m = /^([+-]?)([0-9]+)(?:\.([0-9]*))?$/.exec(s) ?? /^([+-]?)()\.([0-9]+)$/.exec(s);
    if (m === null) return null;
    const whole = m[2] === "" ? "0" : (m[2] as string);
    const frac = m[3] ?? "";
    const num = BigInt(whole + frac) * (m[1] === "-" ? -1n : 1n);
    return new Rat(num, 10n ** BigInt(frac.length));
  }

  static fromDecimal(v: { units: bigint; scale: number }): Rat {
    return new Rat(v.units, 10n ** BigInt(v.scale));
  }

  mul(o: Rat): Rat {
    return new Rat(this.num * o.num, this.den * o.den);
  }
  quo(o: Rat): Rat {
    return new Rat(this.num * o.den, this.den * o.num);
  }
  isInt(): boolean {
    return this.den === 1n;
  }
  /** `big.Rat.FloatString(prec)`: halves rounded away from zero. */
  floatString(prec: number): string {
    const neg = this.num < 0n;
    const a = neg ? -this.num : this.num;
    const scale = 10n ** BigInt(prec);
    let q = (a * scale) / this.den;
    const r = (a * scale) % this.den;
    if (2n * r >= this.den) q += 1n;
    let digits = q.toString();
    if (prec > 0) {
      digits = digits.padStart(prec + 1, "0");
      digits = digits.slice(0, -prec) + "." + digits.slice(-prec);
    }
    return (neg && q !== 0n ? "-" : "") + digits;
  }
}

/** golang's ratKey: an integer as itself, else 6 decimals with trailing zeros cut. */
export function ratKey(r: Rat): string {
  if (r.isInt()) return r.num.toString();
  const s = r.floatString(6);
  return goTrimRight(goTrimRight(s, "0"), ".");
}
