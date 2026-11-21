# (C)
"""Tracing tests: in-memory exporter for the span tree, JSONL exporter and viewer on disk."""
import asyncio
import json
import re

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from dcops.agent import run_incident
from dcops.llm import AssistantTurn, ScriptedModel, ToolCall, Usage
from dcops.trace_view import render_tree
from dcops.tracing import JsonlSpanExporter, setup_tracing

SC = "crah-fan-failure"
FINAL = (
    "CRAH-03 tripped.\n\n```json\n"
    '{"cause_equipment": "CRAH-03", "cause": "fan overload", "runbook_ids": ["RB-01"]}\n```'
)
WORK_ORDER = {"equipment_id": "CRAH-03", "summary": "Replace fan motor", "steps": ["Isolate"], "priority": 2}


def tc(i, name, args=None):
    return ToolCall(id=f"t{i}", name=name, arguments=json.dumps(args or {}))


def traced_run(turns, tmp_path, provider):
    tracer = provider.get_tracer("test")
    model = ScriptedModel(turns)
    return asyncio.run(
        asyncio.wait_for(run_incident(SC, model, out_dir=tmp_path, tracer=tracer), 120)
    )


def mem_provider():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


def test_run_produces_expected_span_tree(tmp_path):
    provider, exporter = mem_provider()
    turns = [
        AssistantTurn(text="", tool_calls=[tc(1, "list_active_alarms"), tc(2, "get_equipment", {"equipment_id": "CRAH-03"})],
                      usage=Usage(10, 5)),
        AssistantTurn(text=FINAL),
    ]
    result = traced_run(turns, tmp_path, provider)
    spans = exporter.get_finished_spans()
    roots = [s for s in spans if s.name == "agent.run"]
    assert len(roots) == 1
    root = roots[0]
    assert root.parent is None
    assert root.attributes["dcops.scenario"] == SC
    assert root.attributes["dcops.steps"] == result.steps == 2
    assert root.attributes["dcops.stop_reason"] == "done"
    assert "gen_ai.request.model" in root.attributes

    children = sorted((s for s in spans if s is not root), key=lambda s: s.start_time)
    assert [s.name for s in children] == ["llm.chat", "tool.call", "tool.call", "llm.chat"]
    assert all(s.parent.span_id == root.context.span_id for s in children)
    chat1, tool1, tool2, chat2 = children
    assert chat1.attributes["gen_ai.usage.input_tokens"] == 10
    assert chat1.attributes["gen_ai.usage.output_tokens"] == 5
    assert chat1.attributes["dcops.tool_calls"] == 2
    assert "gen_ai.usage.input_tokens" not in chat2.attributes  # usage None: not set
    assert chat2.attributes["dcops.tool_calls"] == 0
    assert tool1.attributes["tool.name"] == "list_active_alarms"
    assert tool1.attributes["tool.approval"] == "auto"
    assert tool1.attributes["tool.is_error"] is False
    assert tool1.attributes["tool.result_chars"] > 0
    assert json.loads(tool2.attributes["tool.arguments"]) == {"equipment_id": "CRAH-03"}


def test_denied_write_is_on_the_span(tmp_path):
    provider, exporter = mem_provider()
    turns = [
        AssistantTurn(text="", tool_calls=[tc(1, "draft_work_order", WORK_ORDER)]),
        AssistantTurn(text=FINAL),
    ]
    traced_run(turns, tmp_path, provider)
    tool = [s for s in exporter.get_finished_spans() if s.name == "tool.call"]
    assert len(tool) == 1
    assert tool[0].attributes["tool.name"] == "draft_work_order"
    assert tool[0].attributes["tool.approval"] == "denied"
    assert tool[0].attributes["tool.is_error"] is True


def test_model_error_marks_run_span_error(tmp_path):
    provider, exporter = mem_provider()

    class Boom:
        name = "boom"

        def complete(self, messages, tools):
            raise RuntimeError("down")

    tracer = provider.get_tracer("test")
    result = asyncio.run(run_incident(SC, Boom(), out_dir=tmp_path, tracer=tracer))
    assert result.stop_reason == "model_error"
    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert spans["agent.run"].status.status_code.name == "ERROR"
    assert any(e.name == "exception" for e in spans["llm.chat"].events)


def test_tool_arguments_cut_to_500_chars(tmp_path):
    provider, exporter = mem_provider()
    turns = [
        AssistantTurn(text="", tool_calls=[tc(1, "search_runbooks", {"query": "x" * 2000})]),
        AssistantTurn(text=FINAL),
    ]
    traced_run(turns, tmp_path, provider)
    tool = [s for s in exporter.get_finished_spans() if s.name == "tool.call"][0]
    assert len(tool.attributes["tool.arguments"]) == 500


def test_jsonl_exporter_and_render_tree(tmp_path):
    path = tmp_path / "deep" / "trace.jsonl"
    provider = setup_tracing(path)
    turns = [
        AssistantTurn(text="", tool_calls=[tc(1, "list_active_alarms")], usage=Usage(7, 3)),
        AssistantTurn(text=FINAL),
    ]
    traced_run(turns, tmp_path, provider)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 4
    for r in rows:
        assert set(r) >= {"name", "trace_id", "span_id", "parent_id", "start_ns", "end_ns", "attributes", "status"}
        assert re.fullmatch(r"[0-9a-f]{32}", r["trace_id"]) and re.fullmatch(r"[0-9a-f]{16}", r["span_id"])
    root = [r for r in rows if r["name"] == "agent.run"][0]
    assert root["parent_id"] is None
    assert all(r["parent_id"] == root["span_id"] for r in rows if r is not root)

    out = render_tree(path)
    print(out)
    lines = out.splitlines()
    assert lines[0].startswith("agent.run")
    assert any(l.startswith("  llm.chat") and "tokens" in l for l in lines)
    assert any(l.startswith("  tool.call") and "list_active_alarms" in l and "auto" in l for l in lines)
    assert all(re.search(r"\d+(\.\d+)? ms", l) for l in lines if l.strip())
    assert "stop=done" in lines[0]


def test_exporter_empty_batch_and_bad_lines(tmp_path):
    path = tmp_path / "t.jsonl"
    exp = JsonlSpanExporter(path)
    exp.export([])
    exp.shutdown()
    path.write_text('not json\n{"name": 1\n', encoding="utf-8")
    out = render_tree(path)
    assert "2 unreadable" in out


def test_run_span_records_search_mode(tmp_path, monkeypatch):
    from dcops import agent

    real = agent._server_params
    # embed=True must not reach the server here: the test never calls Ollama.
    monkeypatch.setattr(agent, "_server_params", lambda sc, out, data, embed: real(sc, out, data, False))
    modes = []
    for embed in (False, True):
        provider, exporter = mem_provider()
        model = ScriptedModel([AssistantTurn(text=FINAL)])
        asyncio.run(asyncio.wait_for(
            run_incident(SC, model, out_dir=tmp_path, embed=embed, tracer=provider.get_tracer("t")), 120))
        root = [s for s in exporter.get_finished_spans() if s.name == "agent.run"][0]
        modes.append(root.attributes["dcops.search_mode"])
    assert modes == ["bm25", "hybrid"]
