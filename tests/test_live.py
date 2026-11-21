from pathlib import Path

import pytest

from tbv.agents.provider import ScriptedProvider
from tbv.agents.runner import RunLimits
from tbv.core.config import Settings, load_agents, load_gate
from tbv.core.models import Split
from tbv.experiment.orchestrator import AgentSpec
from tbv.experiment.store import Store
from tbv.live import Matrix, dry_run, require_ready, run_experiment, select_tasks
from tbv.sandbox.local_executor import LocalExecutor
from tbv.scenarios import SCENARIOS
from tbv.suite.task import load_tasks

GATE = load_gate()


def test_unconfigured_agents_are_refused_with_a_helpful_message() -> None:
    g = next(a for a in load_agents().agents if a.name == "gemma-4-31b")
    with pytest.raises(RuntimeError, match="tbv models"):
        require_ready(g, Settings(gemini_api_key="k"))


def _specs(names: list[str]) -> list[AgentSpec]:
    out = []
    for sc in SCENARIOS:
        if sc.name in names:
            turns = sc.turns + sc.retry_turns
            out.append(
                AgentSpec(
                    sc.name,
                    lambda t=turns: ScriptedProvider(t),
                    RunLimits(),  # type: ignore[misc]
                    "cfg",
                    "scripted",
                )
            )
    return out


def test_run_experiment_resumes_and_respects_split_selection(
    example_tasks: Path, tmp_path: Path
) -> None:
    tasks = load_tasks(example_tasks)
    store = Store(tmp_path / "r.sqlite")
    # scenario agents only know bug-001: restrict the matrix to that task
    mx = Matrix(agents=["honest_fix"], tasks=["bug-001"], split="dev")
    splits = {t.spec.id: Split.DEV for t in tasks}
    assert [t.spec.id for t in select_tasks(mx, tasks, splits)] == ["bug-001"]
    specs = _specs(["honest_fix"])
    s1 = run_experiment(store, specs, tasks, splits, mx, LocalExecutor(), GATE, tmp_path / "w")
    s2 = run_experiment(store, specs, tasks, splits, mx, LocalExecutor(), GATE, tmp_path / "w")
    assert (s1.ran, s2.ran, s2.skipped) == (1, 0, 1)
    test_mx = Matrix(agents=["honest_fix"], tasks=["bug-001"], split="test")
    assert select_tasks(test_mx, tasks, splits) == []  # TEST tasks only when asked for


def test_dry_run_projects_from_a_sample(example_tasks: Path, tmp_path: Path) -> None:
    tasks = load_tasks(example_tasks)
    mx = Matrix(agents=["echo_fake"], tasks=["bug-001"])
    p = dry_run(
        _specs(["echo_fake"]),
        tasks,
        {},
        mx,
        LocalExecutor(),
        GATE,
        n_total_runs=60,
        rpd=500,
        tpm=250_000,
        sample=1,
    )
    assert p.requests > 0 and p.retry_fraction == 1.0 and p.days_at_rpd >= 1
