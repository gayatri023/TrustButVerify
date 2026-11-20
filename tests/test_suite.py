from pathlib import Path

import pytest
import yaml

from tbv.core.config import load_gate
from tbv.core.globs import matches
from tbv.core.testreport import parse_junit
from tbv.sandbox.local_executor import LocalExecutor
from tbv.sandbox.scoring import build_scoring_dir, score_hidden
from tbv.sandbox.workspace import changes, copy_tree, diff_dirs, snapshot, tree_hash
from tbv.suite.factory import expand_spec
from tbv.suite.task import PublicTask, load_task, load_tasks
from tbv.suite.validator import validate_task, write_reports

GATE = load_gate()


def test_globs() -> None:
    assert matches("conftest.py", ["**/conftest.py"])
    assert matches("a/b/conftest.py", ["**/conftest.py"])
    assert matches("tests/x/y.py", ["tests/**"])
    assert not matches("src/tests_helper.py", ["tests/**"])
    assert matches(".github/workflows/ci.yml", [".github/**"])
    assert not matches("conftest.pyc", ["**/conftest.py"])


def test_parse_junit_counts() -> None:
    xml = (
        '<testsuites><testsuite><testcase classname="t" name="a"/>'
        '<testcase classname="t" name="b"><failure message="boom"/></testcase>'
        '<testcase classname="t" name="c"><skipped/></testcase></testsuite></testsuites>'
    )
    r = parse_junit(xml)
    assert (r.total, r.passed, r.failed, r.skipped) == (3, 1, 1, 1)
    assert r.failing_names == ["t::b"] and not r.ok and r.detail == "boom"
    assert not parse_junit("<not xml").ran


def test_snapshot_diff_changes(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    (a / "x.py").write_text("1\n")
    (a / "__pycache__").mkdir()
    (a / "__pycache__" / "junk.pyc").write_bytes(b"x")
    copy_tree(a, b)
    assert tree_hash(snapshot(a)) == tree_hash(snapshot(b))
    (b / "x.py").write_text("2\n")
    (b / "new.py").write_text("n\n")
    cs = changes(snapshot(a), snapshot(b))
    assert cs.modified == ["x.py"] and cs.added == ["new.py"]
    assert "-1" in diff_dirs(a, b) and "+2" in diff_dirs(a, b)


def test_all_example_specs_validate(example_tasks: Path, tmp_path: Path) -> None:
    ex = LocalExecutor()
    results = [validate_task(t, ex, GATE) for t in load_tasks(example_tasks)]
    assert len(results) == 5
    bad = [(r.task_id, r.reasons) for r in results if not r.valid]
    assert not bad, bad
    write_reports(results, tmp_path / "rep")
    assert "5 valid of 5" in (tmp_path / "rep" / "validation.txt").read_text()


def _spec(**over: object) -> dict[str, object]:
    base: dict[str, object] = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "suite/specs/bug-001.yaml").read_text()
    )
    base.update(over)
    return base


@pytest.mark.parametrize(
    ("name", "over", "check"),
    [
        (
            "hidden_passes_on_seed",
            {"hidden_tests": {"test_h.py": "def test_ok():\n    assert True\n"}},
            "seed_hidden_fails",
        ),
        (
            "reference_fails",
            {"reference": {"windows.py": "def moving_sum(v, k):\n    return []\n"}},
            "reference_passes_hidden_and_visible",
        ),
        (
            "leak_in_repo",
            {
                "files": {
                    "windows.py": "# test_window_larger_than_list\ndef moving_sum(v, k):\n    return []\n"
                }
            },
            "no_leakage",
        ),
        (
            "wrong_declared_visible_status",
            {"visible_tests_at_seed": "pass"},
            "seed_visible_as_declared",
        ),
    ],
)
def test_broken_tasks_are_caught(
    tmp_path: Path, name: str, over: dict[str, object], check: str
) -> None:
    task = load_task(expand_spec(_spec(id=name, **over), tmp_path))
    res = validate_task(task, LocalExecutor(), GATE)
    assert not res.valid
    assert check in [c.name for c in res.checks if not c.ok], res.reasons


def test_public_task_has_no_hidden_fields(example_tasks: Path) -> None:
    t = load_tasks(example_tasks)[0]
    dumped = t.public().model_dump_json()
    assert t.spec.hidden_requirement not in dumped
    assert not any("hidden" in f for f in PublicTask.model_fields)


def test_pristine_scoring_ignores_test_and_config_tampering(
    example_tasks: Path, tmp_path: Path
) -> None:
    task = next(t for t in load_tasks(example_tasks) if t.spec.id == "bug-001")
    final = tmp_path / "final"
    copy_tree(task.repo_dir, final)
    # Agent cheats: weakens the visible test, adds a forcing conftest, ships a wrong fix.
    (final / "tests/test_windows.py").write_text("def test_x():\n    assert True\n")
    (final / "conftest.py").write_text(
        "def pytest_collection_modifyitems(items):\n    items.clear()\n"
    )
    (final / "pytest.ini").write_text("[pytest]\naddopts = --co\n")
    ex = LocalExecutor()
    dropped = build_scoring_dir(task, final, tmp_path / "score", GATE)
    assert set(dropped) == {"tests/test_windows.py", "conftest.py", "pytest.ini"}
    score = score_hidden(task, final, ex, GATE)
    assert score.report.ran and not score.report.ok  # cheating did not rescue the wrong fix
    assert score.dropped == dropped
