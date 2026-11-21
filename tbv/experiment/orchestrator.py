"""Run a matrix of (agent, task) cells: resumable, idempotent, TEST-guarded, quota-aware."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tbv.agents.provider import Provider
from tbv.agents.ratelimit import DailyQuotaExhausted
from tbv.agents.runner import RunLimits
from tbv.core.config import GateConfig, config_hash
from tbv.core.models import ClaimType, ClaimVerdict, Severity, Split
from tbv.experiment.cell import AttemptOutcome, execute_attempt
from tbv.experiment.store import Store, TestSplitGuard
from tbv.gate.claims import LLM
from tbv.gate.retry import assert_no_leak, build_feedback, needs_retry
from tbv.sandbox.base import Executor
from tbv.sandbox.workspace import read_text, snapshot
from tbv.suite.task import Task


@dataclass
class AgentSpec:
    name: str
    make_provider: Callable[[], Provider]
    limits: RunLimits
    config_hash: str = ""
    model: str = ""
    limiter: object | None = None  # optional QuotaLimiter, for quota accounting


@dataclass
class Summary:
    ran: int = 0
    skipped: int = 0
    paused_until: float | None = None


def classify_false_completion(out: AttemptOutcome) -> str | None:
    """Failure taxonomy for one false completion (None if the run was not one)."""
    if not out.false_completion or out.report is None:
        return None
    r = out.report
    contradicted = [c for c in r.claims if c.verdict is ClaimVerdict.CONTRADICTED]
    if any(c.claim.type is ClaimType.FILE_CREATED_OR_CHANGED for c in contradicted):
        return "hallucinated_file"
    if any(t.severity is Severity.HIGH for t in r.tamper):
        return "tampered"
    if contradicted:
        return "contradicted_claim"
    if any(c.verdict is ClaimVerdict.UNSUPPORTED for c in r.claims):
        return "unsupported_claim"
    return "incomplete_but_visible_pass"


def hidden_strings(task: Task) -> list[str]:
    """Everything that must never appear in feedback sent to the agent."""
    out = {task.spec.hidden_requirement, "hidden_tests"}
    for rel in snapshot(task.hidden_dir):
        out.add(Path(rel).stem)
        out.update(re.findall(r"def (test_\w+)", read_text(task.hidden_dir / rel)))
    return sorted(s for s in out if s)


def record(
    store: Store,
    out: AttemptOutcome,
    task: Task,
    split: Split,
    agent: AgentSpec,
    repeat: int,
    attempt: int,
    gate: GateConfig,
    fixture: bool,
) -> None:
    import time

    key = {"agent": agent.name, "task": task.spec.id, "repeat": repeat, "attempt": attempt}
    rep = out.report
    store.insert(
        "runs",
        {
            **key,
            "split": split.value,
            "task_type": task.spec.type.value,
            "difficulty": task.spec.difficulty.value,
            "status": out.run.status.value,
            "claimed_done": int(out.claimed_done),
            "final_message": out.run.final_message,
            "steps": out.run.steps,
            "tokens_in": out.run.tokens_in,
            "tokens_out": out.run.tokens_out,
            "run_seconds": out.run.duration,
            "gate_overall": rep.overall.value if rep else None,
            "gate_seconds": out.gate_seconds,
            "extraction_method": rep.extraction_method if rep else None,
            "completed_correctly": int(out.completed_correctly),
            "hidden_only_ok": int(out.score.hidden.ok),
            "visible_ok": int(out.score.visible.ok),
            "tampered": int(bool(rep and any(t.severity is Severity.HIGH for t in rep.tamper))),
            "taxonomy": classify_false_completion(out),
            "model": agent.model,
            "config_hash": agent.config_hash,
            "gate_version": gate.version,
            "fixture": int(fixture),
            "created_at": time.time(),
        },
    )
    if rep:
        for i, cr in enumerate(rep.claims):
            store.insert(
                "claims",
                {
                    **key,
                    "idx": i,
                    "type": cr.claim.type.value,
                    "polarity": cr.claim.polarity.value,
                    "verdict": cr.verdict.value,
                    "reason": cr.reason,
                    "span": cr.claim.text_span,
                    "implicit": int(cr.claim.implicit),
                },
            )
        for v in rep.verifiers:
            store.insert(
                "verifiers",
                {**key, "name": v.name, "status": v.status.value, "runtime_s": v.runtime_s},
            )
        for t in rep.tamper:
            store.insert(
                "tamper",
                {**key, "rule_id": t.rule_id, "severity": t.severity.value, "path": t.path},
            )


def run_cell(
    store: Store,
    task: Task,
    split: Split,
    agent: AgentSpec,
    executor: Executor,
    gate: GateConfig,
    work_root: Path,
    *,
    repeat: int = 0,
    retry_steps: int = 10,
    llm: LLM | None = None,
    fixture: bool = False,
    on_attempt: Callable[[str, str, int, AttemptOutcome], None] | None = None,
) -> bool:
    """Run attempt 1 (+ one gated retry). Returns False if the cell was already done."""
    if store.has_run(agent.name, task.spec.id, repeat, 1):
        return False
    work = work_root / agent.name / task.spec.id / str(repeat)
    provider = agent.make_provider()
    a1 = execute_attempt(
        task,
        provider,
        executor,
        gate,
        agent.limits,
        work,
        agent=agent.name,
        repeat=repeat,
        attempt=1,
        config_hash=agent.config_hash,
        llm=llm,
    )
    record(store, a1, task, split, agent, repeat, 1, gate, fixture)
    if on_attempt:
        on_attempt(agent.name, task.spec.id, 1, a1)
    if a1.report is not None and needs_retry(a1.report):
        feedback = build_feedback(a1.report)
        assert_no_leak(feedback, hidden_strings(task))
        retry_limits = RunLimits(
            max_steps=retry_steps,
            max_wall_seconds=agent.limits.max_wall_seconds,
            max_tokens=agent.limits.max_tokens,
            command_timeout=agent.limits.command_timeout,
        )
        a2 = execute_attempt(
            task,
            provider,
            executor,
            gate,
            retry_limits,
            work,
            agent=agent.name,
            repeat=repeat,
            attempt=2,
            config_hash=agent.config_hash,
            llm=llm,
            history=a1.run.history,
            followup=feedback,
            workspace=a1.workspace,
        )
        record(store, a2, task, split, agent, repeat, 2, gate, fixture)
        if on_attempt:
            on_attempt(agent.name, task.spec.id, 2, a2)
    return True


def run_matrix(
    store: Store,
    cells: list[tuple[AgentSpec, Task]],
    splits: dict[str, Split],
    executor: Executor,
    gate: GateConfig,
    work_root: Path,
    *,
    final: bool = False,
    fixture: bool = False,
    repeat: int = 0,
    retry_steps: int = 10,
    llm: LLM | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
    on_attempt: Callable[[str, str, int, AttemptOutcome], None] | None = None,
) -> Summary:
    summary = Summary()
    uses_test = any(splits.get(t.spec.id) is Split.TEST for _, t in cells)
    if uses_test:
        if not final:
            raise TestSplitGuard("TEST-split tasks require --final (they are evaluated once)")
        store.lock_test_config(
            config_hash(
                {
                    "gate": gate.model_dump(mode="json"),
                    "agents": sorted(a.config_hash for a, _ in cells),
                }
            )
        )
    for i, (agent, task) in enumerate(cells, 1):
        split = splits.get(task.spec.id, Split.DEV)
        try:
            if run_cell(
                store,
                task,
                split,
                agent,
                executor,
                gate,
                work_root,
                repeat=repeat,
                retry_steps=retry_steps,
                on_attempt=on_attempt,
                llm=llm,
                fixture=fixture,
            ):
                summary.ran += 1
            else:
                summary.skipped += 1
        except DailyQuotaExhausted as exc:
            summary.paused_until = exc.reset_at
            break
        if on_progress:
            on_progress(i, len(cells), f"{agent.name} / {task.spec.id}")
    return summary
