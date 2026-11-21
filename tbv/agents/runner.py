"""The agent loop: provider <-> tools, with step/wall/token limits and a JSONL transcript."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from tbv.agents.provider import Provider
from tbv.agents.ratelimit import DailyQuotaExhausted
from tbv.agents.tools import ToolBox
from tbv.agents.types import (
    FinalRecord,
    Message,
    MetaRecord,
    StepRecord,
    ToolResult,
    append_record,
)
from tbv.core.models import RunStatus
from tbv.sandbox.base import Executor
from tbv.sandbox.workspace import hash_dir
from tbv.suite.task import PublicTask


@dataclass
class RunLimits:
    max_steps: int = 30  # provider turns (== API requests)
    max_wall_seconds: float = 900
    max_tokens: int = 200_000
    command_timeout: float = 60
    context_keep_last: int | None = None  # compact tool output older than the last N messages
    max_tool_chars: int = 20_000


@dataclass
class RunResult:
    status: RunStatus
    final_message: str
    steps: int
    tokens_in: int
    tokens_out: int
    duration: float
    history: list[Message] = field(default_factory=list)
    workspace_hash: str = ""
    error: str | None = None


def compact_history(msgs: list[Message], keep_last: int | None) -> list[Message]:
    """Model-visible history: old tool outputs become stubs (keeps call/response pairing intact)."""
    if keep_last is None or len(msgs) <= keep_last:
        return msgs
    stub = ToolResult(ok=True, stdout="[earlier output omitted to save context]")
    out: list[Message] = []
    for i, m in enumerate(msgs):
        if m.role == "tool" and i < len(msgs) - keep_last:
            out.append(Message(role="tool", tool_results=[(n, stub) for n, _ in m.tool_results]))
        else:
            out.append(m)
    return out


def run_agent(
    public: PublicTask,
    provider: Provider,
    executor: Executor,
    workspace: Path,
    limits: RunLimits,
    transcript_path: Path,
    meta: MetaRecord,
    *,
    history: list[Message] | None = None,
    followup: str | None = None,
) -> RunResult:
    start = time.monotonic()
    append_record(transcript_path, meta)
    msgs = list(history) if history else [Message(role="user", text=public.instruction)]
    if followup:
        msgs.append(Message(role="user", text=followup))
    toolbox = ToolBox(workspace, executor, limits.command_timeout, limits.max_tool_chars)
    t_in = t_out = turns = step_no = 0
    status, final_msg, error = RunStatus.BUDGET_EXHAUSTED, "", None

    def finish_record() -> RunResult:
        wh = hash_dir(workspace)
        dur = time.monotonic() - start
        append_record(
            transcript_path,
            FinalRecord(
                status=status,
                message=final_msg,
                workspace_hash=wh,
                steps=turns,
                tokens_in=t_in,
                tokens_out=t_out,
                duration=dur,
                error=error,
            ),
        )
        return RunResult(status, final_msg, turns, t_in, t_out, dur, msgs, wh, error)

    while turns < limits.max_steps:
        if time.monotonic() - start > limits.max_wall_seconds or t_in + t_out > limits.max_tokens:
            break
        try:
            out = provider.next_turn(compact_history(msgs, limits.context_keep_last))
        except DailyQuotaExhausted:
            raise  # not the agent's fault: the experiment runner pauses and resumes later
        except Exception as exc:  # noqa: BLE001 - provider failures end the run as `error`
            status, error = RunStatus.ERROR, f"{type(exc).__name__}: {exc}"
            return finish_record()
        turns += 1
        t_in += out.tokens_in
        t_out += out.tokens_out
        if not out.tool_calls:  # the agent stopped talking to tools: its text is the final claim
            msgs.append(Message(role="assistant", text=out.text, raw=out.raw))
            status, final_msg = RunStatus.FINISHED, out.text
            return finish_record()
        msgs.append(
            Message(role="assistant", text=out.text, tool_calls=out.tool_calls, raw=out.raw)
        )
        results: list[tuple[str, ToolResult]] = []
        done = False
        for tc in out.tool_calls:
            if tc.name == "finish":
                res = ToolResult(stdout="finished")
                final_msg, done = str(tc.args.get("message", "")), True
            else:
                res = toolbox.execute(tc)
            step_no += 1
            append_record(
                transcript_path,
                StepRecord(
                    step=step_no,
                    tool=tc.name,
                    args=tc.args,
                    result=res,
                    text=out.text,
                    workspace_hash=hash_dir(workspace),
                    ts=time.time(),
                    tokens_in=out.tokens_in,
                    tokens_out=out.tokens_out,
                ),
            )
            results.append((tc.name, res))
            if done:
                break
        msgs.append(Message(role="tool", tool_results=results))
        if done:
            status = RunStatus.FINISHED
            return finish_record()
    return finish_record()
