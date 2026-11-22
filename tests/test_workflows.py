from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _load(name: str) -> dict:  # type: ignore[type-arg]
    return yaml.safe_load((WF / name).read_text(encoding="utf-8"))


def test_workflows_use_minimal_permissions_and_safe_triggers() -> None:
    for f in sorted(WF.glob("*.yml")):
        data = _load(f.name)
        assert data["permissions"] == {"contents": "read"}, f.name
        triggers = data.get("on") or data.get(True)  # PyYAML parses a bare `on` key as True
        assert "pull_request_target" not in triggers, f.name


def test_ci_runs_lint_tests_and_the_docker_sandbox_tests() -> None:
    jobs = _load("ci.yml")["jobs"]
    assert set(jobs) == {"checks", "sandbox"}
    steps = " ".join(str(s.get("run", "")) for s in jobs["sandbox"]["steps"])
    assert "make docker-tests" in steps


def test_models_workflow_is_manual_and_only_reads_the_one_secret() -> None:
    raw = (WF / "models.yml").read_text(encoding="utf-8")
    data = _load("models.yml")
    assert list((data.get("on") or data.get(True)).keys()) == ["workflow_dispatch"]
    assert raw.count("secrets.") == 1 and "secrets.GEMINI_API_KEY" in raw
    assert "echo" not in raw  # never print the key


def test_experiment_and_smoke_are_manual_and_only_read_the_one_secret() -> None:
    for name in ("experiment.yml", "smoke.yml"):
        raw = (WF / name).read_text(encoding="utf-8")
        trig = _load(name).get("on") or _load(name).get(True)
        assert list(trig.keys()) == ["workflow_dispatch"], name
        assert raw.count("secrets.") == 1 and "secrets.GEMINI_API_KEY" in raw, name
    exp = (WF / "experiment.yml").read_text(encoding="utf-8")
    assert "--final" in exp and "actions/cache/save" in exp and "if: always()" in exp
