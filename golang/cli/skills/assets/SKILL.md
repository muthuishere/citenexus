---
name: citenexus
description: Drive the CiteNexus CLI — an evidence-first RAG engine that ingests artifacts (pdf, docx, pptx, html, md, txt, csv, images) and answers ONLY from retrieved, cited evidence, abstaining when evidence is weak, missing, or conflicting. Use when the user wants to build a local knowledge base and ask grounded, cite-or-abstain questions over their own documents. Trigger on "ingest these docs", "ask my corpus", "what do my documents say about X", "ground this answer in my files", "cite-or-abstain over my folder".
---

# CiteNexus CLI skill

CiteNexus answers **only** from retrieved evidence and **abstains** when evidence
is weak, missing, or conflicting. The guarantee is *no ungrounded claim*. You
drive it through the `citenexus` binary; you never invent an answer yourself.

## Prerequisites

The `citenexus` binary must be on PATH (`npm i -g @muthuishere/citenexuscli`). If it
is missing, tell the user to install it — do not fabricate answers.

## The loop

1. **Scaffold** (once per project): `citenexus init` writes a committable
   `citenexus.yaml`. Secrets are never stored — auth is `${ENV}` header templates
   resolved at the request edge, so the file is always safe to commit.
2. **Ingest**: `citenexus ingest <path>` extracts, chunks, embeds and stores the
   artifact's evidence units. Re-ingesting the same document replaces its rows.
3. **Retrieve** (cite-only, no model): `citenexus retrieve "<query>" --json`
   returns fused candidates (BM25 + vector, RRF). Use this to *show sources*.
4. **Ask** (grounded answer or refusal): `citenexus ask "<question>" --json`
   returns a `Result`: an `answer` with `sources[]` (verbatim passages), or a
   refusal with `decision: "refused"`. **Relay the refusal honestly** — never
   paper over it.

## Reading the result

`ask --json` emits the pinned `Result` shape. Check `evidence.decision`:
`"answered"` → present `answer` + cite each `sources[].passage`;
`"refused"` → tell the user the corpus lacks the evidence.

See `references/commands.md` for the full flag/command table and the two LLM
modes (`api` today; `skill` mode — where this skill fulfills the model call — is
the sequenced follow-on).
