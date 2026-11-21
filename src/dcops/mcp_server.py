# (C)
"""MCP server (stdio) exposing the fictional site and runbooks to an agent.

stdout is the MCP transport: never print to it. Diagnostics go to stderr.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .search import OllamaEmbedder, RunbookIndex, load_chunks
from .site import DataDirNotFound, Site, list_scenarios

MAX_STEPS = 20
MAX_STEP_CHARS = 500
MAX_SUMMARY_CHARS = 1000

_READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)

# Params are typed Any so bad values reach our own validation and come back as
# {"error": ...}; the advertised JSON schema still says what each one is.
_Int = lambda desc: Annotated[Any, Field(description=desc, json_schema_extra={"type": "integer"})]  # noqa: E731
_Str = lambda desc: Annotated[str, Field(description=desc)]  # noqa: E731
_EQUIPMENT_ID = "Equipment id, e.g. CRAH-03, as listed on an alarm or in another unit's upstream/downstream"


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _err(msg: str) -> dict:
    return {"error": msg}


def build_server(scenario: str, out_dir: Path, data_dir=None, embedder=None) -> FastMCP:
    site = Site.load(scenario, data_dir)
    index = RunbookIndex(load_chunks(data_dir), embedder)
    out_dir = Path(out_dir)
    mcp = FastMCP("dcops", log_level="WARNING")

    @mcp.tool(annotations=_READ)
    def list_active_alarms() -> list[dict]:
        """List the active alarms (id, equipment_id, severity, message, raised_at, and the
        operator's free-text note when there is one)."""
        return site.alarms()

    @mcp.tool(annotations=_READ)
    def get_alarm(alarm_id: _Str("Alarm id, e.g. AL-1001")) -> dict:
        """Get one alarm with its details by id, e.g. AL-1001."""
        a = site.alarm(alarm_id) if isinstance(alarm_id, str) else None
        return a if a is not None else _err(f"unknown alarm: {alarm_id}")

    @mcp.tool(annotations=_READ)
    def get_equipment(equipment_id: _Str(_EQUIPMENT_ID)) -> dict:
        """Get one piece of equipment: type, status, power path, upstream and downstream ids, and
        the sensor metrics get_sensor_history can read for it."""
        e = site.equipment(equipment_id) if isinstance(equipment_id, str) else None
        return e if e is not None else _err(f"unknown equipment: {equipment_id}")

    @mcp.tool(annotations=_READ)
    def get_sensor_history(
        equipment_id: _Str(_EQUIPMENT_ID),
        metric: _Str("Sensor metric name for that equipment, from get_equipment's metrics list"),
        minutes: _Int("Minutes of history, clamped to 1..1440") = 60,
    ) -> dict:
        """Get recent readings for one sensor. Points are [minutes_ago, value]."""
        if not _is_int(minutes):
            return _err("minutes must be an integer")
        if not isinstance(equipment_id, str) or site.equipment(equipment_id) is None:
            return _err(f"unknown equipment: {equipment_id}")
        h = site.sensor_history(equipment_id, metric, minutes) if isinstance(metric, str) else None
        if h is not None:
            return h
        valid = site.metrics(equipment_id)
        if not valid:
            return _err(f"unknown metric {metric!r}: {equipment_id} has no sensors in this scenario")
        return _err(f"unknown metric {metric!r} for {equipment_id}; valid metrics: {', '.join(valid)}")

    @mcp.tool(annotations=_READ)
    def search_runbooks(
        query: _Str("What to look for, in plain words, e.g. chilled water low flow"),
        k: _Int("Number of results, 1..10") = 3,
    ) -> list[dict] | dict:
        """Search the runbooks. Returns runbook_id, title, section, text, score."""
        if not isinstance(query, str) or not query.strip():
            return _err("query must be a non-empty string")
        if not _is_int(k) or not 1 <= k <= 10:
            return _err("k must be an integer from 1 to 10")
        return [
            {
                "runbook_id": h.chunk.runbook_id,
                "title": h.chunk.title,
                "section": h.chunk.section,
                "text": h.chunk.text,
                "score": h.score,
            }
            for h in index.search(query, k=k)
        ]

    @mcp.tool(annotations=_WRITE)
    def draft_work_order(
        equipment_id: _Str("Equipment id the work is for, e.g. CRAH-03"),
        summary: _Str("What is wrong and what the work fixes, at most 1000 characters"),
        steps: Annotated[Any, Field(description="1..20 non-empty step strings, each at most 500 characters",
                                    json_schema_extra={"type": "array", "items": {"type": "string"}})],
        priority: _Int("Priority 1 (highest) to 4"),
    ) -> dict:
        """Draft a work order file for a human to review. Never executes anything."""
        if not isinstance(equipment_id, str) or site.equipment(equipment_id) is None:
            return _err(f"unknown equipment: {equipment_id}")
        if not isinstance(summary, str) or not summary.strip():
            return _err("summary must be a non-empty string")
        if len(summary) > MAX_SUMMARY_CHARS:
            return _err(f"summary must be at most {MAX_SUMMARY_CHARS} characters")
        if not isinstance(steps, list) or not steps:
            return _err("steps must be a non-empty list of strings")
        if len(steps) > MAX_STEPS:
            return _err(f"steps must have at most {MAX_STEPS} items")
        for s in steps:
            if not isinstance(s, str) or not s.strip():
                return _err("each step must be a non-empty string")
            if len(s) > MAX_STEP_CHARS:
                return _err(f"each step must be at most {MAX_STEP_CHARS} characters")
        if not _is_int(priority) or not 1 <= priority <= 4:
            return _err("priority must be an integer from 1 to 4")
        folder = out_dir / "work_orders"
        folder.mkdir(parents=True, exist_ok=True)
        nums = [int(m.group(1)) for p in folder.glob("WO-*.json") if (m := re.fullmatch(r"WO-(\d+)\.json", p.name))]
        wo_id = f"WO-{max(nums, default=0) + 1}"
        path = folder / f"{wo_id}.json"
        doc = {
            "work_order_id": wo_id,
            "equipment_id": equipment_id,
            "summary": summary,
            "steps": list(steps),
            "priority": priority,
            "scenario": scenario,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "draft",
        }
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return {"work_order_id": wo_id, "path": str(path)}

    return mcp


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dcops.mcp_server", description="MCP server for the fictional site")
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--no-embed", action="store_true", help="BM25 only, never call Ollama")
    args = ap.parse_args(argv)
    try:
        known = list_scenarios()
    except DataDirNotFound as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.scenario not in known:
        print(f"unknown scenario: {args.scenario} (available: {', '.join(known)})", file=sys.stderr)
        return 2
    embedder = None if args.no_embed else OllamaEmbedder()
    build_server(args.scenario, args.out, embedder=embedder).run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
