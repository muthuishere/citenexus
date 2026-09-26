//! A tiny, dependency-free PDF writer for SYNTHETIC test fixtures.
//!
//! It writes PDF 1.7 by hand: standard-14 Helvetica / Helvetica-Bold with
//! WinAnsiEncoding (Latin-1 text), positioned text runs, stroked lines, filled
//! rectangles, a gray image XObject, an optional outline (bookmarks) and an
//! optional tagged structure tree (StructTreeRoot + ParentTree + MCIDs). No
//! AGPL/GPL tool is involved; every fixture is invented text.
//!
//! Coordinates are given TOP-LEFT origin (y grows down), in points, and
//! converted to PDF user space here.
#![allow(dead_code)]

#[derive(Clone)]
pub enum Item {
    /// `tag` = Some("H1" | "P" | ...) marks the run as tagged content.
    Text {
        x: f64,
        y: f64,
        size: f64,
        bold: bool,
        text: String,
        tag: Option<String>,
    },
    /// Invisible text (render mode 3): the OCR layer under a scan.
    Ocr {
        x: f64,
        y: f64,
        size: f64,
        text: String,
    },
    /// Text rotated `deg` degrees counter-clockwise about its start point
    /// (x, y) = where the baseline starts, top-left page coordinates. 90 =
    /// a vertical label reading bottom to top.
    Rotated {
        x: f64,
        y: f64,
        size: f64,
        deg: f64,
        text: String,
    },
    Line {
        x0: f64,
        y0: f64,
        x1: f64,
        y1: f64,
    },
    Rect {
        x: f64,
        y: f64,
        w: f64,
        h: f64,
    },
    Image {
        x: f64,
        y: f64,
        w: f64,
        h: f64,
    },
}

#[derive(Clone)]
pub struct Page {
    pub width: f64,
    pub height: f64,
    pub items: Vec<Item>,
    /// MediaBox lower-left corner (0, 0 by default). A non-zero origin moves
    /// the box and translates the content with it, so the page looks the same.
    pub origin: (f64, f64),
}

impl Page {
    pub fn a4() -> Self {
        Page {
            width: 595.0,
            height: 842.0,
            items: vec![],
            origin: (0.0, 0.0),
        }
    }
    pub fn text(mut self, x: f64, y: f64, size: f64, text: &str) -> Self {
        self.items.push(Item::Text {
            x,
            y,
            size,
            bold: false,
            text: text.into(),
            tag: None,
        });
        self
    }
    pub fn bold(mut self, x: f64, y: f64, size: f64, text: &str) -> Self {
        self.items.push(Item::Text {
            x,
            y,
            size,
            bold: true,
            text: text.into(),
            tag: None,
        });
        self
    }
    pub fn tagged(mut self, tag: &str, x: f64, y: f64, size: f64, bold: bool, text: &str) -> Self {
        self.items.push(Item::Text {
            x,
            y,
            size,
            bold,
            text: text.into(),
            tag: Some(tag.into()),
        });
        self
    }
    pub fn ocr(mut self, x: f64, y: f64, size: f64, text: &str) -> Self {
        self.items.push(Item::Ocr {
            x,
            y,
            size,
            text: text.into(),
        });
        self
    }
    /// A vertical label reading bottom to top, occupying x..x+size, with its
    /// baseline starting at (x + size, y_bottom).
    pub fn vertical(mut self, x: f64, y_bottom: f64, size: f64, text: &str) -> Self {
        self.items.push(Item::Rotated {
            x: x + size * 0.8,
            y: y_bottom,
            size,
            deg: 90.0,
            text: text.into(),
        });
        self
    }
    pub fn rotated(mut self, x: f64, y: f64, size: f64, deg: f64, text: &str) -> Self {
        self.items.push(Item::Rotated {
            x,
            y,
            size,
            deg,
            text: text.into(),
        });
        self
    }
    pub fn line(mut self, x0: f64, y0: f64, x1: f64, y1: f64) -> Self {
        self.items.push(Item::Line { x0, y0, x1, y1 });
        self
    }
    pub fn rect(mut self, x: f64, y: f64, w: f64, h: f64) -> Self {
        self.items.push(Item::Rect { x, y, w, h });
        self
    }
    pub fn image(mut self, x: f64, y: f64, w: f64, h: f64) -> Self {
        self.items.push(Item::Image { x, y, w, h });
        self
    }
    /// Lay `lines` out as a left-aligned paragraph starting at (x, y).
    pub fn para(mut self, x: f64, y: f64, size: f64, lines: &[&str]) -> Self {
        for (i, l) in lines.iter().enumerate() {
            self = self.text(x, y + i as f64 * size * 1.25, size, l);
        }
        self
    }
}

#[derive(Default)]
pub struct Doc {
    pub pages: Vec<Page>,
    /// (title, 0-based page index)
    pub outline: Vec<(String, usize)>,
}

fn esc(text: &str) -> Vec<u8> {
    let mut out = Vec::new();
    for ch in text.chars() {
        let b: u8 = match ch {
            '\u{2013}' => 0x96,
            '\u{2014}' => 0x97,
            '\u{20AC}' => 0x80,
            '\u{2022}' => 0x95,
            c if (c as u32) < 256 => c as u32 as u8,
            _ => b'?',
        };
        if b == b'(' || b == b')' || b == b'\\' {
            out.push(b'\\');
        }
        out.push(b);
    }
    out
}

fn f(v: f64) -> String {
    let s = format!("{v:.2}");
    s.trim_end_matches('0').trim_end_matches('.').to_string()
}

enum Kid {
    Mcid(usize),
    Elem(usize),
}

struct Elem {
    id: usize,
    role: String,
    page: usize,
    key: String,
    parent: Option<usize>,
    kids: Vec<Kid>,
    rowspan: u32,
    colspan: u32,
}

/// Parse one path segment: `Role`, `Role#id` / `Role:id`, optional `{rs=2,cs=3}`.
fn segment(seg: &str) -> (String, Option<String>, u32, u32) {
    let (head, attrs) = match seg.split_once('{') {
        Some((h, a)) => (h, a.trim_end_matches('}')),
        None => (seg, ""),
    };
    let (role, id) = match head.find(['#', ':']) {
        Some(i) => (head[..i].to_string(), Some(head[i + 1..].to_string())),
        None => (head.to_string(), None),
    };
    let (mut rs, mut cs) = (1, 1);
    for kv in attrs.split(',').filter(|x| !x.is_empty()) {
        if let Some((k, v)) = kv.split_once('=') {
            let n: u32 = v.trim().parse().unwrap_or(1);
            match k.trim() {
                "rs" => rs = n,
                "cs" => cs = n,
                _ => {}
            }
        }
    }
    (role, id, rs, cs)
}

/// Add one marked run to the element tree; returns the leaf's object id.
fn add_tag(
    elems: &mut Vec<Elem>,
    unique: &mut usize,
    tag: &str,
    page: usize,
    mcid: usize,
    alloc: &mut dyn FnMut() -> usize,
) -> usize {
    let segs: Vec<&str> = tag.split('/').collect();
    let mut parent: Option<usize> = None;
    let mut key = String::new();
    for (lvl, seg) in segs.iter().enumerate() {
        let (role, id, rs, cs) = segment(seg);
        key.push('/');
        match &id {
            Some(i) => key.push_str(&format!("{role}#{i}")),
            None => {
                *unique += 1;
                key.push_str(&format!("{role}~{unique}"));
            }
        }
        let found = elems.iter().position(|e| e.page == page && e.key == key);
        let idx = match found {
            Some(i) => i,
            None => {
                let obj = alloc();
                elems.push(Elem {
                    id: obj,
                    role,
                    page,
                    key: key.clone(),
                    parent,
                    kids: vec![],
                    rowspan: rs,
                    colspan: cs,
                });
                let i = elems.len() - 1;
                if let Some(p) = parent {
                    elems[p].kids.push(Kid::Elem(i));
                }
                i
            }
        };
        if lvl + 1 == segs.len() {
            elems[idx].kids.push(Kid::Mcid(mcid));
            return elems[idx].id;
        }
        parent = Some(idx);
    }
    unreachable!("a tag has at least one segment")
}

impl Doc {
    pub fn new(pages: Vec<Page>) -> Self {
        Doc {
            pages,
            outline: vec![],
        }
    }

    pub fn build(&self) -> Vec<u8> {
        // Object numbering: 1 catalog, 2 pages, 3 F1, 4 F2, 5 image, then the rest.
        let mut objs: Vec<Vec<u8>> = vec![vec![]; 5];
        let tagged = self.pages.iter().any(|p| {
            p.items
                .iter()
                .any(|i| matches!(i, Item::Text { tag: Some(_), .. }))
        });
        let mut next = 6usize;
        let mut alloc = |objs: &mut Vec<Vec<u8>>| {
            let n = next;
            next += 1;
            objs.push(vec![]);
            n
        };

        let mut page_ids = vec![];
        let mut content_ids = vec![];
        for _ in &self.pages {
            page_ids.push(alloc(&mut objs));
            content_ids.push(alloc(&mut objs));
        }
        let (root_id, doc_elem_id, parent_tree_id) = if tagged {
            (alloc(&mut objs), alloc(&mut objs), alloc(&mut objs))
        } else {
            (0, 0, 0)
        };

        // Struct elements, built from tag PATHS (see `Page::tagged`).
        let mut elems: Vec<Elem> = vec![];
        let mut unique = 0usize;
        let mut per_page_elems: Vec<Vec<usize>> = vec![vec![]; self.pages.len()];

        for (pi, page) in self.pages.iter().enumerate() {
            let mut c = Vec::new();
            let mut mcid = 0usize;
            for item in &page.items {
                match item {
                    Item::Text {
                        x,
                        y,
                        size,
                        bold,
                        text,
                        tag,
                    } => {
                        let font = if *bold { "F2" } else { "F1" };
                        let py = page.height - y - size;
                        if let Some(t) = tag {
                            c.extend(format!("/{t} <</MCID {mcid}>> BDC\n").bytes());
                        }
                        c.extend(
                            format!("BT /{font} {} Tf {} {} Td (", f(*size), f(*x), f(py)).bytes(),
                        );
                        c.extend(esc(text));
                        c.extend(b") Tj ET\n");
                        if let Some(t) = tag {
                            c.extend(b"EMC\n");
                            let id = add_tag(&mut elems, &mut unique, t, pi, mcid, &mut || {
                                alloc(&mut objs)
                            });
                            per_page_elems[pi].push(id);
                            mcid += 1;
                        }
                    }
                    Item::Ocr { x, y, size, text } => {
                        let py = page.height - y - size;
                        c.extend(
                            format!("BT 3 Tr /F1 {} Tf {} {} Td (", f(*size), f(*x), f(py)).bytes(),
                        );
                        c.extend(esc(text));
                        c.extend(b") Tj ET\n");
                    }
                    Item::Rotated {
                        x,
                        y,
                        size,
                        deg,
                        text,
                    } => {
                        let (s, co) = deg.to_radians().sin_cos();
                        c.extend(
                            format!(
                                "BT /F1 {} Tf {} {} {} {} {} {} Tm (",
                                f(*size),
                                f(co),
                                f(s),
                                f(-s),
                                f(co),
                                f(*x),
                                f(page.height - y)
                            )
                            .bytes(),
                        );
                        c.extend(esc(text));
                        c.extend(b") Tj ET\n");
                    }
                    Item::Line { x0, y0, x1, y1 } => c.extend(
                        format!(
                            "0.5 w {} {} m {} {} l S\n",
                            f(*x0),
                            f(page.height - y0),
                            f(*x1),
                            f(page.height - y1)
                        )
                        .bytes(),
                    ),
                    Item::Rect { x, y, w, h } => c.extend(
                        format!(
                            "{} {} {} {} re f\n",
                            f(*x),
                            f(page.height - y - h),
                            f(*w),
                            f(*h)
                        )
                        .bytes(),
                    ),
                    Item::Image { x, y, w, h } => c.extend(
                        format!(
                            "q {} 0 0 {} {} {} cm /Im0 Do Q\n",
                            f(*w),
                            f(*h),
                            f(*x),
                            f(page.height - y - h)
                        )
                        .bytes(),
                    ),
                }
            }
            if page.origin != (0.0, 0.0) {
                let mut wrapped =
                    format!("q 1 0 0 1 {} {} cm\n", f(page.origin.0), f(page.origin.1))
                        .into_bytes();
                wrapped.extend(&c);
                wrapped.extend(b"Q\n");
                c = wrapped;
            }
            let mut stream = format!("<< /Length {} >>\nstream\n", c.len()).into_bytes();
            stream.extend(&c);
            stream.extend(b"\nendstream");
            objs[content_ids[pi] - 1] = stream;
            let sp = if tagged {
                format!(" /StructParents {pi}")
            } else {
                String::new()
            };
            objs[page_ids[pi] - 1] = format!(
                "<< /Type /Page /Parent 2 0 R /MediaBox [{} {} {} {}] /Contents {} 0 R /Resources << /Font << /F1 3 0 R /F2 4 0 R >> /XObject << /Im0 5 0 R >> >>{sp} >>",
                f(page.origin.0),
                f(page.origin.1),
                f(page.origin.0 + page.width),
                f(page.origin.1 + page.height),
                content_ids[pi]
            )
            .into_bytes();
        }

        let kids: Vec<String> = page_ids.iter().map(|i| format!("{i} 0 R")).collect();
        objs[1] = format!(
            "<< /Type /Pages /Kids [{}] /Count {} >>",
            kids.join(" "),
            kids.len()
        )
        .into_bytes();
        objs[2] =
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
                .to_vec();
        objs[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>".to_vec();
        let img = [0x80u8, 0x40, 0xC0, 0x20];
        let mut io = format!(
            "<< /Type /XObject /Subtype /Image /Width 2 /Height 2 /ColorSpace /DeviceGray /BitsPerComponent 8 /Length {} >>\nstream\n",
            img.len()
        )
        .into_bytes();
        io.extend(img);
        io.extend(b"\nendstream");
        objs[4] = io;

        let mut catalog = String::from("<< /Type /Catalog /Pages 2 0 R");
        if tagged {
            for e in &elems {
                let kids: Vec<String> = e
                    .kids
                    .iter()
                    .map(|k| match k {
                        Kid::Mcid(m) => m.to_string(),
                        Kid::Elem(i) => format!("{} 0 R", elems[*i].id),
                    })
                    .collect();
                let parent = e.parent.map(|i| elems[i].id).unwrap_or(doc_elem_id);
                let attrs = if e.rowspan > 1 || e.colspan > 1 {
                    format!(
                        " /A << /O /Table /RowSpan {} /ColSpan {} >>",
                        e.rowspan, e.colspan
                    )
                } else {
                    String::new()
                };
                objs[e.id - 1] = format!(
                    "<< /Type /StructElem /S /{} /P {parent} 0 R /Pg {} 0 R /K [{}]{attrs} >>",
                    e.role,
                    page_ids[e.page],
                    kids.join(" ")
                )
                .into_bytes();
            }
            let all: Vec<String> = elems
                .iter()
                .filter(|e| e.parent.is_none())
                .map(|e| format!("{} 0 R", e.id))
                .collect();
            objs[doc_elem_id - 1] = format!(
                "<< /Type /StructElem /S /Document /P {root_id} 0 R /K [{}] >>",
                all.join(" ")
            )
            .into_bytes();
            let nums: Vec<String> = per_page_elems
                .iter()
                .enumerate()
                .map(|(pi, ids)| {
                    let r: Vec<String> = ids.iter().map(|i| format!("{i} 0 R")).collect();
                    format!("{pi} [{}]", r.join(" "))
                })
                .collect();
            objs[parent_tree_id - 1] = format!("<< /Nums [{}] >>", nums.join(" ")).into_bytes();
            objs[root_id - 1] = format!(
                "<< /Type /StructTreeRoot /K [{doc_elem_id} 0 R] /ParentTree {parent_tree_id} 0 R >>"
            )
            .into_bytes();
            catalog.push_str(&format!(
                " /StructTreeRoot {root_id} 0 R /MarkInfo << /Marked true >> /Lang (en)"
            ));
        }
        if !self.outline.is_empty() {
            let outlines_id = alloc(&mut objs);
            let item_ids: Vec<usize> = self.outline.iter().map(|_| alloc(&mut objs)).collect();
            for (k, (title, pi)) in self.outline.iter().enumerate() {
                let mut d = format!(
                    "<< /Title ({}) /Parent {outlines_id} 0 R /Dest [{} 0 R /XYZ 0 {} 0]",
                    String::from_utf8_lossy(&esc(title)),
                    page_ids[*pi],
                    f(self.pages[*pi].height)
                );
                if k > 0 {
                    d.push_str(&format!(" /Prev {} 0 R", item_ids[k - 1]));
                }
                if k + 1 < item_ids.len() {
                    d.push_str(&format!(" /Next {} 0 R", item_ids[k + 1]));
                }
                d.push_str(" >>");
                objs[item_ids[k] - 1] = d.into_bytes();
            }
            objs[outlines_id - 1] = format!(
                "<< /Type /Outlines /First {} 0 R /Last {} 0 R /Count {} >>",
                item_ids[0],
                item_ids[item_ids.len() - 1],
                item_ids.len()
            )
            .into_bytes();
            catalog.push_str(&format!(" /Outlines {outlines_id} 0 R"));
        }
        catalog.push_str(" >>");
        objs[0] = catalog.into_bytes();

        let mut out = b"%PDF-1.7\n%\xE2\xE3\xCF\xD3\n".to_vec();
        let mut offsets = vec![];
        for (i, body) in objs.iter().enumerate() {
            offsets.push(out.len());
            out.extend(format!("{} 0 obj\n", i + 1).bytes());
            out.extend(body);
            out.extend(b"\nendobj\n");
        }
        let xref = out.len();
        out.extend(format!("xref\n0 {}\n0000000000 65535 f \n", objs.len() + 1).bytes());
        for o in offsets {
            out.extend(format!("{o:010} 00000 n \n").bytes());
        }
        out.extend(
            format!(
                "trailer\n<< /Size {} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n",
                objs.len() + 1
            )
            .bytes(),
        );
        out
    }
}
