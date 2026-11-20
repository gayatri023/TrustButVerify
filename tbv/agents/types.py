"""Provider-neutral message and transcript types."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

from tbv.core.models import RunStatus


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    ok: bool = True
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    truncated: bool = False


class Message(BaseModel):
    """One conversation turn. `raw` carries provider-specific objects (e.g. thought signatures)."""

    model_config = {"arbitrary_types_allowed": True}

    role: Literal["user", "assistant", "tool"]
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[tuple[str, ToolResult]] = Field(default_factory=list)  # (tool name, result)
    raw: Any = Field(default=None, exclude=True)


class ProviderTurn(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    raw: Any = Field(default=None, exclude=True)


class MetaRecord(BaseModel):
    kind: Literal["meta"] = "meta"
    run_id: str
    agent: str
    task_id: str
    repeat: int = 0
    attempt: int = 1
    model: str
    prompt_version: str
    config_hash: str
    seed_hash: str
    started_at: float


class StepRecord(BaseModel):
    kind: Literal["step"] = "step"
    step: int
    tool: str
    args: dict[str, Any]
    result: ToolResult
    text: str = ""
    workspace_hash: str
    ts: float
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None


class FinalRecord(BaseModel):
    kind: Literal["final"] = "final"
    status: RunStatus
    message: str = ""
    workspace_hash: str
    steps: int
    tokens_in: int
    tokens_out: int
    duration: float
    error: str | None = None


Record = Annotated[MetaRecord | StepRecord | FinalRecord, Field(discriminator="kind")]
_ADAPTER: TypeAdapter[Record] = TypeAdapter(Record)


def transcript_json_schema() -> dict[str, Any]:
    return _ADAPTER.json_schema()


class Transcript(BaseModel):
    meta: MetaRecord
    steps: list[StepRecord] = Field(default_factory=list)
    final: FinalRecord | None = None


def append_record(path: Path, rec: MetaRecord | StepRecord | FinalRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(rec.model_dump_json() + "\n")


def read_transcript(path: Path) -> Transcript:
    meta: MetaRecord | None = None
    steps: list[StepRecord] = []
    final: FinalRecord | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = _ADAPTER.validate_python(json.loads(line))
        if isinstance(rec, MetaRecord):
            meta = rec
        elif isinstance(rec, StepRecord):
            steps.append(rec)
        else:
            final = rec
    if meta is None:
        raise ValueError(f"{path}: transcript has no meta record")
    return Transcript(meta=meta, steps=steps, final=final)
