from pathlib import Path

import pytest

from tbv.agents.provider import ScriptedProvider
from tbv.agents.ratelimit import DailyQuotaExhausted
from tbv.agents.runner import RunLimits
from tbv.core.config import load_gate
from tbv.core.models import Split
from tbv.experiment import orchestrator as orch
from tbv.experiment.orchestrator import AgentSpec, run_matrix
from tbv.experiment.store import Store, TestSplitGuard
from tbv.gate.retry import HiddenLeak
from tbv.sandbox.local_executor import LocalExecutor
from tbv.scenarios import SCENARIOS
from tbv.suite.splits import load_splits, make_splits, write_splits
from tbv.suite.task import Task, load_tasks

GATE = load_gate()


def _cells(tasks: dict[str, Task], names: list[str]) -> list[tuple[AgentSpec, Task]]:
    out = []
    for sc in SCENARIOS:
        if sc.name in names:
            turns = sc.turns + sc.retry_turns
            out.append(
                (
                    AgentSpec(
                        sc.name,
                        lambda t=turns: ScriptedProvider(t),
                        RunLimits(),  # type: ignore[misc]
                        "cfg",
                        "scripted",
                    ),
                    tasks[sc.task_id],
                )
            )
    return out


@pytest.fixture
def tasks(example_tasks: Path) -> dict[str, Task]:
    return {t.spec.id: t for t in load_tasks(example_tasks)}


def test_resume_is_idempotent_and_records_retry(tasks: dict[str, Task], tmp_path: Path) -> None:
    store = Store(tmp_path / "r.sqlite")
    cells = _cells(tasks, ["honest_fix", "echo_fake", "silent_done"])
    s1 = run_matrix(store, cells[:1], {}, LocalExecutor(), GATE, tmp_path / "w", fixture=True)
    assert (s1.ran, s1.skipped) == (1, 0)  # "interrupted" after the first cell
    s2 = run_matrix(store, cells, {}, LocalExecutor(), GATE, tmp_path / "w", fixture=True)
    assert (s2.ran, s2.skipped) == (2, 1)  # resumes: only the two remaining cells run
    s3 = run_matrix(store, cells, {}, LocalExecutor(), GATE, tmp_path / "w", fixture=True)
    assert (s3.ran, s3.skipped) == (0, 3)
    rows = store.con.execute(
        "SELECT agent, attempt, gate_overall, completed_correctly FROM runs ORDER BY agent, attempt"
    ).fetchall()
    keys = [(r["agent"], r["attempt"]) for r in rows]
    assert len(keys) == len(set(keys))  # no duplicates
    echo = [r for r in rows if r["agent"] == "echo_fake"]
    assert [(r["attempt"], r["gate_overall"], r["completed_correctly"]) for r in echo] == [
        (1, "BLOCK", 0),
        (2, "PASS", 1),
    ]  # blocked, retried, rescued


def test_test_split_guard(tasks: dict[str, Task], tmp_path: Path) -> None:
    store = Store(tmp_path / "r.sqlite")
    cells = _cells(tasks, ["honest_fix"])
    splits = {"bug-001": Split.TEST}
    with pytest.raises(TestSplitGuard, match="--final"):
        run_matrix(store, cells, splits, LocalExecutor(), GATE, tmp_path / "w")
    run_matrix(store, cells, splits, LocalExecutor(), GATE, tmp_path / "w", final=True)
    changed = GATE.model_copy(update={"hardcode_min_string_len": 9})
    with pytest.raises(TestSplitGuard, match="config changed"):
        run_matrix(store, cells, splits, LocalExecutor(), changed, tmp_path / "w2", final=True)


def test_leak_guard_blocks_hidden_content_in_feedback(
    tasks: dict[str, Task], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(orch, "build_feedback", lambda report: "see test_window_equals_length")
    store = Store(tmp_path / "r.sqlite")
    with pytest.raises(HiddenLeak):
        run_matrix(store, _cells(tasks, ["echo_fake"]), {}, LocalExecutor(), GATE, tmp_path / "w")


def test_daily_quota_pauses_without_recording_a_failure(
    tasks: dict[str, Task], tmp_path: Path
) -> None:
    class Quota:
        model = "q"

        def next_turn(self, history: list) -> None:  # type: ignore[type-arg]
            raise DailyQuotaExhausted(1234.0)

    spec = AgentSpec("q", lambda: Quota(), RunLimits(), "c", "q")  # type: ignore[arg-type,return-value]
    store = Store(tmp_path / "r.sqlite")
    s = run_matrix(store, [(spec, tasks["bug-001"])], {}, LocalExecutor(), GATE, tmp_path / "w")
    assert s.paused_until == 1234.0 and s.ran == 0
    assert store.con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0  # resumable later


def test_splits_are_stratified_deterministic_and_frozen(
    tasks: dict[str, Task], tmp_path: Path
) -> None:
    lst = list(tasks.values())
    a, b = make_splits(lst, 2), make_splits(lst, 2)
    assert a == b and len(a["test"]) == 2 and set(a["test"]).isdisjoint(a["dev"])
    assert len(a["test"]) + len(a["dev"]) == len(lst)
    p = tmp_path / "splits.yaml"
    write_splits(p, a)
    assert load_splits(p)[a["test"][0]] is Split.TEST
    with pytest.raises(RuntimeError, match="frozen"):
        write_splits(p, a)


def test_demo_end_to_end(tmp_path: Path) -> None:
    from rich.console import Console

    from tbv.demo import run_demo

    html = run_demo(tmp_path / "demo", Console(quiet=True)).read_text(encoding="utf-8")
    assert "SYNTHETIC FIXTURE DATA" in html and "False-completion rate" in html
    assert (tmp_path / "demo" / "reports" / "echo_fake.attempt2.md").exists()
    memo = (tmp_path / "demo" / "memo.html").read_text(encoding="utf-8")
    assert "SYNTHETIC FIXTURE DATA" in memo and "Recommendation" in memo and "Limitations" in memo


def test_repeat_index_creates_distinct_rows(tasks: dict[str, Task], tmp_path: Path) -> None:
    store = Store(tmp_path / "r.sqlite")
    cells = _cells(tasks, ["honest_fix"])
    run_matrix(store, cells, {}, LocalExecutor(), GATE, tmp_path / "w", repeat=0)
    s = run_matrix(store, cells, {}, LocalExecutor(), GATE, tmp_path / "w", repeat=1)
    assert s.ran == 1
    reps = [r["repeat"] for r in store.con.execute("SELECT repeat FROM runs WHERE attempt=1")]
    assert sorted(reps) == [0, 1]


def test_split_is_stratified_when_possible(example_tasks: Path) -> None:
    lst = load_tasks(example_tasks)
    types = {t.spec.type for t in lst}
    sp = make_splits(lst, len(types))
    test_types = {t.spec.type for t in lst if t.spec.id in sp["test"]}
    assert test_types == types and len(sp["test"]) == len(types)  # one task of every type
