"""Spike — ADR-0008 corpus/index reconciliation against REAL storage.

Throwaway prototype. Nothing under python/src is modified; this only *measures*
the existing seam.

Run:  cd python && uv run python ../spikes/adr-0008-reconcile/spike.py

Storage is real: a LocalFsBackend rooted in a tmp dir (the same StorageBackend
ABC S3Backend implements) plus a real on-disk LanceDB leaf store. Models are
deterministic fakes — reconciliation is pure bookkeeping, no model is involved.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from citenexus import CiteNexus
from citenexus.domain.partition import PartitionPath
from citenexus.ingest.pipeline import IngestPipeline
from citenexus.storage.manifest import EtagManifest, load_manifest
from citenexus.storage.paths import Layer, layer_prefix

PARTITION = PartitionPath.of(("workspace", "spike"))
SIGNALS = ["embedding", "text", "structure", "graph", "wiki"]

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


# --------------------------------------------------------------- fake models


class FakeEmbedder:
    """Deterministic hashing vectorizer — no network."""

    def embed(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode("utf-8")).digest()
        return [b / 255.0 for b in h[:16]]


# ------------------------------------------------------- the corpus manifest


@dataclass(frozen=True)
class ManifestEntry:
    document_id: str
    sha256: str
    version: str = "v1"
    current: bool = True
    source_uri: str = ""


@dataclass(frozen=True)
class CorpusManifest:
    """The caller-authored statement of the agreed corpus (ADR-0008)."""

    entries: tuple[ManifestEntry, ...]

    @property
    def current(self) -> dict[str, ManifestEntry]:
        return {e.document_id: e for e in self.entries if e.current}

    def superseded_hashes(self, document_id: str) -> set[str]:
        return {
            e.sha256 for e in self.entries if e.document_id == document_id and not e.current
        }


@dataclass(frozen=True)
class ReconcileReport:
    orphans: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    drifted: tuple[tuple[str, str, str], ...] = ()  # (doc_id, indexed_hash, declared_hash)

    @property
    def empty(self) -> bool:
        return not (self.orphans or self.missing or self.drifted)

    def as_tuple(self) -> tuple[Any, ...]:
        return (self.orphans, self.missing, self.drifted)

    def __str__(self) -> str:
        return (
            f"orphans={list(self.orphans)} missing={list(self.missing)} "
            f"drifted={[(d, i[:8], m[:8]) for d, i, m in self.drifted]}"
        )


# ------------------------------------------------ PART 1: enumerate the index


def enumerate_index(rag: CiteNexus) -> dict[str, str]:
    """document_id -> content hash, for everything currently indexed.

    Enumeration path used (all existing API, no new primitive):
      * python/src/citenexus/storage/manifest.py:31   EtagManifest.etags
        (document_id -> checksum), loaded via manifest.py:78 load_manifest with
        the key from ingest/pipeline.py:79 IngestPipeline.ETAG.
      * python/src/citenexus/storage/protocols.py:40  VectorStore.scan()
        rows carry `document_id` and `checksum` (written at
        ingest/pipeline.py:182-200).

    The etag manifest is the authoritative logical presence record (it is the
    revoke commit point, client.py:545); the vector scan is the physical one.
    They are unioned so a doc present in EITHER shows up.
    """
    manifest = load_manifest(rag._backend, rag.partition, IngestPipeline.ETAG, EtagManifest)
    assert isinstance(manifest, EtagManifest)
    indexed: dict[str, str] = dict(manifest.etags)
    for row in rag._store.scan():
        doc_id = str(row.get("document_id", ""))
        if doc_id and doc_id not in indexed:
            indexed[doc_id] = str(row.get("checksum", ""))
    return indexed


# ------------------------------------------------------------ PART 2: diff


def reconcile(rag: CiteNexus, manifest: CorpusManifest) -> ReconcileReport:
    """Read-only diff of the live index against the declared corpus."""
    indexed = enumerate_index(rag)
    declared = manifest.current

    orphans, missing, drifted = [], [], []
    for doc_id, indexed_hash in sorted(indexed.items()):
        entry = declared.get(doc_id)
        if entry is None:
            # A doc whose id is not declared AT ALL is an orphan. A doc declared
            # only as a superseded version is drift, not an orphan (ADR-0008).
            if any(e.document_id == doc_id for e in manifest.entries):
                drifted.append((doc_id, indexed_hash, ""))
            else:
                orphans.append(doc_id)
        elif entry.sha256 != indexed_hash:
            drifted.append((doc_id, indexed_hash, entry.sha256))
    for doc_id in sorted(declared):
        if doc_id not in indexed:
            missing.append(doc_id)

    return ReconcileReport(tuple(orphans), tuple(missing), tuple(drifted))


def assert_disjoint(report: ReconcileReport, label: str) -> None:
    o, m, d = set(report.orphans), set(report.missing), {x[0] for x in report.drifted}
    check(
        f"{label}: sets disjoint",
        not (o & m or o & d or m & d),
        f"o∩m={o & m} o∩d={o & d} m∩d={m & d}",
    )


# ------------------------------------------------------- PART 4: remediation


def remediate(rag: CiteNexus, report: ReconcileReport) -> list[Any]:
    """Consume a report and remove ORPHANS ONLY, through the existing revoke
    path (``client.delete`` -> ``delete.py``). Never called from reconcile.

    `missing` needs an ingest and `drifted` needs a re-ingest — neither is a
    deletion, so neither is touched here.
    """
    return [rag.delete(document_id) for document_id in report.orphans]


# -------------------------------------------------------------- layer probe


def layer_keys(rag: CiteNexus) -> dict[str, list[str]]:
    """Every storage key, grouped by layer + the vector rows (residue probe)."""
    b = rag._backend
    out = {
        layer.value: b.list_prefix(layer_prefix(layer, rag.partition))
        for layer in (Layer.raw, Layer.knowledge, Layer.manifests, Layer.graph)
    }
    # the wiki lives under knowledge/<P>/wiki (wiki/store.py:96) — already covered
    # by out["knowledge"]. Probe file CONTENTS too: a key can be gone while the
    # document id survives inside index.json / log.md / the graph blob.
    out["contents"] = [
        f"{k}::{b.get_bytes(k).decode('utf-8', 'replace')[:4000]}"
        for layer in ("knowledge", "graph", "manifests")
        for k in out[layer]
        if not k.endswith("log.md")  # the wiki log is an append-only audit trail
    ]
    out["vector_rows"] = [str(r.get("eu_id")) for r in rag._store.scan()]
    out["lexical_rows"] = [
        str(r.get("eu_id")) for r in _bm25_all(rag)
    ]
    return out


def _bm25_all(rag: CiteNexus) -> list[dict[str, Any]]:
    """The lexical/BM25 index is derived from scan(); probe it via a query that
    matches every fixture doc."""
    from citenexus.storage.bm25 import Bm25TextSearch

    return Bm25TextSearch(rag._store).search_text("the clause obligation tenant", limit=100)


# ------------------------------------------------------------------ harness


DOCS = {
    "lease": "The tenant shall indemnify the landlord for any damage to the premises.",
    "policy": "The employee shall not disclose confidential information to third parties.",
    "ghost": "This memo was never part of the agreed corpus at all.",
    "crashed": "A document whose ingest was interrupted before it committed.",
    "drifty": "Original text of the drifting document, version one, clause A.",
    "superseded": "Version one of the superseded document, clause A obligation.",
}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_rag(root: Path, *, vector_store: Any = None) -> CiteNexus:
    return CiteNexus(
        root,
        partition=PARTITION,
        signals=SIGNALS,
        embedder=FakeEmbedder(),
        vector_store=vector_store,
    )


class ExplodingStore:
    """Wraps a real store and blows up on upsert — an interrupted ingest."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.armed = True

    def upsert(self, rows: Any) -> None:
        if self.armed:
            raise RuntimeError("simulated crash mid-ingest (process killed)")
        self._inner.upsert(rows)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="adr0008-"))
    print(f"real storage root: {root}\n")

    rag = make_rag(root)

    print("PART 1 — can the index be enumerated?")
    for doc_id in ("lease", "policy"):
        rag.ingest(text=DOCS[doc_id], document_id=doc_id)
    idx = enumerate_index(rag)
    check("enumerate_index returns doc_id -> content hash", idx == {
        "lease": sha(DOCS["lease"]), "policy": sha(DOCS["policy"])
    }, str({k: v[:8] for k, v in idx.items()}))
    check(
        "hashes agree between etag manifest and vector rows",
        all(
            str(r["checksum"]) == idx[str(r["document_id"])]
            for r in rag._store.scan()
        ),
    )

    print("\nPART 2/3 — drift scenarios on a real store")
    # clean corpus first
    clean_manifest = CorpusManifest((
        ManifestEntry("lease", sha(DOCS["lease"])),
        ManifestEntry("policy", sha(DOCS["policy"])),
    ))
    rep = reconcile(rag, clean_manifest)
    check("clean corpus -> empty report", rep.empty, str(rep))
    assert_disjoint(rep, "clean")

    # (a) ghost document — ingested, never declared
    rag.ingest(text=DOCS["ghost"], document_id="ghost")

    # (b) crashed ingest — declared, ingest interrupted before commit
    crashed_store = ExplodingStore(rag._store)
    crashed_rag = make_rag(root, vector_store=crashed_store)
    crashed_error = ""
    try:
        crashed_rag.ingest(text=DOCS["crashed"], document_id="crashed")
    except RuntimeError as exc:  # the simulated kill
        crashed_error = str(exc)
    check("interrupted ingest raised (simulated crash)", bool(crashed_error), crashed_error)

    # (c) drifted — ingested v1, source changed afterwards
    rag.ingest(text=DOCS["drifty"], document_id="drifty")
    rag.ingest(text="Rewritten text of the drifting document, clause B.", document_id="drifty")

    # (d) superseded — indexed v1, manifest designates v2 current
    rag.ingest(text=DOCS["superseded"], document_id="superseded")

    manifest = CorpusManifest((
        ManifestEntry("lease", sha(DOCS["lease"])),
        ManifestEntry("policy", sha(DOCS["policy"])),
        ManifestEntry("crashed", sha(DOCS["crashed"])),
        ManifestEntry("drifty", sha(DOCS["drifty"])),
        ManifestEntry("superseded", sha(DOCS["superseded"]), version="v1", current=False),
        ManifestEntry("superseded", sha("Version two of the superseded document."),
                      version="v2", current=True),
    ))

    rep = reconcile(rag, manifest)
    print(f"  report: {rep}")
    check("(a) ghost document -> orphan", "ghost" in rep.orphans)
    check("(b) crashed ingest -> missing", "crashed" in rep.missing)
    check("(c) changed source -> drifted", "drifty" in {d for d, _, _ in rep.drifted})
    check("(d) superseded version -> drifted, not orphan",
          "superseded" in {d for d, _, _ in rep.drifted} and "superseded" not in rep.orphans)
    assert_disjoint(rep, "drift")

    # crashed-ingest residue: did the aborted run leave artifacts behind?
    keys = layer_keys(rag)
    crashed_raw = [k for k in keys["raw"] if sha(DOCS["crashed"]) in k]
    crashed_struct = [k for k in keys["knowledge"] if "crashed" in k]
    check(
        "crashed ingest leaves residue (documented, not asserted-clean)",
        True,
        f"raw={crashed_raw} structure={crashed_struct}",
    )

    # idempotence
    rep2 = reconcile(rag, manifest)
    check("reconcile is idempotent (two runs identical)", rep.as_tuple() == rep2.as_tuple())
    check("reconcile mutated nothing", layer_keys(rag)["vector_rows"] == keys["vector_rows"])

    # ------------------------------------------------ revoke residue probe
    print("\nPART 3e — revoke residue probe (every layer)")
    rag.ingest(text="A disposable clause about the tenant obligation.", document_id="victim")
    rag.ingest(text="Victim revision two: a different tenant obligation clause.",
               document_id="victim")  # gives the doc a superseded raw blob
    before = layer_keys(rag)
    result = rag.delete("victim")
    after = layer_keys(rag)
    check("delete reported deleted", result.status == "deleted", str(result.n_units))

    residue: dict[str, list[str]] = {}
    for layer, ks in after.items():
        hit = [k for k in ks if "victim" in k]
        if hit:
            residue[layer] = hit
    # content-addressed raw blobs are not named after the doc — check by hash
    stale_hash = sha("A disposable clause about the tenant obligation.")
    live_hash = sha("Victim revision two: a different tenant obligation clause.")
    stale_blob = [k for k in after["raw"] if stale_hash in k]
    live_blob = [k for k in after["raw"] if live_hash in k]
    if stale_blob:
        residue["raw (superseded blob, by hash)"] = stale_blob
    if live_blob:
        residue["raw (current blob, by hash)"] = live_blob

    for layer, hit in residue.items():
        print(f"    RESIDUE in {layer}: {hit}")
    check("revoke leaves no residue in ANY layer", not residue,
          "see RESIDUE lines above" if residue else "")
    check("revoke removed vector rows",
          len(after["vector_rows"]) < len(before["vector_rows"]))
    check("revoke removed lexical rows",
          not [r for r in after["lexical_rows"] if r.startswith("victim")])

    # ------------------------------------------------ PART 4: remediation
    print("\nPART 4 — remediation through delete.py (never inside reconcile)")
    rep = reconcile(rag, manifest)
    removed = remediate(rag, rep)
    check("orphans removed via existing revoke path",
          all(r.status == "deleted" for r in removed), str([r.document_id for r in removed]))
    rep_after = reconcile(rag, manifest)
    check("post-remediation report has no orphans", not rep_after.orphans, str(rep_after))
    check("remediation did not create new missing/drifted",
          set(rep_after.missing) == set(rep.missing)
          and {d for d, _, _ in rep_after.drifted} == {d for d, _, _ in rep.drifted},
          str(rep_after))

    # a fully-declared, fully-clean corpus after remediation
    print("\nfinal — reconcile against a manifest that matches reality")
    live = enumerate_index(rag)
    truth = CorpusManifest(tuple(ManifestEntry(d, h) for d, h in live.items()))
    rep_final = reconcile(rag, truth)
    check("matching manifest -> empty report", rep_final.empty, str(rep_final))
    assert_disjoint(rep_final, "final")

    shutil.rmtree(root, ignore_errors=True)
    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
