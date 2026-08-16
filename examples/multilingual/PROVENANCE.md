# Provenance of the multilingual corpus

## The corpus is authored fiction. Read this before quoting anything from it.

Every one of the twelve documents in `corpus/` (and their sources in
`corpus-src/`) was **written for this example**. None of it is a real policy,
a real statute, or a real contract, and none of it was copied, scraped or
adapted from any real employer's handbook.

- **"Vaanam Technologies Private Limited" does not exist.** The company, its
  Chennai and Hyderabad offices, its document IDs (`VTPL-HB-02`,
  `VTPL-ANX-CHN-03`, …), its clause numbering and its effective dates are all
  invented.
- **Every figure is invented.** The 60-day notice period, the INR 45,000 notice
  buy-out, the INR 12,500 probation stipend, the INR 2,00,000 liquidated
  damages, the 26 weeks of maternity leave — all chosen to make the measurement
  work, not because they reflect Indian employment law, the Maternity Benefit
  Act, the Shops and Establishments Acts of Tamil Nadu or Telangana, or any
  employer's actual practice.
- **This is not legal advice** and must not be used as a template, a reference,
  or a basis for any employment decision.

## Why authored rather than scraped

Real statutes and real employer handbooks are a licensing problem: statute text
carries jurisdiction-specific reuse terms, and a real handbook is somebody's
confidential document. Authoring the corpus sidesteps both, and it buys
something a scrape cannot — the corpus can be **designed** so the measurement is
possible at all:

1. The English handbook is deliberately incomplete. Clauses 3.4, 4.3 and 9.2
   state the general rule and then say, in so many words, *this Part does not
   itself state that figure — the regional annexure does*. So the English half
   is internally consistent and honest, and the figure genuinely exists in only
   one place.
2. That one place is a Tamil or a Telugu document. An English question about it
   therefore has exactly one grounded answer, in a script the query does not
   share a single token with. `test_corpus.py` enforces this: it fails if any
   Tamil/Telugu-only figure leaks into an English document.
3. Exact-match-critical tokens — clause numbers (`7.2`, `9.4`), day counts
   (`21`, `90`), amounts (`INR 45,000`) — are seeded throughout, because those
   are precisely what query translation damages, and you cannot measure damage
   to something that is not there.

## Language quality

The Tamil and Telugu documents were authored for this example in a formal
policy register. They are meant to be *plausible and internally consistent*
policy prose that a Tamil or Telugu reader can follow — not certified
translations, and not the output of a professional legal translator. Where a
Tamil and a Telugu annexure cover the same topic they are deliberately **not**
parallel translations of each other: they state different figures for different
offices, which is what makes each one individually load-bearing.

If you are a native speaker and find awkward phrasing, that is a real defect
worth fixing — but note that fixing it must not change any of the numbered
facts, or `test_corpus.py` and the baseline in `RESULTS.md` will disagree.

## The PDFs

`corpus/07-*.pdf` and `corpus/08-*.pdf` are real PDFs, generated from the
matching `.txt` files in `corpus-src/` by `tools/render_pdf.py` using headless
Chrome and the macOS system font *Tamil Sangam MN*. They are reproducible:
re-running that script regenerates them byte-for-similar and re-verifies the
extraction fidelity. See `RESULTS.md` for what does and does not survive the
round-trip, and why Telugu is deliberately **not** shipped as a PDF.

## Third-party material

None. No external text, no downloaded fonts committed to the repo, no scraped
sources. The fonts used for rendering are macOS system fonts, referenced by
name at render time and not redistributed here.
