# (C)
from pathlib import Path

from dcops.search import (
    EmbedderUnavailable,
    RunbookIndex,
    load_chunks,
    retrieval_metrics,
)

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "evals" / "retrieval_gold.jsonl"
SECTIONS = ["Symptoms", "Immediate actions", "Diagnosis", "Recovery", "Escalation"]


def test_chunks_one_per_section():
    chunks = load_chunks()
    assert len(chunks) == 50
    assert {c.runbook_id for c in chunks} == {f"RB-{i:02d}" for i in range(1, 11)}
    assert {c.section for c in chunks} == set(SECTIONS)
    assert all(c.title and c.text and "Fictional sample" not in c.text for c in chunks)


def test_runbooks_have_fictional_notice_and_no_em_dash():
    for p in (ROOT / "data" / "runbooks").glob("RB-*.md"):
        text = p.read_text(encoding="utf-8")
        lines = text.splitlines()
        assert lines[0] == "<!-- (C) -->"
        first = next(l for l in lines if l.strip() and not l.startswith("<!--"))
        assert first.startswith("> Fictional sample runbook")
        assert chr(0x2014) not in text


def test_bm25_finds_the_obvious_runbook():
    idx = RunbookIndex(load_chunks())
    assert idx.mode == "bm25"
    assert idx.search("UPS running on battery after utility dip")[0].chunk.runbook_id == "RB-02"


def test_results_are_one_per_runbook():
    idx = RunbookIndex(load_chunks())
    hits = idx.search("breaker power battery temperature", k=10)
    ids = [h.chunk.runbook_id for h in hits]
    assert len(ids) == len(set(ids))


def test_gold_set_hit_at_3_bm25():
    m = retrieval_metrics(RunbookIndex(load_chunks()), GOLD)
    assert m["n"] == 15
    assert m["hit_at_3"] >= 0.9


def _rank_of(idx, rid, query):
    ids = [h.chunk.runbook_id for h in idx.search(query, k=10)]
    return ids.index(rid) if rid in ids else None


def test_hybrid_uses_embedder_and_fuses():
    chunks = load_chunks()
    query = "check the alarm and clear it and verify the unit"

    class FavorRB07:
        def embed(self, texts):
            return [[1.0, 0.0] if ("humidity" in t.lower() or t == query) else [0.0, 1.0] for t in texts]

    base = RunbookIndex(chunks)
    assert _rank_of(base, "RB-07", query) == 4  # fifth under BM25 alone
    hyb = RunbookIndex(chunks, FavorRB07())
    assert hyb.mode == "hybrid"
    top = [h.chunk.runbook_id for h in hyb.search(query, k=3)]
    assert "RB-07" in top


class Down:
    def embed(self, texts):
        raise EmbedderUnavailable("no ollama")


def test_embedder_failure_falls_back():
    idx = RunbookIndex(load_chunks(), Down())
    assert idx.mode == "bm25"
    assert idx.search("UPS on battery")


def test_query_time_failure_falls_back():
    calls = {"n": 0}

    class Flaky:
        def embed(self, texts):
            calls["n"] += 1
            if calls["n"] > 1:
                raise EmbedderUnavailable("gone")
            return [[1.0, 0.0] for _ in texts]

    idx = RunbookIndex(load_chunks(), Flaky())
    assert idx.mode == "hybrid"
    assert idx.search("UPS on battery")
    assert idx.mode == "bm25"
