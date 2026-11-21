# (C)
"""Plain-text incident report for the terminal."""
from __future__ import annotations

from pathlib import Path

from dcops.agent import RunResult, ToolRecord

# C0 controls except tab and newline, plus DEL and the C1 range: model-written text must
# not be able to move the cursor, clear the screen or retitle the terminal.
_CONTROL = {i: None for i in (*range(0x00, 0x20), *range(0x7F, 0xA0)) if i not in (0x09, 0x0A)}


def _clean(text: object) -> str:
    return str(text).translate(_CONTROL)


def _short_args(args: dict | str, limit: int = 60) -> str:
    if isinstance(args, dict):
        text = ", ".join(f"{k}={v}" for k, v in args.items())
    else:
        text = str(args)
    text = " ".join(_clean(text).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _evidence_line(r: ToolRecord) -> str:
    line = f"  {_clean(r.name)}({_short_args(r.args)}) [{r.approval}]"
    return line + " ERROR" if r.is_error else line


def _work_order(result: RunResult, out_dir: Path | None) -> str:
    calls = [r for r in result.tools if r.name == "draft_work_order"]
    if not calls:
        return "none requested"
    if any(r.approval in ("auto", "approved") and not r.is_error for r in calls):
        return f"written under {out_dir}" if out_dir is not None else "written"
    if any(r.approval == "denied" for r in calls):
        return "denied by operator, nothing written"
    return "requested but not written"


def format_report(result: RunResult, *, scenario: str, out_dir: Path | None, trace_path: Path | None) -> str:
    f = result.finding
    lines = [f"Incident report: {scenario}", ""]
    lines.append("Cause")
    if f.parsed and (f.cause_equipment or f.cause):
        lines.append(f"  {_clean(f.cause_equipment or 'unknown equipment')}: {_clean(f.cause)}")
    else:
        lines.append("  not determined")
    lines += ["", "Runbooks cited", "  " + (_clean(", ".join(f.runbook_ids)) if f.runbook_ids else "none")]
    lines += ["", "Evidence"]
    lines += [_evidence_line(r) for r in result.tools] or ["  no tool calls"]
    lines += ["", "Work order", f"  {_work_order(result, out_dir)}"]
    lines += ["", "Stop", f"  {result.stop_reason} after {result.steps} steps"]
    lines += ["", "Report", *(f"  {l}" if l else "" for l in _clean(result.report).strip().splitlines())]
    if trace_path is not None:
        lines += ["", f"Trace: {trace_path} (view with: dcops trace {trace_path})"]
    return "\n".join(lines)
