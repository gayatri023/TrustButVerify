"""Gemini adapter (google-genai SDK; field names checked against SDK 3.5.0).

Robustness for models whose API support is unknown (Gemma): if the API rejects the system
instruction, the prompt is inlined into the first user message; if it rejects function calling,
the agent falls back to a JSON-in-text tool protocol. Not exercised against the real API in the
authoring environment; the fallback logic is unit-tested with a fake client."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from tbv.agents.ratelimit import QuotaLimiter
from tbv.agents.tools import TOOL_SPECS
from tbv.agents.types import Message, ProviderTurn, ToolCall
from tbv.core.config import AgentConfig

TEXT_TOOL_RULES = (
    "\n\nYou have these tools. To use one, reply with ONLY a JSON object on its own, like "
    '{"tool": "read_file", "args": {"path": "x.py"}} . One tool call per reply. Tools:\n'
)


def parse_text_tool_call(text: str) -> ToolCall | None:
    """First JSON object in `text` that names a known tool; None if there is none."""
    names = {t["name"] for t in TOOL_SPECS}
    for m in re.finditer(r"\{", text):
        depth = 0
        for i in range(m.start(), len(text)):
            depth += (text[i] == "{") - (text[i] == "}")
            if depth == 0:
                try:
                    obj = json.loads(text[m.start() : i + 1])
                except json.JSONDecodeError:
                    break
                if isinstance(obj, dict) and obj.get("tool") in names:
                    args = obj.get("args")
                    return ToolCall(
                        name=str(obj["tool"]), args=args if isinstance(args, dict) else {}
                    )
                break
    return None


class GeminiProvider:
    def __init__(
        self,
        cfg: AgentConfig,
        api_key: str,
        system_prompt: str,
        limiter: QuotaLimiter | None = None,
        client: Any | None = None,
    ) -> None:
        from google.genai import types

        self._types = types
        self.model = cfg.model
        self._cfg = cfg
        self._limiter = limiter
        self._system = system_prompt
        self._last_in = 0
        self._inline_system = False
        self._text_tools = cfg.tool_mode == "text"
        if client is None:
            from google import genai

            client = genai.Client(api_key=api_key)
        self._client = client

    # ---- request construction -------------------------------------------------------------
    def _tool_text(self) -> str:
        return TEXT_TOOL_RULES + "\n".join(
            f"- {t['name']}: {t['description']} args schema: {json.dumps(t['parameters'])}"
            for t in TOOL_SPECS
        )

    def _config(self) -> Any:
        t = self._types
        kw: dict[str, Any] = {"temperature": self._cfg.temperature}
        system = self._system + (self._tool_text() if self._text_tools else "")
        if not self._inline_system:
            kw["system_instruction"] = system
        if not self._text_tools:
            decls = [
                t.FunctionDeclaration(
                    name=s["name"],
                    description=s["description"],
                    parameters_json_schema=s["parameters"],
                )
                for s in TOOL_SPECS
            ]
            kw["tools"] = [t.Tool(function_declarations=decls)]
            kw["automatic_function_calling"] = t.AutomaticFunctionCallingConfig(disable=True)
        return t.GenerateContentConfig(**kw)

    def _first_user_prefix(self) -> str:
        if not self._inline_system:
            return ""
        return self._system + (self._tool_text() if self._text_tools else "") + "\n\n"

    def _contents(self, history: list[Message]) -> list[Any]:
        return self._contents_text(history) if self._text_tools else self._contents_native(history)

    def _contents_native(self, history: list[Message]) -> list[Any]:
        t = self._types
        out: list[Any] = []
        first_user = True
        for m in history:
            if m.role == "user":
                prefix = self._first_user_prefix() if first_user else ""
                first_user = False
                out.append(t.Content(role="user", parts=[t.Part(text=prefix + m.text)]))
            elif m.role == "assistant":
                if m.raw is not None:  # keep the model's own content (thought signatures)
                    out.append(m.raw)
                else:
                    parts = [t.Part(text=m.text)] if m.text else []
                    parts += [
                        t.Part(function_call=t.FunctionCall(name=c.name, args=c.args))
                        for c in m.tool_calls
                    ]
                    out.append(t.Content(role="model", parts=parts))
            else:
                parts = [
                    t.Part.from_function_response(
                        name=name,
                        response={
                            "ok": r.ok,
                            "exit_code": r.exit_code,
                            "stdout": r.stdout,
                            "stderr": r.stderr,
                        },
                    )
                    for name, r in m.tool_results
                ]
                out.append(t.Content(role="user", parts=parts))
        return out

    def _contents_text(self, history: list[Message]) -> list[Any]:
        t = self._types
        turns: list[tuple[str, str]] = []
        first_user = True
        for m in history:
            if m.role == "user":
                text = (self._first_user_prefix() if first_user else "") + m.text
                first_user = False
                role = "user"
            elif m.role == "assistant":
                role = "model"
                text = m.text or json.dumps(
                    {"tool": m.tool_calls[0].name, "args": m.tool_calls[0].args}
                    if m.tool_calls
                    else {}
                )
            else:
                role = "user"
                text = "\n".join(
                    f"Tool result for {n} (ok={r.ok}, exit_code={r.exit_code}):\n"
                    f"{r.stdout}\n{r.stderr}"
                    for n, r in m.tool_results
                )
            if turns and turns[-1][0] == role:  # keep roles alternating
                turns[-1] = (role, turns[-1][1] + "\n\n" + text)
            else:
                turns.append((role, text))
        return [t.Content(role=r, parts=[t.Part(text=x)]) for r, x in turns]

    # ---- call with fallbacks ----------------------------------------------------------------
    def next_turn(self, history: list[Message]) -> ProviderTurn:
        attempts = self._cfg.retry.max_retries + 3
        resp: Any = None
        for i in range(attempts):
            if self._limiter:
                self._limiter.acquire((self._last_in + 800) if self._last_in else 3000)
            try:
                resp = self._client.models.generate_content(
                    model=self.model, contents=self._contents(history), config=self._config()
                )
                break
            except Exception as exc:  # noqa: BLE001
                code = getattr(exc, "code", None)
                msg = str(exc).lower()
                if code == 400 and "instruction" in msg and not self._inline_system:
                    self._inline_system = True  # this model rejects a system instruction
                    continue
                if (
                    code == 400
                    and ("function" in msg or "tool" in msg)
                    and self._cfg.tool_mode == "auto"
                    and not self._text_tools
                ):
                    self._text_tools = True  # this model rejects function calling
                    continue
                if i == attempts - 1 or code not in (429, 500, 503):
                    raise
                time.sleep(self._cfg.retry.backoff_seconds * (2 ** min(i, 4)))
        cand = resp.candidates[0] if resp and resp.candidates else None
        content = cand.content if cand else None
        text, calls = "", []
        for p in (content.parts or []) if content else []:
            if getattr(p, "function_call", None) and p.function_call.name:
                calls.append(
                    ToolCall(name=p.function_call.name, args=dict(p.function_call.args or {}))
                )
            elif getattr(p, "text", None) and not getattr(p, "thought", False):
                text += p.text
        if self._text_tools:
            parsed = parse_text_tool_call(text)
            calls = [parsed] if parsed else []
        u = resp.usage_metadata if resp else None
        t_in = int(getattr(u, "prompt_token_count", 0) or 0) if u else 0
        self._last_in = t_in
        if self._limiter and t_in:
            self._limiter.settle(t_in)
        t_out = (
            int(getattr(u, "response_token_count", 0) or 0)
            + int(getattr(u, "thoughts_token_count", 0) or 0)
            if u
            else 0
        )
        raw = None if self._text_tools else content
        return ProviderTurn(text=text, tool_calls=calls, tokens_in=t_in, tokens_out=t_out, raw=raw)
