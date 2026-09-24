//! Two independent vision transcriptions, reconciled (ADR-0017 decision 4).
//!
//! A vision model writes text where there is no text layer to check it
//! against, and no bag of words can see a MOVED word ("geen" moved to another
//! sentence) or two amounts swapped between lines. So every vision request is
//! issued TWICE (variants 1 and 2, the host asked to use a different model or
//! seed), and only what both transcriptions say identically is kept as
//! content:
//!
//! - both texts are split into sentences (per line, then after `.`/`!`/`?`);
//! - each sentence gets a comparison key: NFKC, case-folded, whitespace-free
//!   word runs, with every number replaced by its ADR-0015 reading
//!   (`numbers::read_number` in the declared language), so `7.000,00` and
//!   `7000,00` compare equal under `nl` and whitespace/case never matter;
//! - an order-preserving alignment (LCS over keys) pairs identical sentences;
//! - paired sentences are **content** (the first transcription's text);
//!   everything else — a sentence only one side has, or that differs — is
//!   **disputed**.
//!
//! Disputed text stays in the unit, inside an HTML comment the host can
//! recognise and must exclude from citable text:
//!
//! ```text
//! <!-- vision_disputed
//! v1: <what transcription 1 said here>
//! v2: <what transcription 2 said here>
//! -->
//! ```
//!
//! `citable_text` strips these blocks. With only one transcription the whole
//! text is one disputed block (single source: never silently trusted).

use unicode_normalization::UnicodeNormalization;

use crate::numbers::read_number;

pub const OPEN: &str = "<!-- vision_disputed";
pub const CLOSE: &str = "-->";

#[derive(Debug, Clone, PartialEq)]
struct Sentence {
    text: String,
    key: Vec<String>,
    line: usize,
}

/// The comparison key of a sentence.
pub fn sentence_key(s: &str, language: Option<&str>) -> Vec<String> {
    let n: Vec<char> = s
        .nfkc()
        .collect::<String>()
        .replace('\u{AD}', "")
        .to_lowercase()
        .chars()
        .collect();
    let mut out = Vec::new();
    let mut i = 0;
    while i < n.len() {
        let c = n[i];
        if c.is_ascii_digit() {
            let start = i;
            while i < n.len() && n[i].is_ascii_digit() {
                i += 1;
            }
            while i + 1 < n.len() && (n[i] == '.' || n[i] == ',') && n[i + 1].is_ascii_digit() {
                i += 1;
                while i < n.len() && n[i].is_ascii_digit() {
                    i += 1;
                }
            }
            let raw: String = n[start..i].iter().collect();
            let dash = i + 1 < n.len() && n[i] == ',' && n[i + 1] == '-';
            if dash {
                i += 2;
            }
            out.push(format!("#{}", read_number(&raw, dash, language).key));
        } else if c.is_alphanumeric() {
            let start = i;
            while i < n.len() && n[i].is_alphanumeric() && !n[i].is_ascii_digit() {
                i += 1;
            }
            out.push(n[start..i].iter().collect());
        } else {
            i += 1;
        }
    }
    out
}

fn sentences(md: &str, language: Option<&str>) -> Vec<Sentence> {
    let mut out = Vec::new();
    for (line_no, line) in md.lines().enumerate() {
        let chars: Vec<char> = line.chars().collect();
        let mut start = 0;
        let mut k = 0;
        while k < chars.len() {
            let end_mark = matches!(chars[k], '.' | '!' | '?');
            let next_space = chars.get(k + 1).is_none_or(|c| c.is_whitespace());
            // "7.000" keeps its dot: only a mark followed by whitespace ends a sentence
            if end_mark && next_space {
                push(&mut out, &chars[start..=k], line_no, language);
                start = k + 1;
            }
            k += 1;
        }
        if start < chars.len() {
            push(&mut out, &chars[start..], line_no, language);
        }
    }
    out
}

fn push(out: &mut Vec<Sentence>, chars: &[char], line: usize, language: Option<&str>) {
    let text: String = chars.iter().collect::<String>().trim().to_string();
    let key = sentence_key(&text, language);
    if !key.is_empty() {
        out.push(Sentence { text, key, line });
    }
}

/// Keep a comment from being closed early by the text inside it.
fn safe(t: &str) -> String {
    t.replace("--", "- -").replace('>', "›")
}

fn block(v1: &[&Sentence], v2: &[&Sentence]) -> String {
    let join = |s: &[&Sentence]| {
        s.iter()
            .map(|x| safe(&x.text))
            .collect::<Vec<_>>()
            .join(" ")
    };
    format!("{OPEN}\nv1: {}\nv2: {}\n{CLOSE}", join(v1), join(v2))
}

/// Order-preserving LCS pairs over sentence keys.
fn align(a: &[Sentence], b: &[Sentence]) -> Vec<(usize, usize)> {
    let (n, m) = (a.len(), b.len());
    let mut dp = vec![vec![0usize; m + 1]; n + 1];
    for i in (0..n).rev() {
        for j in (0..m).rev() {
            dp[i][j] = if a[i].key == b[j].key {
                dp[i + 1][j + 1] + 1
            } else {
                dp[i + 1][j].max(dp[i][j + 1])
            };
        }
    }
    let (mut i, mut j) = (0, 0);
    let mut pairs = Vec::new();
    while i < n && j < m {
        if a[i].key == b[j].key {
            pairs.push((i, j));
            i += 1;
            j += 1;
        } else if dp[i + 1][j] >= dp[i][j + 1] {
            i += 1;
        } else {
            j += 1;
        }
    }
    pairs
}

#[derive(Debug, Clone, PartialEq)]
pub struct Reconciled {
    pub markdown: String,
    /// At least one sentence (or the whole text) is disputed.
    pub disputed: bool,
    pub content_sentences: usize,
    pub disputed_sentences: usize,
}

/// Reconcile the two transcriptions; `None` = that variant is missing or
/// failed its checks.
pub fn reconcile(v1: Option<&str>, v2: Option<&str>, language: Option<&str>) -> Option<Reconciled> {
    let (a, b) = match (v1, v2) {
        (None, None) => return None,
        (Some(t), None) | (None, Some(t)) => {
            let s = sentences(t, language);
            let refs: Vec<&Sentence> = s.iter().collect();
            let (x, y): (&[&Sentence], &[&Sentence]) = if v1.is_some() {
                (&refs, &[])
            } else {
                (&[], &refs)
            };
            return Some(Reconciled {
                markdown: block(x, y),
                disputed: true,
                content_sentences: 0,
                disputed_sentences: s.len(),
            });
        }
        (Some(a), Some(b)) => (sentences(a, language), sentences(b, language)),
    };
    let pairs = align(&a, &b);
    let mut out: Vec<String> = Vec::new();
    let mut cur_line: Option<usize> = None;
    let (mut ia, mut ib) = (0usize, 0usize);
    let (mut content, mut disputed) = (0usize, 0usize);
    let emit_gap = |out: &mut Vec<String>,
                    cur_line: &mut Option<usize>,
                    ga: &[&Sentence],
                    gb: &[&Sentence]| {
        if ga.is_empty() && gb.is_empty() {
            return 0;
        }
        out.push(block(ga, gb));
        *cur_line = None;
        ga.len() + gb.len()
    };
    for &(pa, pb) in pairs.iter().chain(std::iter::once(&(a.len(), b.len()))) {
        let ga: Vec<&Sentence> = a[ia..pa].iter().collect();
        let gb: Vec<&Sentence> = b[ib..pb].iter().collect();
        disputed += emit_gap(&mut out, &mut cur_line, &ga, &gb);
        if pa < a.len() {
            let s = &a[pa];
            match (cur_line, out.last_mut()) {
                (Some(l), Some(last)) if l == s.line => {
                    last.push(' ');
                    last.push_str(&s.text);
                }
                _ => out.push(s.text.clone()),
            }
            cur_line = Some(s.line);
            content += 1;
        }
        ia = pa + 1;
        ib = pb + 1;
    }
    Some(Reconciled {
        markdown: out.join("\n"),
        disputed: disputed > 0,
        content_sentences: content,
        disputed_sentences: disputed,
    })
}

/// The markdown with every `vision_disputed` block removed: the only text a
/// host may cite or quote-match.
pub fn citable_text(markdown: &str) -> String {
    let mut out = String::new();
    let mut rest = markdown;
    while let Some(start) = rest.find(OPEN) {
        out.push_str(&rest[..start]);
        match rest[start..].find(CLOSE) {
            Some(end) => rest = &rest[start + end + CLOSE.len()..],
            None => {
                rest = "";
            }
        }
    }
    out.push_str(rest);
    out.lines()
        .map(str::trim_end)
        .filter(|l| !l.trim().is_empty())
        .collect::<Vec<_>>()
        .join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    const V1: &str = "Reiskosten 7.000,00 geen voorschot. Hotel 5.100,00 per jaar.\nDiner 1.250,00 vooraf betaald.";

    #[test]
    fn whitespace_and_case_only_differences_are_content() {
        let v2 = "reiskosten   7.000,00 GEEN voorschot.  Hotel 5.100,00 per jaar.\nDiner 1.250,00 vooraf betaald.";
        let r = reconcile(Some(V1), Some(v2), Some("nl")).unwrap();
        assert!(!r.disputed);
        assert_eq!(r.content_sentences, 3);
        assert_eq!(citable_text(&r.markdown), V1);
    }

    #[test]
    fn a_moved_geen_is_disputed_not_content() {
        let v2 = "Reiskosten 7.000,00 voorschot. Hotel 5.100,00 geen per jaar.\nDiner 1.250,00 vooraf betaald.";
        let r = reconcile(Some(V1), Some(v2), Some("nl")).unwrap();
        assert!(r.disputed);
        let c = citable_text(&r.markdown);
        assert_eq!(c, "Diner 1.250,00 vooraf betaald.");
        assert!(r
            .markdown
            .contains("v2: Reiskosten 7.000,00 voorschot. Hotel 5.100,00 geen per jaar."));
    }

    #[test]
    fn a_number_changed_in_one_is_disputed() {
        let v2 = V1.replace("5.100,00", "5.001,00");
        let r = reconcile(Some(V1), Some(&v2), Some("nl")).unwrap();
        let c = citable_text(&r.markdown);
        assert!(!c.contains("Hotel"), "{c}");
        assert!(c.contains("Reiskosten 7.000,00 geen voorschot."));
    }

    #[test]
    fn same_amount_written_two_ways_is_content() {
        let v2 = V1.replace("7.000,00", "7000,00");
        let r = reconcile(Some(V1), Some(&v2), Some("nl")).unwrap();
        assert!(!r.disputed);
    }

    #[test]
    fn a_single_transcription_is_all_disputed() {
        let r = reconcile(None, Some(V1), Some("nl")).unwrap();
        assert!(r.disputed);
        assert_eq!(citable_text(&r.markdown), "");
        assert!(r.markdown.starts_with(OPEN));
        assert!(reconcile(None, None, None).is_none());
    }

    #[test]
    fn comment_text_cannot_close_the_block() {
        let r = reconcile(Some("a --> b"), None, None).unwrap();
        assert_eq!(r.markdown.matches(CLOSE).count(), 1);
    }
}
