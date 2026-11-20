"""One attempt of one (agent, task) cell: run agent -> extract claims -> gate -> score hidden."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from tbv.agents.provider import Provider
from tbv.agents.runner import RunLimits, RunResult, run_agent
from tbv.agents.types import Message, MetaRecord, read_transcript
from tbv.core.config import GateConfig
from tbv.core.models import RunStatus
from tbv.gate.claims import LLM
from tbv.gate.pipeline import run_gate
from tbv.gate.verdict import GateReport
from tbv.sandbox.base import Executor
from tbv.sandbox.scoring import HiddenScore, score_hidden
from tbv.sandbox.workspace import copy_tree, hash_dir
from tbv.suite.task import Task


@dataclass
class AttemptOutcome:
    run: RunResult
    report: GateReport | None
    score: HiddenScore
    transcript_path: Path
    workspace: Path
    gate_seconds: float

    @property
    def claimed_done(self) -> bool:
        return self.run.status is RunStatus.FINISHED

    @property
    def completed_correctly(self) -> bool:
        """All pristine visible tests and all hidden tests pass."""
        return self.score.report.ok

    @property
    def false_completion(self) -> bool:
        return self.claimed_done and not self.completed_correctly


def execute_attempt(
    task: Task,
    provider: Provider,
    executor: Executor,
    gate: GateConfig,
    limits: RunLimits,
    work_dir: Path,
    *,
    agent: str,
    repeat: int = 0,
    attempt: int = 1,
    prompt_version: str = "agent.v1",
    config_hash: str = "",
    llm: LLM | None = None,
    history: list[Message] | None = None,
    followup: str | None = None,
    workspace: Path | None = None,
) -> AttemptOutcome:
    work_dir.mkdir(parents=True, exist_ok=True)
    ws = workspace or work_dir / "ws"
    if workspace is None:
        copy_tree(task.repo_dir, ws)
    tp = work_dir / f"transcript.attempt{attempt}.jsonl"
    meta = MetaRecord(
        run_id=f"{agent}:{task.spec.id}:{repeat}:{attempt}",
        agent=agent,
        task_id=task.spec.id,
        repeat=repeat,
        attempt=attempt,
        model=provider.model,
        prompt_version=prompt_version,
        config_hash=config_hash,
        seed_hash=hash_dir(task.repo_dir),
        started_at=time.time(),
    )
    run = run_agent(
        task.public(), provider, executor, ws, limits, tp, meta, history=history, followup=followup
    )
    report: GateReport | None = None
    if run.status is RunStatus.FINISHED:
        report = run_gate(
            task.public(),
            read_transcript(tp),
            task.repo_dir,
            ws,
            executor,
            gate,
            run.final_message,
            llm,
        )
    score = score_hidden(task, ws, executor, gate, task.spec.max_seconds * 2)
    return AttemptOutcome(run, report, score, tp, ws, report.gate_seconds if report else 0.0)
