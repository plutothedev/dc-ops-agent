# (C)
"""CLI tests: no Ollama, no network. The model factory is patched."""
import json
from pathlib import Path

import pytest

from dcops import cli
from dcops.agent import Finding, RunResult, ToolRecord
from dcops.llm import AssistantTurn, ModelUnavailable, ScriptedModel, ToolCall
from dcops.report import format_report

SC = "crah-fan-failure"
FINAL = (
    "CRAH-03 tripped on fan motor overload.\n\n```json\n"
    '{"cause_equipment": "CRAH-03", "cause": "CRAH-03 fan motor overload trip", "runbook_ids": ["RB-01"]}\n```'
)


def scripted():
    return ScriptedModel(
        [
            AssistantTurn(text="", tool_calls=[ToolCall(id="c1", name="list_active_alarms", arguments="{}")]),
            AssistantTurn(text=FINAL, tool_calls=[]),
        ]
    )


def test_scenarios_lists_six(capsys):
    assert cli.main(["scenarios"]) == 0
    out = capsys.readouterr().out
    assert len([l for l in out.splitlines() if l.strip()]) == 6
    assert SC in out


def test_run_with_model_unavailable_exits_2_with_hint(monkeypatch, tmp_path, capsys):
    class Down:
        name = "down"

        def complete(self, messages, tools):
            raise ModelUnavailable("cannot reach Ollama; run `ollama serve` and `ollama pull qwen3:8b`")

    monkeypatch.setattr(cli, "make_model", lambda name: Down())
    code = cli.main(["run", "--scenario", SC, "--out", str(tmp_path / "o"), "--trace", str(tmp_path / "t.jsonl"), "--deny-writes"])
    err = capsys.readouterr().err
    assert code == 2
    assert "ollama pull qwen3:8b" in err and err.startswith("error: ")
    assert "Traceback" not in err and len(err.strip().splitlines()) == 1


def test_run_with_scripted_model_prints_report(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "make_model", lambda name: scripted())
    trace = tmp_path / "t.jsonl"
    code = cli.main(["run", "--scenario", SC, "--out", str(tmp_path / "o"), "--trace", str(trace), "--deny-writes"])
    out = capsys.readouterr().out
    assert code == 0
    assert "CRAH-03" in out and "RB-01" in out and "list_active_alarms" in out
    assert f"dcops trace {trace}" in out.splitlines()[-1]
    assert trace.exists() and trace.stat().st_size > 0
    assert chr(0x2014) not in out


def test_trace_command_renders(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "make_model", lambda name: scripted())
    trace = tmp_path / "t.jsonl"
    cli.main(["run", "--scenario", SC, "--out", str(tmp_path / "o"), "--trace", str(trace), "--deny-writes"])
    capsys.readouterr()
    assert cli.main(["trace", str(trace)]) == 0
    assert "agent.run" in capsys.readouterr().out


def test_eval_retrieval_prints_metrics(capsys):
    assert cli.main(["eval", "retrieval"]) == 0
    out = capsys.readouterr().out
    assert "hit@3" in out and "MRR" in out and "n=" in out and "bm25" in out


def test_keyboard_interrupt_exits_130(monkeypatch, capsys):
    def boom(args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_cmd_scenarios", boom)
    assert cli.main(["scenarios"]) == 130
    assert capsys.readouterr().err.strip() == "interrupted"


def _result(stop="done", tools=None, parsed=True):
    f = Finding("CRAH-03", "fan trip", ["RB-01"], True) if parsed else Finding(None, "", [], False)
    return RunResult("model text\n", f, 3, stop, tools or [])


def test_format_report_work_order_states(tmp_path):
    written = [ToolRecord("draft_work_order", {"equipment_id": "X"}, "approved", False, 10)]
    denied = [ToolRecord("draft_work_order", {"equipment_id": "X"}, "denied", True, 10)]
    r1 = format_report(_result(tools=written), scenario=SC, out_dir=tmp_path, trace_path=None)
    r2 = format_report(_result(tools=denied), scenario=SC, out_dir=tmp_path, trace_path=None)
    r3 = format_report(_result(parsed=False), scenario=SC, out_dir=None, trace_path=None)
    assert str(tmp_path) in r1 and "denied" in r2 and "none requested" in r3
    assert "not determined" in r3
    assert all(chr(0x2014) not in r for r in (r1, r2, r3))


@pytest.mark.parametrize("stop,code", [("step_cap", 1), ("repeat_loop", 1), ("model_error", 2)])
def test_exit_codes(stop, code):
    assert cli.exit_code(_result(stop=stop)) == code


def test_report_does_not_claim_written_for_errored_work_order(tmp_path):
    rec = [ToolRecord("draft_work_order", {"equipment_id": "X"}, "approved", True, 10)]
    r = format_report(_result(tools=rec), scenario=SC, out_dir=tmp_path, trace_path=None)
    assert "written" not in r.split("Work order")[1].split("Stop")[0].replace("not written", "")


def test_max_steps_zero_exits_2_cleanly(tmp_path, capsys):
    code = cli.main(["run", "--scenario", SC, "--max-steps", "0", "--out", str(tmp_path), "--trace", str(tmp_path / "t")])
    err = capsys.readouterr().err
    assert code == 2 and err.startswith("error: ") and "Traceback" not in err


def test_run_exception_becomes_error_line(monkeypatch, tmp_path, capsys):
    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli, "make_model", lambda n: scripted())
    monkeypatch.setattr(cli, "run_incident_sync", boom)
    code = cli.main(["run", "--scenario", SC, "--out", str(tmp_path), "--trace", str(tmp_path / "t")])
    assert code == 2 and capsys.readouterr().err.strip() == "error: kaboom"


def test_format_report_strips_control_characters(tmp_path):
    esc, bel, cr, nul, tab, nl = chr(27), chr(7), chr(13), chr(0), chr(9), chr(10)
    f = Finding("CRAH-03" + esc + "[2J", "fan" + bel + " trip" + cr, ["RB-01" + nul], True)
    rec = ToolRecord("get_equipment", {"equipment_id": "CRAH" + esc + "]0;x" + bel}, "auto", False, 10)
    raw = ToolRecord("get_alarm", "not json" + esc + "[31m", "blocked", True, 10)
    r = RunResult("line one" + esc + "[1m" + nl + "col" + tab + "two" + cr, f, 3, "done", [rec, raw])
    out = format_report(r, scenario=SC, out_dir=None, trace_path=None)
    bad = [c for c in out if ord(c) < 32 and c not in (nl, tab)]
    assert bad == []
    assert "CRAH-03[2J" in out and "fan trip" in out and "RB-01" in out
    assert "col" + tab + "two" in out and "not json[31m" in out


def _capture_run(monkeypatch):
    seen = {}

    def fake(scenario, model, **kw):
        seen.update(kw, scenario=scenario)
        return _result()

    monkeypatch.setattr(cli, "make_model", lambda n: scripted())
    monkeypatch.setattr(cli, "run_incident_sync", fake)
    return seen


def _run_args(tmp_path, *extra):
    return ["run", "--scenario", SC, "--out", str(tmp_path / "o"), "--trace", str(tmp_path / "t.jsonl"), *extra]


def test_approver_wiring(monkeypatch, tmp_path, capsys):
    from dcops.agent import ask_terminal, deny_all

    seen = _capture_run(monkeypatch)
    assert cli.main(_run_args(tmp_path, "--deny-writes")) == 0
    assert seen["approver"] is deny_all
    assert cli.main(_run_args(tmp_path)) == 0
    assert seen["approver"] is ask_terminal
    assert cli.main(_run_args(tmp_path, "--yes-to-writes")) == 0
    assert seen["approver"]("draft_work_order", {}) is True


def test_draft_work_order_flag_reaches_run_incident(monkeypatch, tmp_path, capsys):
    seen = _capture_run(monkeypatch)
    cli.main(_run_args(tmp_path))
    assert seen["request_work_order"] is False
    cli.main(_run_args(tmp_path, "--draft-work-order"))
    assert seen["request_work_order"] is True


def test_default_approver_denies_without_a_tty(monkeypatch, tmp_path, capsys):
    import io

    order = {"equipment_id": "CRAH-03", "summary": "Replace fan", "steps": ["Swap"], "priority": 2}
    model = ScriptedModel([
        AssistantTurn(text="", tool_calls=[ToolCall(id="w1", name="draft_work_order", arguments=json.dumps(order))]),
        AssistantTurn(text=FINAL),
    ])
    monkeypatch.setattr(cli, "make_model", lambda n: model)
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))  # piped "y" must not approve
    code = cli.main(_run_args(tmp_path, "--draft-work-order"))
    out = capsys.readouterr()
    assert code == 0 and "draft_work_order" in out.out
    assert "denied by operator, nothing written" in out.out
    assert "Approve" not in out.err  # never prompted
    assert not (tmp_path / "o" / "work_orders").exists()


def test_missing_data_folder_exits_2(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("DCOPS_DATA", str(tmp_path / "nope"))
    for argv in (["scenarios"], _run_args(tmp_path), ["eval", "retrieval"], ["eval", "agent", "--runs", "1"]):
        assert cli.main(argv) == 2, argv
        err = capsys.readouterr().err
        assert err.startswith("error: data folder not found at "), argv
        assert "DCOPS_DATA" in err and "Traceback" not in err and len(err.strip().splitlines()) == 1


def test_missing_gold_file_exits_2(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "GOLD", tmp_path / "gold.jsonl")
    assert cli.main(["eval", "retrieval"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: retrieval gold file not found at ") and "Traceback" not in err
