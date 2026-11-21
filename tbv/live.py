"""Live wiring: real Gemini providers + Docker executor behind `tbv run` and `tbv experiment`.

NOT exercised in the authoring environment (no Docker, no API key). The orchestration it calls is
tested with fakes (tests/test_live.py); the first real run should be one easy task."""

from __future__ import annotations

import datetime as dt
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from tbv.agents.gemini_provider import GeminiProvider
from tbv.agents.provider import Provider
from tbv.agents.ratelimit import QuotaLimiter, _pacific_day
from tbv.agents.runner import RunLimits
from tbv.core.config import CONFIG_DIR, AgentConfig, GateConfig, Settings, config_hash
from tbv.core.models import Split
from tbv.experiment.orchestrator import AgentSpec, Summary, run_matrix
from tbv.experiment.projection import Projection, project
from tbv.experiment.store import Store
from tbv.sandbox.base import Executor
from tbv.suite.task import Task


class Matrix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agents: list[str]
    split: Literal["dev", "test", "all"] = "dev"
    tasks: list[str] | None = None
    repeats: int = 1
    retry_steps: int = 10


def load_matrix(path: Path) -> Matrix:
    return Matrix.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def system_prompt() -> str:
    return (CONFIG_DIR / "prompts" / "agent.v1.txt").read_text(encoding="utf-8").strip()


def require_ready(cfg: AgentConfig, settings: Settings) -> None:
    if not cfg.is_configured:
        raise RuntimeError(f"{cfg.name}: model id not set in config/agents.yaml (run `tbv models`)")
    if not (cfg.rpm and cfg.rpd):
        raise RuntimeError(f"{cfg.name}: set rpm, tpm and rpd from the AI Studio rate-limit page")
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not set (Codespaces secret or .env)")


def make_spec(cfg: AgentConfig, settings: Settings, store: Store) -> AgentSpec:
    require_ready(cfg, settings)
    day = _pacific_day(dt.datetime.now(dt.UTC).timestamp())
    limiter = QuotaLimiter(
        cfg.rpm or 1,
        cfg.rpd or 1,
        tpm=cfg.tpm,
        used_today=store.used_quota(cfg.model, day),
        day=day,
    )
    prompt = system_prompt()
    key = settings.gemini_api_key or ""

    def factory() -> Provider:
        return GeminiProvider(cfg, key, prompt, limiter)

    limits = RunLimits(
        max_steps=cfg.max_steps,
        max_wall_seconds=cfg.max_wall_seconds,
        max_tokens=cfg.max_tokens,
        context_keep_last=cfg.context_keep_last,
        max_tool_chars=cfg.max_tool_chars,
    )
    return AgentSpec(cfg.name, factory, limits, config_hash(cfg), cfg.model, limiter)


def select_tasks(matrix: Matrix, tasks: list[Task], splits: dict[str, Split]) -> list[Task]:
    chosen = [t for t in tasks if matrix.tasks is None or t.spec.id in matrix.tasks]
    if matrix.split != "all":
        want = Split.DEV if matrix.split == "dev" else Split.TEST
        chosen = [t for t in chosen if splits.get(t.spec.id, Split.DEV) is want]
    return chosen


def sync_quota(store: Store, spec: AgentSpec, before: int) -> None:
    lim = spec.limiter
    if isinstance(lim, QuotaLimiter) and lim.used_today > before:
        store.add_quota(spec.model, lim.day, lim.used_today - before)


def run_experiment(
    store: Store,
    specs: list[AgentSpec],
    tasks: list[Task],
    splits: dict[str, Split],
    matrix: Matrix,
    executor: Executor,
    gate: GateConfig,
    work_root: Path,
    *,
    final: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> Summary:
    total = Summary()
    chosen = select_tasks(matrix, tasks, splits)
    for repeat in range(matrix.repeats):
        for spec in specs:
            before = spec.limiter.used_today if isinstance(spec.limiter, QuotaLimiter) else 0
            s = run_matrix(
                store,
                [(spec, t) for t in chosen],
                splits,
                executor,
                gate,
                work_root,
                final=final,
                repeat=repeat,
                retry_steps=matrix.retry_steps,
                on_progress=on_progress,
            )
            sync_quota(store, spec, before)
            total.ran += s.ran
            total.skipped += s.skipped
            if s.paused_until:
                total.paused_until = s.paused_until
                return total
    return total


def dry_run(
    specs: list[AgentSpec],
    tasks: list[Task],
    splits: dict[str, Split],
    matrix: Matrix,
    executor: Executor,
    gate: GateConfig,
    n_total_runs: int,
    rpd: int,
    tpm: int | None,
    sample: int = 5,
) -> Projection:
    """Run `sample` tasks into a throwaway store and project the whole matrix."""
    store = Store(":memory:")
    chosen = select_tasks(matrix, tasks, splits)[:sample]
    with tempfile.TemporaryDirectory(prefix="tbv-dry-") as td:
        for spec in specs[:1]:
            run_matrix(
                store,
                [(spec, t) for t in chosen],
                {},
                executor,
                gate,
                Path(td),
                retry_steps=matrix.retry_steps,
            )
    rows = store.con.execute("SELECT attempt, steps, tokens_in FROM runs").fetchall()
    a1 = [r for r in rows if r["attempt"] == 1]
    a2 = [r for r in rows if r["attempt"] == 2]
    return project(
        [r["steps"] for r in a1],
        [r["tokens_in"] for r in a1],
        [True] * len(a2) + [False] * (len(a1) - len(a2)),
        [r["steps"] for r in a2],
        n_total_runs,
        rpd,
        tpm,
    )
