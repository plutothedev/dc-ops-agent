# (C)
"""The dcops command."""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from dcops.agent import RunResult, ask_terminal, deny_all, run_incident_sync
from dcops.evals import run_agent_evals
from dcops.llm import ChatModel, OllamaModel
from dcops.report import format_report
from dcops.search import OllamaEmbedder, RunbookIndex, load_chunks, retrieval_metrics
from dcops.site import DataDirNotFound, list_scenarios
from dcops.trace_view import render_tree
from dcops.tracing import setup_tracing

GOLD = Path(__file__).resolve().parents[2] / "evals" / "retrieval_gold.jsonl"


def make_model(name: str) -> ChatModel:
    return OllamaModel(model=name)


def exit_code(result: RunResult) -> int:
    if result.stop_reason == "done":
        return 0
    return 2 if result.stop_reason == "model_error" else 1


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dcops", description="Local-model data center incident agent.")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("scenarios", help="list the alarm scenarios")
    r = sub.add_parser("run", help="investigate one scenario")
    r.add_argument("--scenario", required=True)
    r.add_argument("--model", default="qwen3:8b")
    r.add_argument("--max-steps", type=int, default=12)
    g = r.add_mutually_exclusive_group()
    g.add_argument("--yes-to-writes", action="store_true", help="approve every write without asking")
    g.add_argument("--deny-writes", action="store_true", help="deny every write without asking")
    r.add_argument("--out", type=Path, default=None, help="folder for work orders")
    r.add_argument("--trace", type=Path, default=None, help="trace file (JSONL)")
    r.add_argument("--embed", action="store_true", help="hybrid runbook search via Ollama embeddings")
    r.add_argument(
        "--draft-work-order", action="store_true",
        help="also ask the agent to draft a work order for the cause (the approver still decides)",
    )
    t = sub.add_parser("trace", help="print a trace as a tree")
    t.add_argument("path", type=Path)
    e = sub.add_parser("eval", help="run an eval")
    e.add_argument("which", choices=["retrieval", "agent"])
    e.add_argument("--embed", action="store_true", help="try hybrid search (retrieval)")
    e.add_argument("--runs", type=int, default=3, help="runs per scenario (agent)")
    e.add_argument("--model", default="qwen3:8b", help="model (agent)")
    e.add_argument("--scenario", action="append", default=None, help="limit to a scenario, repeatable (agent)")
    e.add_argument("--out", type=Path, default=None, help="results .md path (agent)")
    e.add_argument("--trace-dir", type=Path, default=None, help="one trace per run goes here (agent)")
    return p


def _cmd_scenarios(args) -> int:
    for name in list_scenarios():
        print(name)
    return 0


def _cmd_run(args) -> int:
    if args.scenario not in list_scenarios():
        print(f"error: unknown scenario {args.scenario!r} (see: dcops scenarios)", file=sys.stderr)
        return 2
    if args.max_steps < 1:
        print("error: --max-steps must be at least 1", file=sys.stderr)
        return 2
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = args.out or Path("out") / f"{args.scenario}-{stamp}"
    trace_path = args.trace or Path("traces") / f"{args.scenario}-{stamp}.jsonl"
    approver = deny_all if args.deny_writes else (lambda name, a: True) if args.yes_to_writes else ask_terminal
    try:
        provider = setup_tracing(trace_path)
    except OSError as e:
        print(f"error: cannot write trace: {e}", file=sys.stderr)
        return 2
    try:
        result = run_incident_sync(
            args.scenario,
            make_model(args.model),
            approver=approver,
            max_steps=args.max_steps,
            out_dir=out_dir,
            embed=args.embed,
            tracer=provider.get_tracer("dcops"),
            request_work_order=args.draft_work_order,
        )
    except Exception as e:
        print(f"error: {' '.join(str(e).split()) or type(e).__name__}", file=sys.stderr)
        return 2
    finally:
        provider.shutdown()
    if result.stop_reason == "model_error":
        print(f"error: {' '.join(result.report.split())}", file=sys.stderr)
        return 2
    print(format_report(result, scenario=args.scenario, out_dir=out_dir, trace_path=trace_path))
    return exit_code(result)


def _cmd_trace(args) -> int:
    if not args.path.exists():
        print(f"error: no such trace file: {args.path}", file=sys.stderr)
        return 2
    print(render_tree(args.path))
    return 0


def _cmd_eval(args) -> int:
    if args.which == "agent":
        return _eval_agent(args)
    if not GOLD.is_file():
        print(f"error: retrieval gold file not found at {GOLD}: run from a clone of the repo", file=sys.stderr)
        return 2
    index = RunbookIndex(load_chunks(), OllamaEmbedder() if args.embed else None)
    m = retrieval_metrics(index, GOLD)
    print(f"mode={index.mode}  hit@3={m['hit_at_3']:.3f}  MRR={m['mrr']:.3f}  n={m['n']}")
    return 0


def _eval_agent(args) -> int:
    known = list_scenarios()
    bad = [n for n in (args.scenario or []) if n not in known]
    if bad:
        print(f"error: unknown scenario {bad[0]!r} (see: dcops scenarios)", file=sys.stderr)
        return 2
    if args.runs < 1:
        print("error: --runs must be at least 1", file=sys.stderr)
        return 2
    results = Path(__file__).resolve().parents[2] / "evals" / "results"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = args.out or results / f"{stamp}-{args.model.replace(':', '-')}.md"
    try:
        summary = run_agent_evals(make_model(args.model), args.runs, out, args.scenario, args.trace_dir)
    except Exception as e:
        print(f"error: {' '.join(str(e).split()) or type(e).__name__}", file=sys.stderr)
        return 2
    if args.out is None:
        shutil.copyfile(out, results / "latest.md")
    t = summary["totals"]
    print(f"model={summary['model']}  passed={t['passed']}/{t['runs']}  model_errors={t['model_errors']}  wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return globals()[f"_cmd_{args.command}"](args)
    except DataDirNotFound as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
