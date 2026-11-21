# (C)
"""Model client: a tiny interface over a local Ollama model, plus a scripted stand-in."""
from __future__ import annotations

import copy
import itertools
import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import openai

DEFAULT_MODEL = "qwen3:8b"
DEFAULT_BASE_URL = "http://localhost:11434"


class ModelUnavailable(RuntimeError):
    """The model server is unreachable or the model is not pulled."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON string; the agent parses it


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True)
class AssistantTurn:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = Usage(None, None)


class ChatModel(Protocol):
    name: str

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantTurn: ...


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_thinking(text: str) -> str:
    """Remove <think>...</think> blocks; an unclosed <think> drops the rest."""
    text = _THINK_BLOCK.sub("", text)
    start = text.find("<think>")
    if start != -1:
        text = text[:start]
    return text.strip()


class ScriptedModel:
    """Replays fixed turns in order and records every messages list it saw.

    Raises IndexError if asked for more turns than were scripted.
    """

    def __init__(self, turns: list[AssistantTurn], name: str = "scripted"):
        self._turns = list(turns)
        self._i = 0
        self.name = name
        self.calls: list[list[dict]] = []

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        self.calls.append(copy.deepcopy(messages))
        if self._i >= len(self._turns):
            raise IndexError(
                f"ScriptedModel exhausted: asked for turn {self._i + 1} "
                f"but only {len(self._turns)} scripted"
            )
        turn = self._turns[self._i]
        self._i += 1
        return turn


class OllamaModel:
    """Local model via Ollama's OpenAI-compatible endpoint at <base_url>/v1."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str | None = None,
        temperature: float = 0.2,
        client: Any = None,
        timeout: float = 120.0,
    ):
        self.name = model
        self.temperature = temperature
        self.base_url = (
            base_url or os.environ.get("OLLAMA_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self._client = client or openai.OpenAI(
            base_url=f"{self.base_url}/v1",
            api_key="ollama",
            timeout=timeout,
            max_retries=0,
        )
        self._ids = itertools.count(1)

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        try:
            kwargs: dict[str, Any] = {
                "model": self.name,
                "messages": messages,
                "temperature": self.temperature,
            }
            if tools:
                kwargs["tools"] = tools
            resp = self._client.chat.completions.create(**kwargs)
        except (openai.APIConnectionError, openai.APITimeoutError) as e:
            raise ModelUnavailable(
                f"Cannot reach Ollama at {self.base_url} ({type(e).__name__}). "
                "Start it with `ollama serve`."
            ) from e
        except openai.NotFoundError as e:
            raise ModelUnavailable(
                f"Model {self.name!r} not found. Run `ollama pull {self.name}`."
            ) from e
        message = resp.choices[0].message
        calls = [
            ToolCall(
                id=tc.id or f"call_{next(self._ids)}",
                name=tc.function.name,
                arguments=tc.function.arguments or "{}",
            )
            for tc in (message.tool_calls or [])
        ]
        usage = getattr(resp, "usage", None)
        return AssistantTurn(
            text=strip_thinking(message.content or ""),
            tool_calls=calls,
            usage=Usage(
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
            ),
        )
