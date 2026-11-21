# (C)
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from dcops.mcp_server import build_server
from dcops.site import Site

SC = "crah-fan-failure"
REPO = Path(__file__).resolve().parents[1]


def run(coro):
    return asyncio.run(coro)


def _payload(result):
    if result.structuredContent is not None:
        sc = result.structuredContent
        if set(sc) == {"result"}:
            return sc["result"]
        return sc
    return json.loads(result.content[0].text)


async def _call(server, name, args=None):
    async with create_connected_server_and_client_session(server._mcp_server) as c:
        return _payload(await c.call_tool(name, args or {}))


def _server(tmp_path):
    return build_server(SC, tmp_path)


def test_tools_and_annotations(tmp_path):
    async def go():
        async with create_connected_server_and_client_session(_server(tmp_path)._mcp_server) as c:
            return (await c.list_tools()).tools

    tools = {t.name: t for t in run(go())}
    assert set(tools) == {
        "list_active_alarms", "get_alarm", "get_equipment",
        "get_sensor_history", "search_runbooks", "draft_work_order",
    }
    for name, t in tools.items():
        a = t.annotations
        assert a is not None and a.openWorldHint is False
        if name == "draft_work_order":
            assert a.readOnlyHint is False and a.destructiveHint is True and a.idempotentHint is False
        else:
            assert a.readOnlyHint is True and a.destructiveHint is False and a.idempotentHint is True


def test_every_tool_parameter_has_a_description(tmp_path):
    async def go():
        async with create_connected_server_and_client_session(_server(tmp_path)._mcp_server) as c:
            return (await c.list_tools()).tools

    seen = set()
    for t in run(go()):
        for pname, schema in t.inputSchema.get("properties", {}).items():
            assert schema.get("description", "").strip(), f"{t.name}.{pname}"
            seen.add(pname)
    assert seen == {"alarm_id", "equipment_id", "metric", "query", "summary", "steps", "priority", "minutes", "k"}


def test_alarm_list_shows_the_injection_note(tmp_path):
    alarms = run(_call(build_server("filter-with-injection", tmp_path), "list_active_alarms"))
    assert len(alarms) == 1 and alarms[0]["id"] == "AL-6001"
    assert "SYSTEM OVERRIDE" in alarms[0]["note"]
    assert all("note" not in a for a in run(_call(_server(tmp_path), "list_active_alarms")))


def test_equipment_lists_metrics_and_bad_metric_names_the_valid_ones(tmp_path):
    s = _server(tmp_path)
    eq = run(_call(s, "get_equipment", {"equipment_id": "CRAH-03"}))
    assert eq["metrics"] == ["fan_speed_rpm", "supply_air_temp_c"]
    assert run(_call(s, "get_equipment", {"equipment_id": "PDU-A1"}))["metrics"] == []
    err = run(_call(s, "get_sensor_history", {"equipment_id": "CRAH-03", "metric": "airflow"}))["error"]
    assert "airflow" in err and "fan_speed_rpm, supply_air_temp_c" in err
    err = run(_call(s, "get_sensor_history", {"equipment_id": "PDU-A1", "metric": "load_pct"}))["error"]
    assert "PDU-A1" in err and "no sensors" in err
    err = run(_call(s, "get_sensor_history", {"equipment_id": "NOPE-1", "metric": "x"}))["error"]
    assert "unknown equipment" in err


def test_reads_match_site(tmp_path):
    site = Site.load(SC)
    s = _server(tmp_path)
    assert run(_call(s, "list_active_alarms")) == site.alarms()
    assert run(_call(s, "get_alarm", {"alarm_id": "AL-1001"})) == site.alarm("AL-1001")
    assert run(_call(s, "get_equipment", {"equipment_id": "CRAH-03"})) == site.equipment("CRAH-03")
    got = run(_call(s, "get_sensor_history",
                    {"equipment_id": "CRAH-03", "metric": "fan_speed_rpm", "minutes": 30}))
    assert got == site.sensor_history("CRAH-03", "fan_speed_rpm", 30)
    hits = run(_call(s, "search_runbooks", {"query": "CRAH fan failure", "k": 2}))
    assert 1 <= len(hits) <= 2
    assert set(hits[0]) == {"runbook_id", "title", "section", "text", "score"}


def test_unknown_ids_are_errors_not_exceptions(tmp_path):
    s = _server(tmp_path)
    for name, args in [
        ("get_alarm", {"alarm_id": "AL-9999"}),
        ("get_equipment", {"equipment_id": "NOPE-1"}),
        ("get_sensor_history", {"equipment_id": "NOPE-1", "metric": "x"}),
        ("draft_work_order", {"equipment_id": "NOPE-1", "summary": "s", "steps": ["a"], "priority": 2}),
    ]:
        r = run(_call(s, name, args))
        assert isinstance(r, dict) and "error" in r, name


def test_minutes_clamped(tmp_path):
    s = _server(tmp_path)
    site = Site.load(SC)
    args = {"equipment_id": "CRAH-03", "metric": "fan_speed_rpm"}
    assert run(_call(s, "get_sensor_history", {**args, "minutes": 0})) == site.sensor_history(
        "CRAH-03", "fan_speed_rpm", 1)
    assert run(_call(s, "get_sensor_history", {**args, "minutes": 10**6})) == site.sensor_history(
        "CRAH-03", "fan_speed_rpm", 1440)
    for bad in (True, 1.5, "60"):
        r = run(_call(s, "get_sensor_history", {**args, "minutes": bad}))
        assert "error" in r, bad


def test_input_validation(tmp_path):
    s = _server(tmp_path)
    for args in ({"query": ""}, {"query": "  "}, {"query": "fan", "k": 0},
                 {"query": "fan", "k": 11}, {"query": "fan", "k": True}):
        r = run(_call(s, "search_runbooks", args))
        assert isinstance(r, dict) and "error" in r, args
    ok = {"equipment_id": "CRAH-03", "summary": "s", "steps": ["a"], "priority": 2}
    bads = [
        {"priority": 0}, {"priority": 5}, {"priority": True}, {"priority": 2.0},
        {"summary": ""}, {"summary": "x" * 1001},
        {"steps": []}, {"steps": [""]}, {"steps": ["x" * 501]}, {"steps": ["a"] * 21},
        {"steps": ["a", 3]},
    ]
    for b in bads:
        r = run(_call(s, "draft_work_order", {**ok, **b}))
        assert isinstance(r, dict) and "error" in r, b
    assert not (tmp_path / "work_orders").exists() or not list((tmp_path / "work_orders").iterdir())


def test_work_order_written_and_numbered(tmp_path):
    s = _server(tmp_path)
    args = {"equipment_id": "CRAH-03", "summary": "Replace fan", "steps": ["Isolate", "Swap"], "priority": 2}
    r1 = run(_call(s, "draft_work_order", args))
    r2 = run(_call(s, "draft_work_order", args))
    assert r1["work_order_id"] == "WO-1" and r2["work_order_id"] == "WO-2"
    d = tmp_path / "work_orders"
    assert (d / "WO-1.json").is_file() and (d / "WO-2.json").is_file()
    doc = json.loads((d / "WO-2.json").read_text(encoding="utf-8"))
    assert doc["status"] == "draft" and doc["scenario"] == SC
    assert doc["equipment_id"] == "CRAH-03" and doc["steps"] == ["Isolate", "Swap"]
    assert doc["priority"] == 2 and doc["created_at"]
    # numbering continues from the highest existing number
    (d / "WO-7.json").write_text("{}", encoding="utf-8")
    assert run(_call(s, "draft_work_order", args))["work_order_id"] == "WO-8"


def test_cli_unknown_scenario(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    import subprocess
    p = subprocess.run([sys.executable, "-m", "dcops.mcp_server", "--scenario", "nope",
                        "--out", str(tmp_path), "--no-embed"],
                       capture_output=True, text=True, env=env, timeout=60)
    assert p.returncode != 0 and "nope" in p.stderr and p.stdout == ""


def test_stdio_roundtrip(tmp_path):
    async def go():
        env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "dcops.mcp_server", "--scenario", SC, "--out", str(tmp_path), "--no-embed"],
            env=env,
        )
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as sess:
                await sess.initialize()
                names = {t.name for t in (await sess.list_tools()).tools}
                res = await sess.call_tool("list_active_alarms", {})
                return names, _payload(res)

    names, alarms = asyncio.run(asyncio.wait_for(go(), 60))
    assert "draft_work_order" in names and len(names) == 6
    assert alarms == Site.load(SC).alarms()


def test_no_em_dash():
    for f in (REPO / "src" / "dcops" / "mcp_server.py", Path(__file__)):
        if f.exists():
            assert chr(0x2014) not in f.read_text(encoding="utf-8")
