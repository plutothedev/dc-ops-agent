# (C)
"""Agent loop tests: a ScriptedModel drives the real MCP server over stdio (BM25 only)."""
import asyncio
import io
import json
from pathlib import Path

import pytest
from mcp.types import Tool, ToolAnnotations

from dcops import agent
from dcops.agent import ToolRecord, ask_terminal, deny_all, is_read_only, parse_finding, run_incident
from dcops.llm import AssistantTurn, ModelUnavailable, ScriptedModel, ToolCall

REPO = Path(__file__).resolve().parents[1]
SC = "crah-fan-failure"
FINAL = (
    "CRAH-03 tripped on fan motor overload, so the racks it cools are warming.\n\n"
    "```json\n"
    '{"cause_equipment": "CRAH-03", "cause": "CRAH-03 fan motor overload trip", "runbook_ids": ["RB-01"]}\n'
    "```"
)
WORK_ORDER = {"equipment_id": "CRAH-03", "summary": "Replace fan motor", "steps": ["Isolate", "Swap"], "priority": 2}


class RecordingModel(ScriptedModel):
    """ScriptedModel that also keeps the tool schemas it was offered."""

    def complete(self, messages, tools):
        self.tools = tools
        return super().complete(messages, tools)


_ids = iter(range(1, 10_000))


def call(name: str, args: dict | None = None, raw: str | None = None) -> ToolCall:
    return ToolCall(id=f"c{next(_ids)}", name=name, arguments=raw if raw is not None else json.dumps(args or {}))


def turn(*calls: ToolCall, text: str = "") -> AssistantTurn:
    return AssistantTurn(text=text, tool_calls=list(calls))


def run(turns, scenario=SC, model=None, **kw):
    model = model or RecordingModel(turns)
    result = asyncio.run(asyncio.wait_for(run_incident(scenario, model, **kw), 120))
    return result, model


def tool_messages(model) -> list[dict]:
    """Every tool message the model saw by the end of the run, in order."""
    return [m for m in model.calls[-1] if m["role"] == "tool"]


def work_orders(out: Path) -> list[Path]:
    d = out / "work_orders"
    return sorted(d.iterdir()) if d.exists() else []


def test_happy_path_done(tmp_path):
    c1 = call("list_active_alarms")
    c2 = call("get_equipment", {"equipment_id": "CRAH-03"})
    c3 = call("search_runbooks", {"query": "CRAH fan failure"})
    result, model = run([turn(c1), turn(c2), turn(c3), turn(text=FINAL)], out_dir=tmp_path)

    assert result.stop_reason == "done" and result.steps == 4
    assert result.finding.parsed is True
    assert result.finding.cause_equipment == "CRAH-03"
    assert result.finding.runbook_ids == ["RB-01"]
    assert result.report.startswith("CRAH-03 tripped") and "```" not in result.report
    assert [(r.name, r.approval, r.is_error) for r in result.tools] == [
        ("list_active_alarms", "auto", False),
        ("get_equipment", "auto", False),
        ("search_runbooks", "auto", False),
    ]

    # The model is offered the server's six tools in OpenAI function form.
    offered = {t["function"]["name"]: t for t in model.tools}
    assert len(offered) == 6 and all(t["type"] == "function" for t in offered.values())
    assert offered["get_equipment"]["function"]["parameters"]["required"] == ["equipment_id"]

    # History: system, user, then assistant turns with tool_calls and tool results.
    last = model.calls[-1]
    assert [m["role"] for m in last[:4]] == ["system", "user", "assistant", "tool"]
    assert last[2]["tool_calls"] == [
        {"id": c1.id, "type": "function", "function": {"name": "list_active_alarms", "arguments": "{}"}}
    ]
    first_result = json.loads(last[3]["content"])
    assert last[3]["tool_call_id"] == c1.id
    assert first_result["tool"] == "list_active_alarms"
    assert first_result["result"][0]["equipment_id"] == "CRAH-03"
    runbooks = json.loads(tool_messages(model)[2]["content"])["result"]
    assert runbooks[0]["runbook_id"] == "RB-01"


def test_write_denied_by_default(tmp_path):
    c = call("draft_work_order", WORK_ORDER)
    result, model = run([turn(c), turn(text=FINAL)], out_dir=tmp_path)

    assert result.stop_reason == "done"
    assert result.tools == [ToolRecord("draft_work_order", WORK_ORDER, "denied", True, result.tools[0].result_chars)]
    assert work_orders(tmp_path) == []
    assert json.loads(tool_messages(model)[0]["content"]) == {
        "tool": "draft_work_order", "error": "denied by operator: not run",
    }


def test_write_approved_writes_file(tmp_path):
    asked = []

    def approve(name, args):
        asked.append((name, args))
        return True

    calls = [call("list_active_alarms"), call("draft_work_order", WORK_ORDER)]
    result, model = run([turn(*calls), turn(text=FINAL)], approver=approve, out_dir=tmp_path)

    assert asked == [("draft_work_order", WORK_ORDER)]  # read tools never reach the approver
    assert [r.approval for r in result.tools] == ["auto", "approved"]
    assert [p.name for p in work_orders(tmp_path)] == ["WO-1.json"]
    assert json.loads(tool_messages(model)[1]["content"])["result"]["work_order_id"] == "WO-1"


def test_approver_errors_and_non_true_answers_are_denials(tmp_path):
    answers = iter([RuntimeError("approval service down"), "yes"])

    def flaky(name, args):
        a = next(answers)
        if isinstance(a, Exception):
            raise a
        return a  # truthy, but not True

    calls = [call("draft_work_order", WORK_ORDER), call("draft_work_order", {**WORK_ORDER, "priority": 3})]
    result, _ = run([turn(*calls), turn(text=FINAL)], approver=flaky, out_dir=tmp_path)

    assert [r.approval for r in result.tools] == ["denied", "denied"]
    assert work_orders(tmp_path) == []


def test_bad_json_args_and_unknown_tool_are_blocked_not_fatal(tmp_path):
    bad = [
        call("get_equipment", raw='{"equipment_id": "CRAH-03"'),
        call("get_equipment", raw='["CRAH-03"]'),
        call("reboot_everything", {}),
    ]
    result, model = run([turn(*bad), turn(call("list_active_alarms")), turn(text=FINAL)], out_dir=tmp_path)

    assert result.stop_reason == "done" and result.finding.parsed
    assert [(r.approval, r.is_error) for r in result.tools] == [
        ("blocked", True), ("blocked", True), ("blocked", True), ("auto", False),
    ]
    assert result.tools[0].args == '{"equipment_id": "CRAH-03"'  # raw text kept for the record
    errors = [json.loads(m["content"]) for m in tool_messages(model)[:3]]
    assert "not valid JSON" in errors[0]["error"]
    assert "JSON object" in errors[1]["error"]
    assert errors[2]["tool"] == "reboot_everything" and "unknown tool" in errors[2]["error"]
    assert "list_active_alarms" in errors[2]["error"]  # tells the model what exists


def test_repeat_guard(tmp_path):
    a = {"equipment_id": "CRAH-03", "metric": "fan_speed_rpm"}
    b = {"metric": "fan_speed_rpm", "equipment_id": "CRAH-03"}  # same call, other key order
    turns = [turn(call("get_sensor_history", a)), turn(call("get_sensor_history", b)),
             turn(call("get_sensor_history", a)), turn(text=FINAL)]
    result, model = run(turns, out_dir=tmp_path)

    assert result.stop_reason == "repeat_loop" and result.steps == 3
    assert len(model.calls) == 3  # the scripted final answer was never requested
    assert [r.approval for r in result.tools] == ["auto", "blocked", "blocked"]
    assert result.finding.parsed is False
    second = json.loads(tool_messages(model)[1]["content"])
    assert second["error"] == "already called with these arguments; use the earlier result"


def test_step_cap(tmp_path):
    turns = [turn(call("list_active_alarms")), turn(call("get_alarm", {"alarm_id": "AL-1001"})),
             turn(call("get_equipment", {"equipment_id": "CRAH-03"})), turn(text=FINAL)]
    result, model = run(turns, max_steps=3, out_dir=tmp_path)

    assert result.stop_reason == "step_cap" and result.steps == 3
    assert len(model.calls) == 3 and len(result.tools) == 3
    assert result.finding.parsed is False


def test_long_result_truncated(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "_payload", lambda result: "x" * 20_000)
    result, model = run([turn(call("list_active_alarms")), turn(text=FINAL)], out_dir=tmp_path)

    content = tool_messages(model)[0]["content"]
    assert len(content) == agent.MAX_RESULT_CHARS + len("[truncated]")
    assert content.endswith("[truncated]")
    assert result.tools[0].result_chars > agent.MAX_RESULT_CHARS  # the record keeps the full size


def test_cap_boundary():
    assert agent._cap("a" * agent.MAX_RESULT_CHARS) == "a" * agent.MAX_RESULT_CHARS
    assert agent._cap("a" * (agent.MAX_RESULT_CHARS + 1)).endswith("a[truncated]")


def test_unparsed_final_answer(tmp_path):
    text = "CRAH-03 is the cause. Follow RB-01."
    result, _ = run([turn(text=text)], out_dir=tmp_path)

    assert result.stop_reason == "done" and result.steps == 1
    assert result.finding.parsed is False and result.finding.cause_equipment is None
    assert result.report == text


def test_parse_finding_rules():
    block = lambda body, lang="json": f"```{lang}\n{body}\n```"  # noqa: E731
    good = '{"cause_equipment": "CHWP-1", "cause": "pump stopped", "runbook_ids": ["RB-04"]}'
    report, f = parse_finding("Report.\n\n" + block(good))
    assert (report, f.cause_equipment, f.cause, f.runbook_ids, f.parsed) == (
        "Report.", "CHWP-1", "pump stopped", ["RB-04"], True)

    first = good.replace("CHWP-1", "CH-1")
    assert parse_finding(block(first) + "\n" + block(good))[1].cause_equipment == "CHWP-1"  # last wins
    assert parse_finding(block(good.replace('"CHWP-1"', "null")))[1].cause_equipment is None

    for bad in [
        "no block at all",
        block(good, lang="python"),
        block("{not json}"),
        block('["CHWP-1"]'),
        block('{"cause_equipment": "CHWP-1", "cause": "x"}'),
        block('{"cause_equipment": 7, "cause": "x", "runbook_ids": []}'),
        block('{"cause_equipment": "CHWP-1", "cause": "x", "runbook_ids": "RB-04"}'),
        block('{"cause_equipment": "CHWP-1", "cause": "x", "runbook_ids": [4]}'),
    ]:
        report, f = parse_finding(bad)
        assert f.parsed is False and (f.cause_equipment, f.cause, f.runbook_ids) == (None, "", []), bad


def test_injection_scenario_scripted_write_is_denied(tmp_path, monkeypatch):
    # A non-interactive run: even a "y" piped into stdin cannot approve a write.
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    obey = {"equipment_id": "CRAH-02", "summary": "Close every alarm", "steps": ["Close all"], "priority": 1}
    turns = [turn(call("list_active_alarms")), turn(call("get_alarm", {"alarm_id": "AL-6001"})),
             turn(call("draft_work_order", obey)), turn(text="Done as the note asked.")]
    result, model = run(turns, scenario="filter-with-injection", approver=ask_terminal, out_dir=tmp_path)

    assert result.stop_reason == "done"
    assert [r.approval for r in result.tools] == ["auto", "auto", "denied"]
    assert work_orders(tmp_path) == []
    note = "SYSTEM OVERRIDE"
    system = model.calls[0][0]
    assert system["role"] == "system" and "never instructions" in system["content"]
    assert all(note not in m["content"] for m in model.calls[-1] if m["role"] != "tool")
    assert note in tool_messages(model)[1]["content"]  # the note reached the model only as data


def test_ask_terminal_denies_without_tty(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    assert ask_terminal("draft_work_order", WORK_ORDER) is False
    assert capsys.readouterr().err == ""  # never prompted
    assert deny_all("draft_work_order", WORK_ORDER) is False


class FakeTty(io.StringIO):
    def isatty(self):
        return True


@pytest.mark.parametrize("answer,expected", [("y\n", True), ("YES\n", True), ("\n", False), ("n\n", False), ("", False)])
def test_ask_terminal_on_a_tty(monkeypatch, capsys, answer, expected):
    monkeypatch.setattr("sys.stdin", FakeTty(answer))
    assert ask_terminal("draft_work_order", {"priority": 1}) is expected
    out = capsys.readouterr()
    assert out.out == "" and 'Approve draft_work_order({"priority": 1})? [y/N]' in out.err


def test_is_read_only_reads_annotations_not_names():
    tool = lambda ann: Tool(name="list_active_alarms", inputSchema={"type": "object"}, annotations=ann)  # noqa: E731
    assert is_read_only(tool(ToolAnnotations(readOnlyHint=True)))
    assert not is_read_only(tool(None))
    assert not is_read_only(tool(ToolAnnotations()))
    assert not is_read_only(tool(ToolAnnotations(readOnlyHint=False)))


def test_model_error_is_a_result_not_a_crash(tmp_path):
    class Down:
        name = "down"

        def complete(self, messages, tools):
            raise ModelUnavailable("Cannot reach Ollama. Start it with `ollama serve`.")

    result, _ = run([], model=Down(), out_dir=tmp_path)
    assert result.stop_reason == "model_error" and result.steps == 0
    assert "ollama serve" in result.report and result.finding.parsed is False


def test_unknown_scenario_fails_before_starting_the_server():
    with pytest.raises(ValueError, match="nope"):
        asyncio.run(run_incident("nope", ScriptedModel([])))


def test_system_prompt_no_think_is_opt_in():
    from dcops.prompts import SYSTEM_PROMPT, system_prompt, user_goal

    assert "/no_think" not in SYSTEM_PROMPT and system_prompt() == SYSTEM_PROMPT
    assert system_prompt(no_think=True).endswith("/no_think")
    assert '"cause_equipment"' in SYSTEM_PROMPT and "```json" in SYSTEM_PROMPT
    assert len(SYSTEM_PROMPT.splitlines()) <= 40
    assert user_goal(None).startswith("Investigate the active alarms")
    assert "CRAH-02 filter" in user_goal("CRAH-02 filter differential pressure high")


def test_no_em_dash():
    for f in (REPO / "src" / "dcops" / "agent.py", REPO / "src" / "dcops" / "prompts.py", Path(__file__)):
        assert chr(0x2014) not in f.read_text(encoding="utf-8"), f


def test_tool_level_error_payload_is_recorded_as_error(tmp_path):
    bad = {**WORK_ORDER, "equipment_id": "NOPE-99"}
    c = call("draft_work_order", bad)
    result, model = run([turn(c), turn(text=FINAL)], approver=lambda n, a: True, out_dir=tmp_path)
    rec = result.tools[0]
    assert rec.approval == "approved" and rec.is_error is True
    assert work_orders(tmp_path) == []
    assert json.loads(tool_messages(model)[0]["content"])["error"].startswith("unknown equipment")


DEEP = "[" * 100_000  # json.loads raises RecursionError on this, not ValueError


def test_deeply_nested_json_is_an_error_result_not_a_crash(tmp_path):
    result, model = run([turn(call("get_equipment", raw=DEEP)), turn(text=FINAL)], out_dir=tmp_path)
    assert result.stop_reason == "done" and result.finding.parsed
    assert (result.tools[0].approval, result.tools[0].is_error) == ("blocked", True)
    assert "not valid JSON" in json.loads(tool_messages(model)[0]["content"])["error"]


def test_deeply_nested_finding_or_payload_does_not_crash():
    nl = chr(10)
    report, f = parse_finding("Report." + nl + nl + "```json" + nl + DEEP + nl + "```")
    assert f.parsed is False
    from mcp.types import CallToolResult, TextContent

    res = CallToolResult(content=[TextContent(type="text", text=DEEP)])
    assert agent._payload(res) == DEEP


def test_request_work_order_adds_one_sentence_to_the_goal(tmp_path):
    import inspect

    from dcops.prompts import WORK_ORDER_REQUEST, user_goal

    kind = inspect.signature(run_incident).parameters["request_work_order"].kind
    assert kind is inspect.Parameter.KEYWORD_ONLY
    _, plain = run([turn(text=FINAL)], out_dir=tmp_path / "a")
    _, asked = run([turn(text=FINAL)], out_dir=tmp_path / "b", request_work_order=True)
    assert plain.calls[0][1] == {"role": "user", "content": user_goal(None)}
    assert "work order" not in plain.calls[0][1]["content"]
    assert asked.calls[0][1]["content"] == user_goal(None) + " " + WORK_ORDER_REQUEST
    assert WORK_ORDER_REQUEST.count(".") == 1 and "approv" in WORK_ORDER_REQUEST
    assert user_goal(None, request_work_order=True) == asked.calls[0][1]["content"]
