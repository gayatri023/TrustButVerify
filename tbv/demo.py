"""`tbv demo`: run the scripted adversarial agents through the real pipeline, offline, for free.

Everything here is SYNTHETIC. It exists so you can see the interface (terminal report, PR comment,
JSON, HTML page) before spending any API quota. Scripted agents run only trusted fixture code."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from rich.console import Console

from tbv.agents.provider import Provider, ScriptedProvider
from tbv.agents.runner import RunLimits
from tbv.agents.types import ProviderTurn
from tbv.analysis.report_html import write_html
from tbv.core.config import REPO_ROOT, load_gate
from tbv.core.models import Split
from tbv.experiment.cell import AttemptOutcome
from tbv.experiment.orchestrator import AgentSpec, run_matrix
from tbv.experiment.store import Store
from tbv.gate.report import render_terminal, to_json, to_markdown
from tbv.sandbox.local_executor import ENV_FLAG, LocalExecutor
from tbv.scenarios import SCENARIOS
from tbv.suite.factory import expand_dir
from tbv.suite.task import Task, load_task


def _factory(turns: list[ProviderTurn]) -> Callable[[], Provider]:
    return lambda: ScriptedProvider(turns)


def run_demo(out_dir: Path, console: Console) -> Path:
    os.environ.setdefault(ENV_FLAG, "1")  # trusted scripted fixtures only
    out_dir.mkdir(parents=True, exist_ok=True)
    gate = load_gate()
    db = out_dir / "results.sqlite"
    db.unlink(missing_ok=True)
    store = Store(db)
    reports = out_dir / "reports"
    reports.mkdir(exist_ok=True)
    summary: list[tuple[str, str, str, str]] = []

    def save(agent: str, task: str, attempt: int, out: AttemptOutcome) -> None:
        if out.report is None:
            return
        stem = reports / f"{agent}.attempt{attempt}"
        Path(f"{stem}.json").write_text(to_json(out.report), encoding="utf-8")
        Path(f"{stem}.md").write_text(to_markdown(out.report), encoding="utf-8")
        verdict = out.report.overall.value
        summary.append(
            (
                f"{agent} #{attempt}",
                verdict,
                "correct" if out.completed_correctly else "hidden tests FAIL",
                out.report.claims[0].reason[:60],
            )
        )
        if attempt == 1 and agent in ("honest_fix", "hedged_no_tests", "edit_tests"):
            render_terminal(out.report, console)

    with tempfile.TemporaryDirectory(prefix="tbv-demo-") as td:
        paths = expand_dir(REPO_ROOT / "suite" / "specs", Path(td) / "tasks")
        tasks: dict[str, Task] = {t.spec.id: t for t in map(load_task, paths)}
        cells = []
        for sc in SCENARIOS:
            turns = sc.turns + sc.retry_turns
            cells.append(
                (
                    AgentSpec(
                        sc.name,
                        _factory(turns),
                        RunLimits(),
                        model="scripted",
                    ),
                    tasks[sc.task_id],
                )
            )
        splits = {tid: Split.DEV for tid in tasks}
        run_matrix(
            store,
            cells,
            splits,
            LocalExecutor(),
            gate,
            Path(td) / "work",
            fixture=True,
            on_attempt=save,
        )
    store.close()
    console.print("\n[bold]Scenario summary (SYNTHETIC)[/]")
    for name, verdict, hidden, _ in summary:
        console.print(f"  {name:<28} gate {verdict:<6} hidden: {hidden}")
    return write_html(db, out_dir / "report.html")
