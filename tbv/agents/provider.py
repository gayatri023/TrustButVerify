"""Provider interface plus a scripted provider for tests and the offline demo."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from tbv.agents.types import Message, ProviderTurn, ToolCall


class Provider(Protocol):
    model: str

    def next_turn(self, history: list[Message]) -> ProviderTurn: ...


class ScriptExhausted(RuntimeError):
    pass


class ScriptedProvider:
    """Plays back a fixed list of turns. Used by tests and `tbv demo`; never calls a model."""

    model = "scripted"

    def __init__(self, turns: Sequence[ProviderTurn]) -> None:
        self._turns = list(turns)
        self._i = 0

    def next_turn(self, history: list[Message]) -> ProviderTurn:
        if self._i >= len(self._turns):
            raise ScriptExhausted("scripted provider has no more turns")
        turn = self._turns[self._i]
        self._i += 1
        return turn


def call(name: str, **args: object) -> ToolCall:
    return ToolCall(name=name, args=dict(args))


def turn(*calls: ToolCall, text: str = "") -> ProviderTurn:
    return ProviderTurn(text=text, tool_calls=list(calls), tokens_in=100, tokens_out=20)
