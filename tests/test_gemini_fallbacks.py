"""Gemini adapter fallbacks, tested with a fake client (no network)."""

from types import SimpleNamespace as NS

from tbv.agents.gemini_provider import GeminiProvider, parse_text_tool_call
from tbv.agents.types import Message, ToolCall
from tbv.core.config import load_agents


class FakeAPIError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def _resp(text: str = "", call: tuple[str, dict] | None = None):  # type: ignore[no-untyped-def,type-arg]
    part = NS(
        text=text or None,
        thought=False,
        function_call=NS(name=call[0], args=call[1]) if call else None,
    )
    return NS(
        candidates=[NS(content=NS(parts=[part]))],
        usage_metadata=NS(prompt_token_count=100, response_token_count=10, thoughts_token_count=0),
    )


class FakeClient:
    def __init__(self, behaviours: list):  # type: ignore[no-untyped-def,type-arg]
        self.calls: list = []  # type: ignore[type-arg]
        self._b = behaviours
        self.models = NS(generate_content=self._gen)

    def _gen(self, model, contents, config):  # type: ignore[no-untyped-def]
        self.calls.append(config)
        b = self._b.pop(0)
        if isinstance(b, Exception):
            raise b
        return b


def _provider(client: FakeClient, mode: str = "auto") -> GeminiProvider:
    cfg = next(a for a in load_agents().agents if a.name == "gemma-4-31b")
    cfg = cfg.model_copy(update={"model": "gemma-test", "tool_mode": mode})
    return GeminiProvider(cfg, "k", "SYSTEM PROMPT", client=client)


HIST = [Message(role="user", text="do the task")]


def test_native_function_call_is_parsed() -> None:
    c = FakeClient([_resp(call=("read_file", {"path": "a.py"}))])
    turn = _provider(c).next_turn(HIST)
    assert turn.tool_calls == [ToolCall(name="read_file", args={"path": "a.py"})]
    assert turn.tokens_in == 100


def test_system_instruction_rejected_is_inlined_into_first_user_message() -> None:
    c = FakeClient(
        [FakeAPIError(400, "Developer instruction is not enabled for this model"), _resp(text="ok")]
    )
    p = _provider(c)
    turn = p.next_turn(HIST)
    assert turn.text == "ok" and len(c.calls) == 2
    assert getattr(c.calls[0], "system_instruction", None) == "SYSTEM PROMPT"
    assert getattr(c.calls[1], "system_instruction", None) is None
    assert p._contents(HIST)[0].parts[0].text.startswith("SYSTEM PROMPT")


def test_function_calling_rejected_falls_back_to_json_text_tools() -> None:
    c = FakeClient(
        [
            FakeAPIError(400, "Function calling is not enabled for this model"),
            _resp(text='I will look. {"tool": "list_files", "args": {"path": "."}}'),
        ]
    )
    turn = _provider(c).next_turn(HIST)
    assert turn.tool_calls == [ToolCall(name="list_files", args={"path": "."})]
    assert getattr(c.calls[1], "tools", None) is None  # second request carried no native tools


def test_text_tool_parsing_edge_cases() -> None:
    assert parse_text_tool_call("no json here") is None
    assert parse_text_tool_call('{"tool": "nope", "args": {}}') is None
    nested = '{"tool": "write_file", "args": {"path": "a", "content": "{x}"}}'
    assert parse_text_tool_call(nested) == ToolCall(
        name="write_file", args={"path": "a", "content": "{x}"}
    )
    assert parse_text_tool_call('{"tool": "finish"}') == ToolCall(name="finish", args={})


def test_native_mode_does_not_swallow_real_errors() -> None:
    import pytest

    c = FakeClient([FakeAPIError(400, "Function calling is not enabled")])
    with pytest.raises(FakeAPIError):
        _provider(c, mode="native").next_turn(HIST)
