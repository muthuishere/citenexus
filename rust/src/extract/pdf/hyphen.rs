//! Line-end hyphen resolution (ADR-0017 decision 1; research §3, §8 #2).
//!
//! pdfium marks a line-end `-`/U+00AD with U+0002 and suppresses the line
//! break (`cpdf_textpage.cpp`, `ProcessGenerateCharacter`). The layout layer
//! keeps that marker at the end of its line; this module decides, per marker,
//! whether the printed hyphen was a soft break (join) or part of the word
//! (keep). Order of evidence:
//!
//! 1. The next word is a coordinating conjunction ("in- en verkoop",
//!    "pre- and post-war"): keep the hyphen AND the space.
//! 2. The next word starts upper-case or with a digit ("Noord-Holland",
//!    "COVID-19"): keep the hyphen.
//! 3. **Document witnesses.** The same document prints the hyphenated form
//!    unbroken ("e-mail" elsewhere) → keep; prints the joined form
//!    ("regulation" elsewhere) → join. Both → the more frequent; a tie keeps.
//! 4. A per-language keep-list: one-letter prefixes ("e-mail", "x-ray"),
//!    known lexical compounds ("long-term"), and — for Dutch — a vowel
//!    collision (klinkerbotsing: "zee-egel", "auto-ongeluk").
//! 5. Otherwise join (a pdfium marker is a soft break far more often than
//!    not). A literal `-` that pdfium did NOT mark is only joined on a
//!    joined-form witness.
//!
//! Idea ported (not copied) from Xberg `collect_hyphen_witnesses` /
//! `should_preserve_lexical_hyphen` (`pdf/structure/pipeline.rs:5635-5891`
//! @ `b4331e0`, MIT) and datalab pdftext `handle_hyphens` (Apache-2.0). See
//! `rust/NOTICE`.

use std::collections::BTreeMap;

use super::layout::HYPHEN_MARK;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Decision {
    /// "regu-" + "lation" → "regulation"
    Join,
    /// "e-" + "mail" → "e-mail"
    Keep,
    /// "in-" + "en verkoop" → "in- en verkoop"
    KeepSpaced,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Lang {
    En,
    Nl,
    /// Unknown: the union of every list (conservative: more keeps).
    Any,
}

impl Lang {
    pub fn parse(code: Option<&str>) -> Lang {
        match code.map(|c| c.trim().to_ascii_lowercase()) {
            Some(c) if c == "en" || c.starts_with("en-") || c.starts_with("en_") => Lang::En,
            Some(c) if c == "nl" || c.starts_with("nl-") || c.starts_with("nl_") => Lang::Nl,
            _ => Lang::Any,
        }
    }
}

const CONJ_EN: &[&str] = &["and", "or", "nor", "to", "as", "&"];
const CONJ_NL: &[&str] = &["en", "of", "tot", "noch", "t/m", "&"];

const KEEP_EN: &[&str] = &[
    "long-term",
    "short-term",
    "mid-term",
    "well-known",
    "well-being",
    "full-time",
    "part-time",
    "follow-up",
    "check-in",
    "check-out",
    "log-in",
    "opt-in",
    "opt-out",
    "up-to-date",
    "day-to-day",
    "one-off",
    "decision-making",
    "third-party",
    "self-employed",
    "non-compete",
    "co-worker",
    "pre-employment",
    "post-employment",
    "cross-border",
    "on-call",
    "stand-by",
    "year-end",
    "sign-off",
];
const KEEP_NL: &[&str] = &[
    "stand-by",
    "check-in",
    "follow-up",
    "part-time",
    "full-time",
    "co-ouderschap",
    "ex-werknemer",
    "ex-werkgever",
    "oud-medewerker",
    "niet-werkzaam",
    "all-in",
    "opt-out",
    "opt-in",
    "on-call",
    "up-to-date",
];

/// Dutch vowel pairs that the spelling separates with a hyphen in compounds.
const NL_COLLISIONS: &[&str] = &[
    "aa", "ae", "ai", "au", "ee", "ei", "eu", "ie", "ii", "oe", "oi", "oo", "ou", "ui", "uu",
];

/// Lower-cased word counts over the whole document, the witness base.
#[derive(Debug, Default, Clone)]
pub struct Witnesses {
    counts: BTreeMap<String, usize>,
}

fn clean_word(w: &str) -> String {
    w.trim_matches(|c: char| !c.is_alphanumeric() && c != '-')
        .trim_matches('-')
        .to_lowercase()
}

impl Witnesses {
    /// Count every whitespace token in `texts`, skipping tokens that touch a
    /// hyphen marker or end a line with `-` (they are the fragments under
    /// decision, not evidence).
    pub fn collect<'a>(lines: impl Iterator<Item = &'a str>) -> Self {
        let mut counts = BTreeMap::new();
        for line in lines {
            let toks: Vec<&str> = line.split_whitespace().collect();
            let n = toks.len();
            for (k, t) in toks.iter().enumerate() {
                if t.contains(HYPHEN_MARK) || (k + 1 == n && t.ends_with('-')) {
                    continue;
                }
                // The first token of a line may be the tail of a broken word.
                let w = clean_word(t);
                if w.is_empty() {
                    continue;
                }
                *counts.entry(w).or_insert(0) += 1;
            }
        }
        Witnesses { counts }
    }

    fn get(&self, w: &str) -> usize {
        self.counts.get(w).copied().unwrap_or(0)
    }
}

/// The alphabetic tail of `left` (the fragment before the hyphen) and the
/// head of `right` (the word after the break), lower-cased, for lookups.
fn stem_left(left: &str) -> String {
    let w = left.rsplit(char::is_whitespace).next().unwrap_or("");
    w.trim_start_matches(|c: char| !c.is_alphanumeric())
        .to_lowercase()
}

fn stem_right(right: &str) -> String {
    let w = right.split(char::is_whitespace).next().unwrap_or("");
    w.trim_end_matches(|c: char| !c.is_alphanumeric())
        .to_lowercase()
}

/// Decide one break. `left` is the text before the hyphen on its line, `right`
/// the text of the next line; `marked` is true for a pdfium U+0002 marker.
pub fn decide(left: &str, right: &str, lang: Lang, wit: &Witnesses, marked: bool) -> Decision {
    let first = right.split_whitespace().next().unwrap_or("");
    let first_lc = first.to_lowercase();
    let conj = |list: &[&str]| list.contains(&first_lc.as_str());
    let is_conj = match lang {
        Lang::En => conj(CONJ_EN),
        Lang::Nl => conj(CONJ_NL),
        Lang::Any => conj(CONJ_EN) || conj(CONJ_NL),
    };
    if is_conj {
        return Decision::KeepSpaced;
    }
    let Some(r0) = first.chars().next() else {
        return Decision::Keep;
    };
    if r0.is_uppercase() || r0.is_ascii_digit() {
        return Decision::Keep;
    }
    let l = stem_left(left);
    let r = stem_right(right);
    if l.is_empty() || r.is_empty() || !l.chars().last().is_some_and(|c| c.is_alphabetic()) {
        return Decision::Keep;
    }
    // "long-term" split as "long-" / "term": the hyphenated whole is `l-r`.
    let hyph = format!("{l}-{r}");
    let joined = format!("{l}{r}");
    let (h, j) = (wit.get(&hyph), wit.get(&joined));
    if h > 0 || j > 0 {
        return if j > h {
            Decision::Join
        } else {
            Decision::Keep
        };
    }
    if !marked {
        return Decision::Keep;
    }
    // Keep-lists: compare on the last hyphen-free piece of the left fragment.
    let l_last = l.rsplit('-').next().unwrap_or(&l);
    let whole = format!("{l_last}-{r}");
    // Both lists are always consulted: keeping a real compound is never
    // wrong, and documents mix languages (English terms in Dutch policies).
    let in_list = KEEP_EN.contains(&whole.as_str()) || KEEP_NL.contains(&whole.as_str());
    if in_list || l_last.chars().count() == 1 {
        return Decision::Keep;
    }
    if lang == Lang::Nl {
        let pair: String = l_last
            .chars()
            .last()
            .into_iter()
            .chain(r.chars().next())
            .collect();
        if NL_COLLISIONS.contains(&pair.as_str()) {
            return Decision::Keep;
        }
    }
    Decision::Join
}

/// How a line ends, for joining.
pub enum LineEnd {
    /// pdfium's U+0002 marker.
    Marker,
    /// A printed `-` pdfium did not mark.
    Literal,
    None,
}

pub fn line_end(line: &str) -> LineEnd {
    let t = line.trim_end();
    if t.ends_with(HYPHEN_MARK) {
        LineEnd::Marker
    } else if t.ends_with('-') && t.chars().rev().nth(1).is_some_and(|c| c.is_alphabetic()) {
        LineEnd::Literal
    } else {
        LineEnd::None
    }
}

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct HyphenStats {
    pub markers: usize,
    pub joined: usize,
    pub kept: usize,
}

/// Join `lines` (top to bottom, one block) into one string, resolving every
/// line-end hyphen. Returns the text and whether any hyphen was joined. Any
/// marker not at a line end prints as the `-` it stands for, so no U+0002
/// ever leaves this function.
pub fn join_lines(
    lines: &[String],
    lang: Lang,
    wit: &Witnesses,
    stats: &mut HyphenStats,
) -> (String, bool) {
    let mut out = String::new();
    let mut joined_any = false;
    for (k, line) in lines.iter().enumerate() {
        let mut cur = line.trim().to_string();
        if k + 1 < lines.len() {
            let next = lines[k + 1].trim();
            match line_end(&cur) {
                LineEnd::Marker | LineEnd::Literal => {
                    let marked = matches!(line_end(&cur), LineEnd::Marker);
                    if marked {
                        stats.markers += 1;
                    }
                    cur.pop(); // the marker or the literal '-'
                    let d = decide(&cur, next, lang, wit, marked);
                    match d {
                        Decision::Join => {
                            joined_any = true;
                            if marked {
                                stats.joined += 1;
                            }
                            out.push_str(&cur.replace(HYPHEN_MARK, "-"));
                            continue; // no separator
                        }
                        Decision::Keep => {
                            if marked {
                                stats.kept += 1;
                            }
                            out.push_str(&cur.replace(HYPHEN_MARK, "-"));
                            out.push('-');
                            continue;
                        }
                        Decision::KeepSpaced => {
                            if marked {
                                stats.kept += 1;
                            }
                            cur.push('-');
                        }
                    }
                }
                LineEnd::None => {}
            }
            out.push_str(&cur.replace(HYPHEN_MARK, "-"));
            out.push(' ');
        } else {
            if matches!(line_end(&cur), LineEnd::Marker) {
                // A trailing marker is resolved across blocks by the caller;
                // leave it for them.
                let body: String =
                    cur[..cur.len() - HYPHEN_MARK.len_utf8()].replace(HYPHEN_MARK, "-");
                out.push_str(&body);
                out.push(HYPHEN_MARK);
            } else {
                out.push_str(&cur.replace(HYPHEN_MARK, "-"));
            }
        }
    }
    (out, joined_any)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn w(text: &str) -> Witnesses {
        Witnesses::collect(text.lines())
    }

    #[test]
    fn coordinated_compound_keeps_hyphen_and_space() {
        assert_eq!(
            decide("de in", "en verkoop", Lang::Nl, &w(""), true),
            Decision::KeepSpaced
        );
        assert_eq!(
            decide("pre", "and post-war", Lang::En, &w(""), true),
            Decision::KeepSpaced
        );
    }

    #[test]
    fn real_compounds_never_merge() {
        assert_eq!(
            decide("per e", "mail", Lang::En, &w(""), true),
            Decision::Keep
        );
        assert_eq!(
            decide("a long", "term plan", Lang::En, &w(""), true),
            Decision::Keep
        );
        assert_eq!(
            decide("Noord", "Holland", Lang::Nl, &w(""), true),
            Decision::Keep
        );
    }

    #[test]
    fn witness_decides() {
        let wit = w("the regulation applies\nsend an e-mail\nwerk-nemer");
        assert_eq!(
            decide("the regu", "lation", Lang::En, &wit, true),
            Decision::Join
        );
        assert_eq!(
            decide("per e", "mail", Lang::En, &wit, true),
            Decision::Keep
        );
        // no witness, no list: a pdfium marker joins
        assert_eq!(
            decide("every", "one", Lang::En, &w(""), true),
            Decision::Join
        );
        // a literal unmarked '-' is kept without a joined witness
        assert_eq!(
            decide("every", "one", Lang::En, &w(""), false),
            Decision::Keep
        );
    }

    #[test]
    fn dutch_vowel_collision_keeps() {
        assert_eq!(
            decide("de zee", "egel", Lang::Nl, &w(""), true),
            Decision::Keep
        );
        assert_eq!(
            decide("de verko", "per", Lang::Nl, &w(""), true),
            Decision::Join
        );
    }

    #[test]
    fn join_lines_never_leaks_a_marker() {
        let mut st = HyphenStats::default();
        let lines = vec![
            "the regu\u{2}".to_string(),
            "lation for e\u{2}".to_string(),
            "mail and in\u{2}".to_string(),
            "en verkoop".to_string(),
        ];
        let (t, j) = join_lines(&lines, Lang::Nl, &w(""), &mut st);
        assert_eq!(t, "the regulation for e-mail and in- en verkoop");
        assert!(j);
        assert_eq!(
            st,
            HyphenStats {
                markers: 3,
                joined: 1,
                kept: 2
            }
        );
    }
}
