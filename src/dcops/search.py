# (C)
"""Runbook chunking and hybrid (BM25 + embedding) search."""
from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from dcops.site import data_dir as _data_dir

K1 = 1.5
B = 0.75
RRF_K = 60
_TOKEN = re.compile(r"[a-z0-9]+")


class EmbedderUnavailable(Exception):
    """The embedding backend could not be reached or returned an error."""


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class Chunk:
    runbook_id: str
    title: str
    section: str
    text: str


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float


def load_chunks(data_dir: Path | None = None) -> list[Chunk]:
    root = Path(data_dir) if data_dir else _data_dir()
    chunks: list[Chunk] = []
    for path in sorted((root / "runbooks").glob("RB-*.md")):
        runbook_id = "-".join(path.stem.split("-")[:2])
        title = runbook_id
        section: str | None = None
        buf: list[str] = []

        def flush() -> None:
            if section is not None:
                text = "\n".join(buf).strip()
                if text:
                    chunks.append(Chunk(runbook_id, title, section, text))

        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                flush()
                section, buf = line[3:].strip(), []
            elif line.startswith("# "):
                title = re.sub(r"^RB-\d+:\s*", "", line[2:].strip())
            elif section is not None:
                buf.append(line)
        flush()
    return chunks


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _doc_text(c: Chunk) -> str:
    return f"{c.title} {c.section} {c.text}"


class _BM25:
    def __init__(self, docs: list[list[str]]):
        self.docs = [Counter(d) for d in docs]
        self.lens = [len(d) for d in docs]
        self.avg = (sum(self.lens) / len(docs)) if docs else 0.0
        df: Counter[str] = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for tf, ln in zip(self.docs, self.lens):
            s = 0.0
            for t in query:
                f = tf.get(t)
                if not f:
                    continue
                norm = f + K1 * (1 - B + B * ln / self.avg)
                s += self.idf[t] * f * (K1 + 1) / norm
            out.append(s)
        return out


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _ranking(scores: list[float]) -> list[int]:
    return sorted(range(len(scores)), key=lambda i: (-scores[i], i))


class RunbookIndex:
    def __init__(self, chunks: list[Chunk], embedder: Embedder | None = None):
        self.chunks = list(chunks)
        self._bm25 = _BM25([_tokens(_doc_text(c)) for c in self.chunks])
        self._embedder = embedder
        self._vectors: list[list[float]] | None = None
        self.mode = "bm25"
        if embedder is not None:
            try:
                vecs = embedder.embed([_doc_text(c) for c in self.chunks])
                if len(vecs) != len(self.chunks):
                    raise EmbedderUnavailable("embedding count mismatch")
                self._vectors = vecs
                self.mode = "hybrid"
            except EmbedderUnavailable:
                self._embedder = None

    def search(self, query: str, k: int = 3) -> list[Hit]:
        if not self.chunks:
            return []
        bm = self._bm25.scores(_tokens(query))
        order = _ranking(bm)
        scores = {i: 0.0 for i in range(len(self.chunks))}
        fused = False
        if self.mode == "hybrid" and self._embedder is not None and self._vectors is not None:
            try:
                qv = self._embedder.embed([query])[0]
                cos = [_cosine(qv, v) for v in self._vectors]
                for rank, i in enumerate(_ranking(cos), start=1):
                    scores[i] += 1 / (RRF_K + rank)
                for rank, i in enumerate(order, start=1):
                    scores[i] += 1 / (RRF_K + rank)
                fused = True
            except (EmbedderUnavailable, IndexError):
                self.mode = "bm25"
        if fused:
            order = sorted(scores, key=lambda i: (-scores[i], i))
            final = scores
        else:
            final = dict(enumerate(bm))
        hits: list[Hit] = []
        seen: set[str] = set()
        for i in order:
            c = self.chunks[i]
            if c.runbook_id in seen:
                continue
            if not fused and final[i] <= 0:
                break
            seen.add(c.runbook_id)
            hits.append(Hit(c, float(final[i])))
            if len(hits) >= k:
                break
        return hits


class OllamaEmbedder:
    def __init__(self, base_url: str | None = None, model: str = "nomic-embed-text", timeout: float = 10.0):
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
        self.model = model
        self.timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            r = httpx.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": texts},
                timeout=self.timeout,
            )
            r.raise_for_status()
            vecs = r.json()["embeddings"]
        except (httpx.HTTPError, ValueError, KeyError) as e:
            raise EmbedderUnavailable(str(e)) from e
        return vecs


def retrieval_metrics(index: RunbookIndex, gold_path: Path | str) -> dict:
    rows = [
        json.loads(line)
        for line in Path(gold_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    hits3 = 0
    rr = 0.0
    for row in rows:
        ids = [h.chunk.runbook_id for h in index.search(row["query"], k=3)]
        if row["runbook_id"] in ids:
            hits3 += 1
            rr += 1 / (ids.index(row["runbook_id"]) + 1)
    n = len(rows)
    return {"hit_at_3": hits3 / n if n else 0.0, "mrr": rr / n if n else 0.0, "n": n}
