from pathlib import Path

import pytest

from tbv.agents.provider import ScriptedProvider
from tbv.agents.ratelimit import QuotaLimiter
from tbv.agents.runner import RunLimits, compact_history
from tbv.agents.types import Message, ToolResult
from tbv.core.config import Settings, load_agents, load_gate
from tbv.core.models import Split
from tbv.experiment.orchestrator import AgentSpec
from tbv.experiment.projection import project
from tbv.experiment.store import Store
from tbv.live import Matrix, dry_run, require_ready, run_experiment, select_tasks
from tbv.sandbox.local_executor import LocalExecutor
from tbv.scenarios import SCENARIOS
from tbv.suite.task import load_tasks

GATE = load_gate()


def test_tpm_limiter_waits_for_the_minute_window() -> None:
    now = [1_700_000_000.0]
    slept: list[float] = []

    def sleep(s: float) -> None:
        slept.append(s)
        now[0] += s

    lim = QuotaLimiter(rpm=30, rpd=100, tpm=1000, clock=lambda: now[0], sleep=sleep)
    lim.acquire(600)
    lim.acquire(600)  # 600 + 600 > 1000: must wait for the first request to leave the window
    assert slept == [60.0]
    lim.settle(100)  # real usage was small, so the next request fits immediately
    lim.acquire(600)
    assert slept == [60.0]
    with pytest.raises(ValueError, match="exceeds"):
        lim.acquire(1001)


def test_compaction_keeps_pairs_and_recent_output() -> None:
    big = ToolResult(stdout="x" * 5000)
    msgs = [Message(role="user", text="task")]
    for _ in range(5):
        msgs.append(Message(role="assistant", text="call"))
        msgs.append(Message(role="tool", tool_results=[("read_file", big)]))
    out = compact_history(msgs, 4)
    assert len(out) == len(msgs)
    assert all("omitted" in m.tool_results[0][1].stdout for m in out[:-4] if m.role == "tool")
    assert out[-1].tool_results[0][1].stdout == "x" * 5000  # recent output untouched
    assert compact_history(msgs, None) is msgs


def test_projection_hand_computed() -> None:
    p = project([10, 20], [10_000, 20_000], [False, False], [], n_runs=100, rpd=500, tpm=16_000)
    assert p.requests == 1500 and p.days_at_rpd == 3
    assert p.minutes_at_tpm == pytest.approx(100 * 15_000 / 16_000)
    q = project([10, 10], [1000, 1000], [True, False], [4], n_runs=10, rpd=1000, tpm=None)
    assert q.requests == pytest.approx(10 * (10 + 0.5 * 4)) and q.retry_fraction == 0.5


def test_shipped_agents_have_limits_but_placeholder_models() -> None:
    cfgs = {a.name: a for a in load_agents().agents}
    g, f = cfgs["gemma-4-31b"], cfgs["gemini-3-1-flash-lite"]
    assert (g.rpm, g.tpm, g.rpd) == (30, 16000, 14400)  # read from the AI Studio screenshot
    assert (f.rpm, f.tpm, f.rpd) == (15, 250000, 500)
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
