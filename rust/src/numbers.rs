//! Locale-aware number reading (ADR-0015), ported from the Python reference
//! `python/src/citenexus/answer/numbers.py` (introduced at `6f7cee0`) and
//! pinned by the same 30 `number_readings` vectors (`tests/numbers_test.rs`).
//!
//! A number is read to a single value only when its FORM, or the text's
//! DECLARED language, leaves one reading; otherwise its key is its raw
//! spelling prefixed `?`, equal to nothing but the same spelling. A false
//! "equal" fails open, a false "different" fails closed, so ambiguity never
//! guesses.
//!
//! Forms (`.` and `,` are the only separators read):
//! - `1500` — an integer; `25,-` — Dutch whole amount (25);
//! - both separators — the LAST is the decimal mark: `1.500,50` = 1500.5;
//! - one separator, repeated — thousands in threes: `1.500.000`;
//! - one separator, once, not followed by exactly three digits, or with a
//!   whole part that cannot lead a thousands group — a decimal mark in every
//!   locale: `25,50`, `1,5`, `0.500`, `1234.567`;
//! - `1.500` / `1,500` — read only under a declared language (`nl` decimal
//!   comma, `en` decimal point), ambiguous otherwise;
//! - anything else (`1.50.000`, `01.02.2024`) — unreadable, kept by spelling.
//!
//! Values are exact: a key is a canonical decimal string built from the digit
//! strings (no floats anywhere).

/// Languages whose decimal mark is a comma / a point (ADR-0015 tables).
pub const DECIMAL_COMMA_LANGUAGES: &[&str] = &["nl"];
pub const DECIMAL_POINT_LANGUAGES: &[&str] = &["en"];

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct NumberReading {
    /// Canonical value ("1500", "25.5", "0.05") or `?<raw>` when ambiguous
    /// or unreadable.
    pub key: String,
    /// The reading has one value.
    pub known: bool,
}

fn primary(language: Option<&str>) -> String {
    language
        .map(|l| l.trim().to_lowercase())
        .and_then(|l| l.split(['-', '_']).next().map(String::from))
        .unwrap_or_default()
}

/// `int("".join(groups))` + `decimals / 10^len`, as a canonical decimal string.
fn canonical(integer_groups: &[&str], decimals: &str) -> String {
    let joined: String = integer_groups.concat();
    let int = joined.trim_start_matches('0');
    let int = if int.is_empty() { "0" } else { int };
    let dec = decimals.trim_end_matches('0');
    if dec.is_empty() {
        int.to_string()
    } else {
        format!("{int}.{dec}")
    }
}

fn known(groups: &[&str], decimals: &str) -> NumberReading {
    NumberReading {
        key: canonical(groups, decimals),
        known: true,
    }
}

fn unread(raw: &str) -> NumberReading {
    NumberReading {
        key: format!("?{raw}"),
        known: false,
    }
}

fn is_group(g: &str) -> bool {
    g.len() == 3 && g.bytes().all(|b| b.is_ascii_digit())
}

fn is_lead(g: &str) -> bool {
    (1..=3).contains(&g.len()) && g.bytes().all(|b| b.is_ascii_digit()) && !g.starts_with('0')
}

/// A valid thousands grouping: 1–3 leading digits (no leading zero), then threes.
fn thousands(groups: &[&str]) -> bool {
    is_lead(groups[0]) && groups[1..].iter().all(|g| is_group(g))
}

/// Read one number spelling (digits joined by single `.`/`,`) to its key.
/// `dash` is true when the Dutch `,-` suffix followed it.
pub fn read_number(raw: &str, dash: bool, language: Option<&str>) -> NumberReading {
    if dash {
        if raw.contains(',') {
            return unread(&format!("{raw},-"));
        }
        let groups: Vec<&str> = raw.split('.').collect();
        if groups.len() > 1 && !thousands(&groups) {
            return unread(&format!("{raw},-"));
        }
        return known(&groups, "");
    }
    let (has_dot, has_comma) = (raw.contains('.'), raw.contains(','));
    if !has_dot && !has_comma {
        return known(&[raw], "");
    }
    if has_dot && has_comma {
        let decimal_mark = if raw.rfind('.') > raw.rfind(',') {
            '.'
        } else {
            ','
        };
        let thousands_mark = if decimal_mark == '.' { ',' } else { '.' };
        let cut = raw.rfind(decimal_mark).expect("mark present");
        let (whole, decimals) = (&raw[..cut], &raw[cut + 1..]);
        if whole.contains(decimal_mark) {
            return unread(raw);
        }
        let groups: Vec<&str> = whole.split(thousands_mark).collect();
        if !thousands(&groups) {
            return unread(raw);
        }
        return known(&groups, decimals);
    }
    let mark = if has_dot { '.' } else { ',' };
    let parts: Vec<&str> = raw.split(mark).collect();
    if parts.len() > 2 {
        return if thousands(&parts) {
            known(&parts, "")
        } else {
            unread(raw)
        };
    }
    let (whole, tail) = (parts[0], parts[1]);
    if tail.len() != 3 || !thousands(&parts) {
        return known(&[whole], tail); // a decimal mark in every locale
    }
    let code = primary(language);
    let as_thousands = if DECIMAL_COMMA_LANGUAGES.contains(&code.as_str()) {
        mark == '.'
    } else if DECIMAL_POINT_LANGUAGES.contains(&code.as_str()) {
        mark == ','
    } else {
        return unread(raw); // 1.500 / 1,500 with no declared locale
    };
    if as_thousands {
        known(&[whole, tail], "")
    } else {
        known(&[whole], tail)
    }
}

/// Every number in `text` (Python `NUMBER_RE` group 1 + the `,-` suffix):
/// ASCII digit groups joined by single `.`/`,`. Returns the readings in order.
pub fn numbers_in(text: &str, language: Option<&str>) -> Vec<NumberReading> {
    let b: Vec<char> = text.chars().collect();
    let mut out = Vec::new();
    let mut i = 0;
    while i < b.len() {
        if !b[i].is_ascii_digit() {
            i += 1;
            continue;
        }
        let start = i;
        while i < b.len() && b[i].is_ascii_digit() {
            i += 1;
        }
        // groups: a separator followed by at least one digit
        while i + 1 < b.len() && (b[i] == '.' || b[i] == ',') && b[i + 1].is_ascii_digit() {
            i += 1;
            while i < b.len() && b[i].is_ascii_digit() {
                i += 1;
            }
        }
        let raw: String = b[start..i].iter().collect();
        let dash = i + 1 < b.len() && b[i] == ',' && b[i + 1] == '-';
        if dash {
            i += 2;
        }
        out.push(read_number(&raw, dash, language));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn forms() {
        let k = |r: &str, l: Option<&str>| read_number(r, false, l).key;
        assert_eq!(k("1.500,50", None), "1500.5");
        assert_eq!(k("7.000,00", Some("nl")), "7000");
        assert_eq!(k("70.000,0", Some("nl")), "70000");
        assert_eq!(k("1.500", Some("nl")), "1500");
        assert_eq!(k("1.500", Some("en")), "1.5");
        assert_eq!(k("1.500", None), "?1.500");
        assert_eq!(k("0.500", None), "0.5");
        assert_eq!(read_number("25", true, None).key, "25");
    }

    #[test]
    fn scanning_text() {
        let keys: Vec<String> = numbers_in("€ 5.100,00 en 25,- op 01.02.2024", Some("nl"))
            .into_iter()
            .map(|r| r.key)
            .collect();
        assert_eq!(keys, vec!["5100", "25", "?01.02.2024"]);
    }
}
