# (C)
"""Print a JSONL trace as an indented tree."""
from __future__ import annotations

import json
from pathlib import Path


def render_tree(path: Path) -> str:
    spans: list[dict] = []
    bad = 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            row["name"], row["trace_id"], row["span_id"], row["start_ns"], row["end_ns"]
            spans.append(row)
        except (ValueError, KeyError, TypeError):
            bad += 1

    by_trace: dict[str, list[dict]] = {}
    for s in spans:
        by_trace.setdefault(s["trace_id"], []).append(s)

    out: list[str] = []
    for trace_spans in by_trace.values():
        ids = {s["span_id"] for s in trace_spans}
        children: dict[str | None, list[dict]] = {}
        for s in sorted(trace_spans, key=lambda s: s["start_ns"]):
            parent = s.get("parent_id")
            children.setdefault(parent if parent in ids else None, []).append(s)

        def walk(parent: str | None, depth: int) -> None:
            for s in children.get(parent, []):
                out.append("  " * depth + _line(s))
                walk(s["span_id"], depth + 1)

        walk(None, 0)
    if bad:
        out.append(f"({bad} unreadable lines skipped)")
    return "\n".join(out)


def _line(s: dict) -> str:
    ms = (s["end_ns"] - s["start_ns"]) / 1e6
    a = s.get("attributes") or {}
    name = s["name"]
    if name == "llm.chat":
        detail = (
            f"model={a.get('gen_ai.request.model')} "
            f"tokens={a.get('gen_ai.usage.input_tokens', '?')}/{a.get('gen_ai.usage.output_tokens', '?')}"
        )
    elif name == "tool.call":
        detail = f"tool={a.get('tool.name')} approval={a.get('tool.approval')} error={a.get('tool.is_error')}"
    elif name == "agent.run":
        detail = f"stop={a.get('dcops.stop_reason')} steps={a.get('dcops.steps')}"
    else:
        detail = ""
    status = "" if s.get("status") in (None, "UNSET", "OK") else f" [{s['status']}]"
    return f"{name}  {ms:.1f} ms  {detail}{status}".rstrip()
