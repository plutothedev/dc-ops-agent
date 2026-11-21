# (C)
import time
from types import SimpleNamespace as NS

import httpx
import openai
import pytest

from dcops.llm import (
    AssistantTurn,
    ModelUnavailable,
    OllamaModel,
    ScriptedModel,
    ToolCall,
    Usage,
    strip_thinking,
)


def test_strip_thinking():
    assert strip_thinking("<think>a</think>hello") == "hello"
    assert strip_thinking("x<think>a</think>y<think>b\nc</think> z") == "xy z"
    assert strip_thinking("<think>never closed") == ""
    assert strip_thinking("ok<think>never closed") == "ok"
    assert strip_thinking("plain") == "plain"


def test_scripted_model_replays_and_records():
    t1 = AssistantTurn("one", [], Usage(None, None))
    t2 = AssistantTurn("two", [ToolCall("c1", "f", "{}")], Usage(1, 2))
    m = ScriptedModel([t1, t2])
    msgs = [{"role": "user", "content": "hi"}]
    assert m.complete(msgs, []) is t1
    msgs[0]["content"] = "mutated"
    assert m.complete(msgs, []) is t2
    assert m.calls[0][0]["content"] == "hi"
    assert len(m.calls) == 2
    assert m.name == "scripted"
    with pytest.raises(IndexError):
        m.complete(msgs, [])


class _FakeClient:
    def __init__(self, message, usage):
        self.kwargs = None
        resp = NS(choices=[NS(message=message)], usage=usage)

        def create(**kw):
            self.kwargs = kw
            return resp

        self.chat = NS(completions=NS(create=create))


def test_ollama_model_parses_openai_tool_calls():
    msg = NS(
        content="<think>hm</think>Checking.",
        tool_calls=[
            NS(id="a1", function=NS(name="get_alarm", arguments='{"id": 1}')),
            NS(id=None, function=NS(name="search", arguments='{"q": "x"}')),
        ],
    )
    client = _FakeClient(msg, NS(prompt_tokens=10, completion_tokens=5))
    m = OllamaModel(client=client)
    turn = m.complete([{"role": "user", "content": "go"}], [{"type": "function"}])
    assert turn.text == "Checking."
    assert turn.tool_calls[0] == ToolCall("a1", "get_alarm", '{"id": 1}')
    assert turn.tool_calls[1].id == "call_1"
    assert turn.tool_calls[1].arguments == '{"q": "x"}'
    assert turn.usage == Usage(10, 5)
    assert m.name == "qwen3:8b"
    assert client.kwargs["tools"] == [{"type": "function"}]
    m.complete([], [])
    assert "tools" not in client.kwargs


def test_ollama_model_no_usage_no_content():
    client = _FakeClient(NS(content=None, tool_calls=None), None)
    turn = OllamaModel(client=client).complete([], [])
    assert turn == AssistantTurn("", [], Usage(None, None))


def test_ollama_model_maps_connection_error_to_model_unavailable():
    m = OllamaModel(base_url="http://127.0.0.1:9")
    start = time.time()
    with pytest.raises(ModelUnavailable) as e:
        m.complete([{"role": "user", "content": "hi"}], [])
    assert "ollama serve" in str(e.value)
    assert "127.0.0.1:9" in str(e.value)
    assert time.time() - start < 10


def test_empty_arguments_default_to_empty_object():
    msg = NS(
        content="",
        tool_calls=[
            NS(id="a", function=NS(name="f", arguments=None)),
            NS(id="b", function=NS(name="g", arguments="")),
        ],
    )
    turn = OllamaModel(client=_FakeClient(msg, None)).complete([], [])
    assert [c.arguments for c in turn.tool_calls] == ["{}", "{}"]


def _raising_client(exc):
    def create(**kw):
        raise exc

    return NS(chat=NS(completions=NS(create=create)))


def _resp(status):
    return httpx.Response(status, request=httpx.Request("POST", "http://x/v1"))


def test_not_found_maps_to_model_unavailable():
    exc = openai.NotFoundError("nope", response=_resp(404), body=None)
    m = OllamaModel(client=_raising_client(exc))
    with pytest.raises(ModelUnavailable) as e:
        m.complete([], [])
    assert "ollama pull qwen3:8b" in str(e.value)


def test_other_api_errors_propagate():
    exc = openai.InternalServerError("boom", response=_resp(500), body=None)
    m = OllamaModel(client=_raising_client(exc))
    with pytest.raises(openai.InternalServerError):
        m.complete([], [])
