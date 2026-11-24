from pathlib import Path

import pytest

from tbv.agents.provider import ScriptedProvider
from tbv.agents.runner import RunLimits
from tbv.core.config import Settings, load_agents, load_gate
from tbv.core.models import Split
from tbv.experiment.orchestrator import AgentSpec
from tbv.experiment.store import Store
from tbv.live import (
    Matrix,
    dry_run,
    make_spec,
    require_ready,
    resolve_model_id,
    run_experiment,
    select_tasks,
)
from tbv.sandbox.local_executor import LocalExecutor
from tbv.scenarios import SCENARIOS
from tbv.suite.task import load_tasks

GATE = load_gate()


def test_unconfigured_agents_are_refused_with_a_helpful_message() -> None:
    g = next(a for a in load_agents().agents if a.name == "gemma-4-31b")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        require_ready(g, Settings())
    with pytest.raises(RuntimeError, match="model id"):
        require_ready(g.model_copy(update={"model": "SET_ME"}), Settings(gemini_api_key="k"))


def test_model_ids_are_resolved_from_a_pattern() -> None:
    ids = [
        "gemma-4-31b-it",
        "gemma-4-26b-it",
        "gemini-3.1-flash-lite-preview",
        "gemini-3.1-flash-lite",
        "gemini-3.1-flash-lite-image",
        "gemini-3.5-flash-lite",
    ]
    assert resolve_model_id("gemma-4-31b", ids) == "gemma-4-31b-it"
    assert resolve_model_id("gemini-3.1-flash-lite", ids) == "gemini-3.1-flash-lite"
    assert (
        resolve_model_id("gemini-3.1-flash-lite", [i for i in ids if i != "gemini-3.1-flash-lite"])
        == "gemini-3.1-flash-lite-preview"
    )
    with pytest.raises(RuntimeError, match="similar ids"):
        resolve_model_id("gemma-9-1b", ids)


def test_make_spec_resolves_auto_models(tmp_path: Path) -> None:
    cfg = next(a for a in load_agents().agents if a.name == "gemma-4-31b")
    spec = make_spec(
        cfg,
        Settings(gemini_api_key="k"),
        Store(":memory:"),
        list_models=lambda key: ["gemma-4-31b-it", "other"],
    )
    assert spec.model == "gemma-4-31b-it" and spec.config_hash


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


def test_model_listing_keeps_the_client_alive_while_iterating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: a temporary genai.Client was garbage collected mid-listing ("client has been closed").

    The fake mirrors the real SDK: the lazy listing does NOT reference the Client object, so the
    client is closed as soon as nothing else holds it."""
    import types as pytypes

    class FakeClient:
        def __init__(self, api_key: str) -> None:
            state = {"closed": False}
            self._state = state

            def list_models():  # type: ignore[no-untyped-def]
                def gen():  # type: ignore[no-untyped-def]
                    if state["closed"]:
                        raise RuntimeError("Cannot send a request, as the client has been closed.")
                    for name in ("models/gemma-4-31b-it", "models/embed-x"):
                        yield pytypes.SimpleNamespace(
                            name=name,
                            supported_actions=["generateContent"] if "gemma" in name else ["embed"],
                        )

                return gen()

            self.models = pytypes.SimpleNamespace(list=list_models)

        def __del__(self) -> None:
            self._state["closed"] = True

        def close(self) -> None:
            pass

    import google.genai as genai_mod

    from tbv.live import fetch_model_ids

    monkeypatch.setattr(genai_mod, "Client", FakeClient)
    assert fetch_model_ids("k") == ["gemma-4-31b-it"]
