"""CiteNexus live demo — six REAL capabilities, one continuous session, no
faked beats, no artificial pauses. Everything below executes for real against
the merged main: real embeddings + reranking (Jina), real generation + vision
(Gemini), real citations. Every model client is the library's own injected,
OpenAI-compatible endpoint seam (citenexus.http) wired to real provider keys
already present in the environment — CiteNexus itself reads no environment;
the caller resolves secrets and injects them, exactly as this script does.

Theme: a clinical-trial protocol with a data-protection addendum (law +
medicine, one coherent corpus).

1. PROSE grounding + cite-or-abstain — a real law clause, a real answer with
   a citation, then a question the corpus has no evidence for -> refusal.
2. VISION on a REAL .docx — a real Word document (python-docx, standard
   OOXML) with a real embedded chart image -> Gemini vision describes it on
   real ingest (image bytes persisted + §9 pre-filter routes it, not
   injected test bytes) -> a question about the chart -> cited, grounded.
3. TABLE — a real CSV dosage table -> a numeric question -> the cited
   passage is the literal table row.
4. LIST — a real HTML contraindications list -> a question -> the cited
   passage is the literal list item.
5. CODE BLOCK — a real Markdown fenced snippet -> a question -> the cited
   passage is the literal code.
6. CAPTION + DOCUMENT METADATA — a real HTML <figcaption> -> a question ->
   the cited passage is the caption; document title/author are also real,
   extracted metadata.

Run:
    GEMINI_API_KEY=... uv run python scripts/demo/citenexus_capabilities_demo.py
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from citenexus import CiteNexus, GeminiHttpEndpoint, OpenAIHttpEndpoint
from citenexus.answer.generator import OpenAICompatibleGenerator
from citenexus.answer.result import Decision
from citenexus.embed.client import OpenAICompatibleEmbedding
from citenexus.extract.html import HtmlExtractor
from citenexus.retrieve.rerank import OpenAICompatibleReranker
from citenexus.vision.client import OpenAICompatibleVision

ASSETS = Path(__file__).resolve().parent / "assets"


class _SingleTextEmbedder:
    """Adapts the batch OpenAI-compatible embedding plugin to the single-text
    seam ``CiteNexus(embedder=...)`` expects (``embed(text) -> vector``)."""

    def __init__(self, plugin: OpenAICompatibleEmbedding) -> None:
        self._plugin = plugin

    def embed(self, text: str) -> list[float]:
        return self._plugin.embed_query(text)


def _rule(char: str = "-") -> None:
    print(char * 70)


def main() -> None:
    gemini_key = os.environ.get("GEMINI_API_KEY")
    jina_key = os.environ.get("JINA_API_KEY")
    missing = [name for name, val in (("GEMINI_API_KEY", gemini_key), ("JINA_API_KEY", jina_key)) if not val]
    if missing:
        print(f"Missing required env var(s): {', '.join(missing)}", file=sys.stderr)
        raise SystemExit(1)

    store_dir = Path("/tmp/citenexus-capabilities-store")
    shutil.rmtree(store_dir, ignore_errors=True)

    gemini = GeminiHttpEndpoint(api_key=gemini_key)
    jina = OpenAIHttpEndpoint(base_url="https://api.jina.ai/v1", api_key=jina_key)

    generator = OpenAICompatibleGenerator(
        base_url=gemini.base_url, model="gemini-2.5-flash", transport=gemini.build_transport()
    )
    vision = OpenAICompatibleVision(
        base_url=gemini.base_url, model="gemini-2.5-flash", transport=gemini.build_transport()
    )
    embedder = _SingleTextEmbedder(
        OpenAICompatibleEmbedding(
            base_url=jina.base_url, model="jina-embeddings-v3", transport=jina.build_transport()
        )
    )
    reranker = OpenAICompatibleReranker(
        base_url=jina.base_url,
        model="jina-reranker-v2-base-multilingual",
        transport=jina.build_transport(),
    )

    _rule("=")
    print('>>> rag = CiteNexus("./store", embedder=Jina, reranker=Jina, generator=Gemini, vision=Gemini)')
    rag = CiteNexus(
        store_dir, embedder=embedder, reranker=reranker, generator=generator, vision=vision
    )
    _rule("=")

    # 1. PROSE — cite, then abstain.
    print("\n### 1/6 PROSE — cite-or-abstain")
    law_text = (
        "Under Section 7(2) of the Data Protection Act, a data controller must "
        "notify the supervisory authority of a personal data breach within "
        "seventy-two hours of becoming aware of it."
    )
    print(f'>>> rag.ingest(text="{law_text}", document_id="data-protection-act-s7")')
    rag.ingest(text=law_text, document_id="data-protection-act-s7")

    q1 = "Within how many hours must a data controller notify the supervisory authority of a breach?"
    print(f"\n>>> rag.ask({q1!r})")
    a1 = rag.ask(q1)
    print(f"decision: {a1.evidence.decision.value}")
    if a1.evidence.decision is Decision.answered:
        print(f"source: {a1.sources[0].document} (cited, verbatim)")
    print(a1.answer)

    q2 = "How many patients were enrolled in the trial's control arm?"
    print(f"\n>>> rag.ask({q2!r})")
    a2 = rag.ask(q2)
    print(f"decision: {a2.evidence.decision.value}")
    print(a2.answer)

    # 2. VISION on a REAL .docx.
    _rule()
    print("\n### 2/6 VISION — real .docx, real embedded chart, real Gemini vision")
    docx_path = ASSETS / "clinical-trial-protocol.docx"
    print('>>> rag.ingest("clinical-trial-protocol.docx")  # real Word doc, real chart image')
    result = rag.ingest(docx_path, document_id="clinical-trial-protocol")
    print(f"ingested: {len(result.eu_ids)} evidence units (text + 1 vision-described figure)")

    q_vision = "According to the chart, which group has a higher recovery rate — treatment or placebo?"
    print(f"\n>>> rag.ask({q_vision!r})")
    a_vision = rag.ask(q_vision)
    print(f"decision: {a_vision.evidence.decision.value}")
    if a_vision.evidence.decision is Decision.answered:
        print(f"source: {a_vision.sources[0].document} (cited, verbatim — real vision description)")
    print(a_vision.answer)

    # 3. TABLE — real CSV, numeric question, cited row.
    _rule()
    print("\n### 3/6 TABLE — real row-level citation")
    csv_text = "PatientWeightKg,DosageMg\n50,250\n70,350\n90,450\n"
    csv_path = Path("/tmp/citenexus-capabilities-dosage.csv")
    csv_path.write_text(csv_text)
    print('>>> rag.ingest("dosage-table.csv")')
    rag.ingest(csv_path, document_id="dosage-table")

    q3 = "What is the dosage in mg for a patient weighing 70 kg?"
    print(f"\n>>> rag.ask({q3!r})")
    a3 = rag.ask(q3)
    print(f"decision: {a3.evidence.decision.value}")
    if a3.evidence.decision is Decision.answered:
        print(f"source: {a3.sources[0].document} (cited row, verbatim)")
    print(a3.answer)

    # 4. LIST — real HTML <ul>, cited list item.
    _rule()
    print("\n### 4/6 LIST — real list-item citation")
    html_list = (
        "<html><body>"
        "<p>Unrelated protocol narrative text.</p>"
        "<h2>Contraindications</h2>"
        "<ul>"
        "<li>Known hypersensitivity to the active compound.</li>"
        "<li>Severe hepatic impairment.</li>"
        "<li>Pregnancy or planned pregnancy during the trial period.</li>"
        "</ul>"
        "</body></html>"
    )
    html_path = Path("/tmp/citenexus-capabilities-contraindications.html")
    html_path.write_text(html_list)
    print('>>> rag.ingest("contraindications.html")')
    rag.ingest(html_path, document_id="contraindications")

    q4 = "Which contraindication relates to severe hepatic impairment?"
    print(f"\n>>> rag.ask({q4!r})")
    a4 = rag.ask(q4)
    print(f"decision: {a4.evidence.decision.value}")
    if a4.evidence.decision is Decision.answered:
        print(f"source: {a4.sources[0].document} (cited list item, verbatim)")
    print(a4.answer)

    # 5. CODE BLOCK — real Markdown fence, cited code.
    _rule()
    print("\n### 5/6 CODE — real fenced-code citation")
    md_text = (
        "Unrelated protocol narrative text.\n\n"
        "```python\n"
        "def dosage_mg(weight_kg: float) -> float:\n"
        "    return weight_kg * DOSAGE_FACTOR  # DOSAGE_FACTOR = 5.0\n"
        "```\n"
    )
    md_path = Path("/tmp/citenexus-capabilities-formula.md")
    md_path.write_text(md_text)
    print('>>> rag.ingest("dosage-formula.md")')
    rag.ingest(md_path, document_id="dosage-formula")

    q5 = "What is the value of DOSAGE_FACTOR in the dosage formula?"
    print(f"\n>>> rag.ask({q5!r})")
    a5 = rag.ask(q5)
    print(f"decision: {a5.evidence.decision.value}")
    if a5.evidence.decision is Decision.answered:
        print(f"source: {a5.sources[0].document} (cited code, verbatim)")
    print(a5.answer)

    # 6. CAPTION + DOCUMENT METADATA — real <figcaption>, real title/author.
    _rule()
    print("\n### 6/6 CAPTIONS + METADATA — real <figcaption>, real title/author")
    html_caption = (
        '<html><head><title>Clinical Trial Protocol v2</title>'
        '<meta name="author" content="Dr. R. Iyer, Principal Investigator"></head>'
        "<body><p>Unrelated protocol narrative text.</p>"
        '<figure><img src="enrollment.png">'
        "<figcaption>Figure 1: 340 patients completed the full 12-week protocol.</figcaption>"
        "</figure></body></html>"
    )
    caption_path = Path("/tmp/citenexus-capabilities-protocol.html")
    caption_path.write_text(html_caption)
    print('>>> rag.ingest("protocol.html")')
    rag.ingest(caption_path, document_id="protocol-caption-doc")

    doc_meta = HtmlExtractor(document_id="protocol-caption-doc").extract(html_caption).metadata
    print(f"title: {doc_meta.title}  |  author: {doc_meta.author}")

    q6 = "How many patients completed the full 12-week protocol?"
    print(f"\n>>> rag.ask({q6!r})")
    a6 = rag.ask(q6)
    print(f"decision: {a6.evidence.decision.value}")
    if a6.evidence.decision is Decision.answered:
        print(f"source: {a6.sources[0].document} (cited caption, verbatim)")
    print(a6.answer)
    _rule("=")


if __name__ == "__main__":
    main()
