"""Gemini adapter (google-genai SDK). Written against SDK 3.5.0's real field names.

NOTE: not exercised in the authoring environment (no network, no key). First real run: use
`tbv run` on one easy task and read the transcript before trusting anything else.
"""

from __future__ import annotations

import time
from typing import Any

from tbv.agents.ratelimit import QuotaLimiter
from tbv.agents.tools import TOOL_SPECS
from tbv.agents.types import Message, ProviderTurn, ToolCall
from tbv.core.config import AgentConfig


class GeminiProvider:
    def __init__(
        self,
        cfg: AgentConfig,
        api_key: str,
        system_prompt: str,
        limiter: QuotaLimiter | None = None,
    ) -> None:
        from google import genai
        from google.genai import types

        self._types = types
        self.model = cfg.model
        self._cfg = cfg
        self._limiter = limiter
        self._client = genai.Client(api_key=api_key)
        decls = [
            types.FunctionDeclaration(
                name=t["name"], description=t["description"], parameters_json_schema=t["parameters"]
            )
            for t in TOOL_SPECS
        ]
        self._config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=cfg.temperature,
            tools=[types.Tool(function_declarations=decls)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    def _contents(self, history: list[Message]) -> list[Any]:
        t = self._types
        out: list[Any] = []
        for m in history:
            if m.role == "user":
                out.append(t.Content(role="user", parts=[t.Part(text=m.text)]))
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

    def next_turn(self, history: list[Message]) -> ProviderTurn:
        attempts = self._cfg.retry.max_retries + 1
        for i in range(attempts):
            if self._limiter:
                self._limiter.acquire()
            try:
                resp = self._client.models.generate_content(
                    model=self.model, contents=self._contents(history), config=self._config
                )
                break
            except Exception as exc:  # noqa: BLE001
                code = getattr(exc, "code", None)
                if i == attempts - 1 or code not in (429, 500, 503):
                    raise
                time.sleep(self._cfg.retry.backoff_seconds * (2**i))
        cand = resp.candidates[0] if resp.candidates else None
        content = cand.content if cand else None
        text, calls = "", []
        for p in (content.parts or []) if content else []:
            if p.function_call and p.function_call.name:
                calls.append(
                    ToolCall(name=p.function_call.name, args=dict(p.function_call.args or {}))
                )
            elif p.text and not p.thought:
                text += p.text
        u = resp.usage_metadata
        t_in = int(getattr(u, "prompt_token_count", 0) or 0) if u else 0
        t_out = (
            int(getattr(u, "response_token_count", 0) or 0)
            + int(getattr(u, "thoughts_token_count", 0) or 0)
            if u
            else 0
        )
        return ProviderTurn(
            text=text, tool_calls=calls, tokens_in=t_in, tokens_out=t_out, raw=content
        )
