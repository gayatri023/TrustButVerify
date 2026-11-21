"""End to end through REAL Docker: task validation and every adversarial scenario must give the same
verdicts as under the test-only executor. Needs the sandbox image (`tbv sandbox build`)."""

from pathlib import Path

import pytest
from scenario_expectations import EXPECTED

from tbv.agents.provider import ScriptedProvider
from tbv.agents.runner import RunLimits
from tbv.core.config import load_gate
from tbv.experiment.cell import execute_attempt
from tbv.sandbox.docker_executor import DEFAULT_IMAGE, DockerExecutor
from tbv.sandbox.preflight import check_docker
from tbv.scenarios import SCENARIOS, Scenario
from tbv.suite.task import load_tasks
from tbv.suite.validator import validate_task

GATE = load_gate()
pytestmark = pytest.mark.docker


@pytest.fixture(scope="module")
def dx() -> DockerExecutor:
    res = check_docker()
    if not res.ok:
        pytest.skip(res.detail)
    ex = DockerExecutor()
    try:
        ex.client.images.get(DEFAULT_IMAGE)
    except Exception:  # noqa: BLE001
        pytest.skip("sandbox image missing: run `uv run tbv sandbox build`")
    return ex


def test_example_tasks_validate_in_docker(dx: DockerExecutor, example_tasks: Path) -> None:
    results = [validate_task(t, dx, GATE) for t in load_tasks(example_tasks)]
    bad = [(r.task_id, r.reasons) for r in results if not r.valid]
    assert not bad, bad


@pytest.mark.parametrize("sc", SCENARIOS, ids=lambda s: s.name)
def test_scenarios_give_the_same_verdicts_in_docker(
    dx: DockerExecutor, example_tasks: Path, tmp_path: Path, sc: Scenario
) -> None:
    task = next(t for t in load_tasks(example_tasks) if t.spec.id == sc.task_id)
    out = execute_attempt(
        task,
        ScriptedProvider(sc.turns),
        dx,
        GATE,
        RunLimits(),
        tmp_path / sc.name,
        agent="scripted",
    )
    verdict, hidden_ok = EXPECTED[sc.name]
    assert out.report is not None
    assert out.report.overall is verdict, (sc.name, out.report.overall, out.report.tamper)
    assert out.completed_correctly is hidden_ok, (sc.name, out.score.report)
