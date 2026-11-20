from pathlib import Path

import pytest

from tbv.agents.provider import ScriptedProvider, call, turn
from tbv.agents.ratelimit import DailyQuotaExhausted, QuotaLimiter, next_reset
from tbv.agents.runner import RunLimits, run_agent
from tbv.agents.tools import ToolBox
from tbv.agents.types import (
    MetaRecord,
    ToolCall,
    read_transcript,
    transcript_json_schema,
)
from tbv.core.models import RunStatus
from tbv.sandbox.local_executor import LocalExecutor
from tbv.sandbox.workspace import copy_tree
from tbv.suite.task import load_tasks


def _meta(task_id: str = "bug-001") -> MetaRecord:
    return MetaRecord(
        run_id="r1",
        agent="a",
        task_id=task_id,
        model="scripted",
        prompt_version="agent.v1",
        config_hash="h",
        seed_hash="s",
        started_at=0.0,
    )


def _setup(example_tasks: Path, tmp_path: Path, tid: str = "bug-001"):  # type: ignore[no-untyped-def]
    task = next(t for t in load_tasks(example_tasks) if t.spec.id == tid)
    ws = tmp_path / "ws"
    copy_tree(task.repo_dir, ws)
    return task, ws


def test_full_episode_with_transcript(example_tasks: Path, tmp_path: Path) -> None:
    task, ws = _setup(example_tasks, tmp_path)
    fix = "def moving_sum(values, k):\n    return [sum(values[i:i+k]) for i in range(len(values)-k+1)]\n"
    prov = ScriptedProvider(
        [
            turn(call("read_file", path="windows.py")),
            turn(call("write_file", path="windows.py", content=fix)),
            turn(call("run_command", cmd="python -m pytest -q")),
            turn(call("finish", message="Fixed the off-by-one; tests pass.")),
        ]
    )
    tp = tmp_path / "t.jsonl"
    res = run_agent(task.public(), prov, LocalExecutor(), ws, RunLimits(), tp, _meta())
    assert res.status is RunStatus.FINISHED and "Fixed" in res.final_message
    tr = read_transcript(tp)
    assert [s.tool for s in tr.steps] == ["read_file", "write_file", "run_command", "finish"]
    assert tr.steps[0].workspace_hash != tr.steps[1].workspace_hash  # the write changed the tree
    assert tr.steps[1].workspace_hash == tr.steps[2].workspace_hash  # running tests did not
    assert tr.steps[2].result.exit_code == 0
    assert tr.final is not None and tr.final.status is RunStatus.FINISHED
    schema = transcript_json_schema()
    assert "MetaRecord" in str(schema)


def test_step_cap_ends_as_budget_exhausted(example_tasks: Path, tmp_path: Path) -> None:
    task, ws = _setup(example_tasks, tmp_path)
    prov = ScriptedProvider([turn(call("list_files")) for _ in range(10)])
    res = run_agent(
        task.public(),
        prov,
        LocalExecutor(),
        ws,
        RunLimits(max_steps=3),
        tmp_path / "t.jsonl",
        _meta(),
    )
    assert res.status is RunStatus.BUDGET_EXHAUSTED and res.steps == 3


def test_provider_error_ends_as_error(example_tasks: Path, tmp_path: Path) -> None:
    task, ws = _setup(example_tasks, tmp_path)
    res = run_agent(
        task.public(),
        ScriptedProvider([]),
        LocalExecutor(),
        ws,
        RunLimits(),
        tmp_path / "t.jsonl",
        _meta(),
    )
    assert res.status is RunStatus.ERROR and res.error


def test_text_only_turn_counts_as_final_message(example_tasks: Path, tmp_path: Path) -> None:
    task, ws = _setup(example_tasks, tmp_path)
    res = run_agent(
        task.public(),
        ScriptedProvider([turn(text="All done.")]),
        LocalExecutor(),
        ws,
        RunLimits(),
        tmp_path / "t.jsonl",
        _meta(),
    )
    assert res.status is RunStatus.FINISHED and res.final_message == "All done."


def test_toolbox_blocks_path_escape(tmp_path: Path) -> None:
    (tmp_path / "ws").mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("x")
    tb = ToolBox(tmp_path / "ws", LocalExecutor())
    assert not tb.execute(ToolCall(name="read_file", args={"path": "../secret.txt"})).ok
    assert not tb.execute(
        ToolCall(name="write_file", args={"path": "../evil.txt", "content": "x"})
    ).ok
    assert not (tmp_path / "evil.txt").exists()
    assert not tb.execute(ToolCall(name="nope")).ok


def test_quota_limiter_rpm_and_daily_reset() -> None:
    now = [1_700_000_000.0]
    slept: list[float] = []

    def sleep(s: float) -> None:
        slept.append(s)
        now[0] += s

    lim = QuotaLimiter(rpm=2, rpd=3, clock=lambda: now[0], sleep=sleep)
    lim.acquire()
    lim.acquire()
    lim.acquire()  # third request in the same minute must wait
    assert slept and slept[0] > 0
    with pytest.raises(DailyQuotaExhausted) as info:
        lim.acquire()
    assert info.value.reset_at > now[0]
    now[0] = next_reset(now[0]) + 1  # after Pacific midnight the day count resets
    lim.acquire()
    assert lim.used_today == 1
