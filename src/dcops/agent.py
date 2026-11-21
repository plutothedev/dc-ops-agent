# (C)
"""The agent: a hand-written tool-calling loop over the site's MCP server.

Every rule that keeps the model in bounds is enforced here in code, not in the prompt:

- Tools come from the server's own list_tools. A tool runs without asking only when its
  annotations say readOnlyHint=True; anything else (including no annotations) goes to the
  approver, and a denial means the tool never runs.
- Bad arguments, unknown tools and repeated calls get an error result the model can read;
  they never crash the run. The third identical call stops the run.
- Every result is cut at MAX_RESULT_CHARS before it reaches the model.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Literal

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, TextContent, Tool
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode, Tracer

from .llm import AssistantTurn, ChatModel, ToolCall
from .prompts import system_prompt, user_goal
from .site import list_scenarios

MAX_RESULT_CHARS = 8000
TRUNCATED = "[truncated]"
TOOL_TIMEOUT = timedelta(seconds=120)
REPEAT_ERROR = "already called with these arguments; use the earlier result"
DENIED_ERROR = "denied by operator: not run"

Approver = Callable[[str, dict], bool]
Approval = Literal["auto", "approved", "denied", "blocked"]
StopReason = Literal["done", "step_cap", "repeat_loop", "model_error"]


@dataclass(frozen=True)
class ToolRecord:
    name: str
    args: dict | str  # the raw argument text when it was not a JSON object
    approval: Approval
    is_error: bool
    result_chars: int  # size of the tool message before the cut at MAX_RESULT_CHARS


@dataclass(frozen=True)
class Finding:
    cause_equipment: str | None
    cause: str
    runbook_ids: list[str]
    parsed: bool


@dataclass
class RunResult:
    report: str
    finding: Finding
    steps: int  # model calls that returned a turn
    stop_reason: StopReason
    tools: list[ToolRecord] = field(default_factory=list)


# Approvers ---------------------------------------------------------------------------

def deny_all(name: str, args: dict) -> bool:
    return False


def ask_terminal(name: str, args: dict) -> bool:
    """Ask the operator on the terminal. Without a TTY (CI, evals, piped input): deny."""
    if sys.stdin is None or not sys.stdin.isatty():
        return False
    # json.dumps escapes control characters, so model-written args cannot drive the terminal.
    print(f"Approve {name}({json.dumps(args)})? [y/N] ", end="", file=sys.stderr, flush=True)
    return sys.stdin.readline().strip().lower() in ("y", "yes")


# The run -----------------------------------------------------------------------------

async def run_incident(
    scenario: str,
    model: ChatModel,
    approver: Approver = deny_all,
    max_steps: int = 12,
    out_dir: Path | None = None,
    data_dir=None,
    embed: bool = False,
    *,
    no_think: bool = False,
    tracer: Tracer | None = None,
    request_work_order: bool = False,
) -> RunResult:
    """Start the MCP server for one scenario and let the model investigate it.

    Approved work orders are written under out_dir (a fresh temp dir when None). Spans go to
    tracer (the global "dcops" tracer when None, a no-op unless the app set up a provider).
    request_work_order adds one sentence to the goal asking for a work order for the cause;
    the approver still decides whether it is written.
    """
    if scenario not in list_scenarios(data_dir):
        raise ValueError(f"unknown scenario: {scenario}")
    if max_steps < 1:
        raise ValueError("max_steps must be at least 1")
    out_dir = Path(out_dir) if out_dir is not None else Path(tempfile.mkdtemp(prefix="dcops-"))

    tracer = tracer or trace.get_tracer("dcops")
    with tracer.start_as_current_span("agent.run") as span:
        span.set_attribute("dcops.scenario", scenario)
        span.set_attribute("gen_ai.request.model", getattr(model, "name", "unknown"))
        span.set_attribute("dcops.search_mode", "hybrid" if embed else "bm25")
        async with stdio_client(_server_params(scenario, out_dir, data_dir, embed)) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=TOOL_TIMEOUT) as session:
                await session.initialize()
                tools = {t.name: t for t in (await session.list_tools()).tools}
                messages = [
                    {"role": "system", "content": system_prompt(no_think)},
                    # No scenario title: several titles name the cause, which would give the answer away.
                    {"role": "user", "content": user_goal(None, request_work_order)},
                ]
                result = await _investigate(session, tools, model, approver, max_steps, messages, tracer)
        span.set_attribute("dcops.steps", result.steps)
        span.set_attribute("dcops.stop_reason", result.stop_reason)
        if result.stop_reason == "model_error":
            span.set_status(Status(StatusCode.ERROR, result.report))
        return result


def run_incident_sync(*args: Any, **kwargs: Any) -> RunResult:
    """run_incident for callers without an event loop."""
    return asyncio.run(run_incident(*args, **kwargs))


async def _investigate(
    session: ClientSession,
    tools: dict[str, Tool],
    model: ChatModel,
    approver: Approver,
    max_steps: int,
    messages: list[dict],
    tracer: Tracer,
) -> RunResult:
    """The loop: ask the model, run the tools it asks for, feed the results back."""
    schemas = [_tool_schema(t) for t in tools.values()]
    seen: Counter[tuple[str, str]] = Counter()
    records: list[ToolRecord] = []
    turn = AssistantTurn(text="")

    for step in range(1, max_steps + 1):
        try:
            with tracer.start_as_current_span("llm.chat") as span:
                span.set_attribute("gen_ai.request.model", getattr(model, "name", "unknown"))
                turn = await call_model(model, messages, schemas)
                span.set_attribute("dcops.tool_calls", len(turn.tool_calls))
                for key, value in (
                    ("gen_ai.usage.input_tokens", turn.usage.input_tokens),
                    ("gen_ai.usage.output_tokens", turn.usage.output_tokens),
                ):
                    if value is not None:
                        span.set_attribute(key, value)
        except Exception as e:  # ModelUnavailable or anything else: a result, not a crash
            return RunResult(f"model error: {e}", _unparsed(), step - 1, "model_error", records)
        messages.append(_assistant_message(turn))

        if not turn.tool_calls:
            report, finding = parse_finding(turn.text)
            return RunResult(report, finding, step, "done", records)

        for call in turn.tool_calls:
            with tracer.start_as_current_span("tool.call") as span:
                record, content = await execute_tool_call(session, tools, approver, call, seen)
                span.set_attribute("tool.name", record.name)
                span.set_attribute("tool.arguments", _args_text(record.args))
                span.set_attribute("tool.approval", record.approval)
                span.set_attribute("tool.result_chars", record.result_chars)
                span.set_attribute("tool.is_error", record.is_error)
            records.append(record)
            if content is None:
                return RunResult(turn.text.strip(), _unparsed(), step, "repeat_loop", records)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": content})

    return RunResult(turn.text.strip(), _unparsed(), max_steps, "step_cap", records)


async def call_model(model: ChatModel, messages: list[dict], schemas: list[dict]) -> AssistantTurn:
    # The model client is synchronous and blocks the event loop while it runs. That is fine:
    # the MCP server is idle between tool calls. Under asyncio.run the first Ctrl+C cancels
    # the run's task, but a blocking model call (or the approval prompt) keeps waiting until
    # it returns; the cancellation lands after that.
    return model.complete(messages, schemas)


async def execute_tool_call(
    session: ClientSession,
    tools: dict[str, Tool],
    approver: Approver,
    call: ToolCall,
    seen: Counter[tuple[str, str]],
) -> tuple[ToolRecord, str | None]:
    """Gate one tool call and run it if allowed.

    Returns the record and the tool message content for the model. Content is None when
    this is the third identical call: the run must stop.
    """
    name = call.name

    def blocked(args: dict | str, why: str) -> tuple[ToolRecord, str]:
        content, size = _tool_message(name, "error", why)
        return ToolRecord(name, args, "blocked", True, size), content

    try:
        args = json.loads(call.arguments)
    except (ValueError, RecursionError) as e:
        return blocked(call.arguments, f"arguments are not valid JSON: {e}")
    if not isinstance(args, dict):
        return blocked(call.arguments, "arguments must be a JSON object")
    if name not in tools:
        return blocked(args, f"unknown tool {name!r}; available: {', '.join(tools)}")

    key = (name, json.dumps(args, sort_keys=True))
    seen[key] += 1
    if seen[key] == 2:
        return blocked(args, REPEAT_ERROR)
    if seen[key] > 2:
        return ToolRecord(name, args, "blocked", True, 0), None

    if is_read_only(tools[name]):
        approval: Approval = "auto"
    else:
        try:
            approved = approver(name, args) is True  # only a real True approves
        except Exception:
            approved = False
        if not approved:
            content, size = _tool_message(name, "error", DENIED_ERROR)
            return ToolRecord(name, args, "denied", True, size), content
        approval = "approved"

    try:
        result = await session.call_tool(name, args)
    except Exception as e:
        content, size = _tool_message(name, "error", f"tool call failed: {type(e).__name__}: {e}")
        return ToolRecord(name, args, approval, True, size), content
    if result.isError:
        content, size = _tool_message(name, "error", _text(result))
        return ToolRecord(name, args, approval, True, size), content
    payload = _payload(result)
    if isinstance(payload, dict) and "error" in payload:
        # Tools report validation failures as a normal {"error": ...} result, not isError.
        content, size = _tool_message(name, "error", payload["error"])
        return ToolRecord(name, args, approval, True, size), content
    content, size = _tool_message(name, "result", payload)
    return ToolRecord(name, args, approval, False, size), content


def is_read_only(tool: Tool) -> bool:
    """Only an explicit readOnlyHint=True from the server skips approval."""
    return tool.annotations is not None and tool.annotations.readOnlyHint is True


# Helpers -----------------------------------------------------------------------------

def _server_params(scenario: str, out_dir: Path, data_dir, embed: bool) -> StdioServerParameters:
    src = str(Path(__file__).resolve().parents[1])  # the directory holding the dcops package
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (src, env.get("PYTHONPATH")) if p)
    if data_dir is not None:
        env["DCOPS_DATA"] = str(data_dir)
    args = ["-m", "dcops.mcp_server", "--scenario", scenario, "--out", str(out_dir)]
    if not embed:
        args.append("--no-embed")
    return StdioServerParameters(command=sys.executable, args=args, env=env)


def _args_text(args: dict | str) -> str:
    """The call's arguments as canonical JSON, cut to 500 chars for the span."""
    text = args if isinstance(args, str) else json.dumps(args, sort_keys=True)
    return text[:500]


def _tool_schema(tool: Tool) -> dict:
    return {
        "type": "function",
        "function": {"name": tool.name, "description": tool.description or "", "parameters": tool.inputSchema},
    }


def _assistant_message(turn: AssistantTurn) -> dict:
    message: dict[str, Any] = {"role": "assistant", "content": turn.text}
    if turn.tool_calls:
        message["tool_calls"] = [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
            for c in turn.tool_calls
        ]
    return message


def _text(result: CallToolResult) -> str:
    return "\n".join(c.text for c in result.content if isinstance(c, TextContent))


def _payload(result: CallToolResult) -> Any:
    """The tool's return value.

    FastMCP sends a list as one text block per item, so a one-item list would read as a
    bare object. Structured content keeps the real shape; FastMCP wraps non-object
    returns as {"result": value}.
    """
    if result.structuredContent is not None:
        sc = result.structuredContent
        return sc["result"] if set(sc) == {"result"} else sc
    text = _text(result)
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        return text


def _tool_message(name: str, key: str, value: Any) -> tuple[str, int]:
    """The tool message for the model, capped, and its size before the cap."""
    content = json.dumps({"tool": name, key: value})
    return _cap(content), len(content)


def _cap(content: str) -> str:
    return content if len(content) <= MAX_RESULT_CHARS else content[:MAX_RESULT_CHARS] + TRUNCATED


_JSON_BLOCK = re.compile(r"```json[ \t]*\n(.*?)```", re.DOTALL)
_FINDING_KEYS = {"cause_equipment", "cause", "runbook_ids"}


def parse_finding(text: str) -> tuple[str, Finding]:
    """Split the final answer into the report and the finding in its last json block.

    A missing or malformed block gives an unparsed finding and leaves the text whole.
    """
    blocks = list(_JSON_BLOCK.finditer(text))
    if blocks:
        last = blocks[-1]
        finding = _finding(last.group(1))
        if finding.parsed:
            return (text[: last.start()] + text[last.end():]).strip(), finding
    return text.strip(), _unparsed()


def _finding(body: str) -> Finding:
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        return _unparsed()
    if not isinstance(data, dict) or not _FINDING_KEYS <= data.keys():
        return _unparsed()
    equipment, cause, runbook_ids = data["cause_equipment"], data["cause"], data["runbook_ids"]
    if (
        (equipment is None or isinstance(equipment, str))
        and isinstance(cause, str)
        and isinstance(runbook_ids, list)
        and all(isinstance(r, str) for r in runbook_ids)
    ):
        return Finding(equipment, cause, runbook_ids, parsed=True)
    return _unparsed()


def _unparsed() -> Finding:
    return Finding(None, "", [], parsed=False)
