"""TBV command line."""

from __future__ import annotations

import datetime as dt
import sys
from collections import Counter
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from tbv import __version__
from tbv.core.config import REPO_ROOT, Settings, load_agents, load_gate, load_pricing
from tbv.core.models import ExitCode, Split
from tbv.core.prereg import prereg_status
from tbv.experiment.orchestrator import Summary
from tbv.sandbox.base import Executor
from tbv.sandbox.preflight import check_docker

app = typer.Typer(
    name="tbv",
    help="TrustButVerify: check a coding agent's 'done' claim against deterministic evidence.",
    no_args_is_help=True,
    add_completion=False,
)
suite_app = typer.Typer(help="Task suite commands.", no_args_is_help=True)
sandbox_app = typer.Typer(help="Sandbox image commands.", no_args_is_help=True)
app.add_typer(suite_app, name="suite")
app.add_typer(sandbox_app, name="sandbox")

out = Console()
err = Console(stderr=True)

DEFAULT_TASKS_DIR = REPO_ROOT / "suite" / "tasks"
DEFAULT_SPECS_DIR = REPO_ROOT / "suite" / "specs"
DEFAULT_DB = REPO_ROOT / "data" / "results.sqlite"
ExecutorOpt = Annotated[
    str,
    typer.Option("--executor", help="docker (default) or local-unsafe (trusted fixtures only)."),
]


def _not_implemented(prompt: str) -> None:
    err.print(f"[yellow]not implemented yet[/] (built in {prompt}). Arguments parsed fine.")
    raise typer.Exit(ExitCode.NOT_IMPLEMENTED)


def _executor(kind: str) -> Executor:
    if kind == "docker":
        res = check_docker()
        if not res.ok:
            err.print(f"[red]{res.detail}[/]")
            raise typer.Exit(ExitCode.ENV_UNAVAILABLE)
        from tbv.sandbox.docker_executor import DockerExecutor

        return DockerExecutor()
    if kind == "local-unsafe":
        from tbv.sandbox.local_executor import LocalExecutor

        try:
            return LocalExecutor()
        except RuntimeError as exc:
            raise typer.BadParameter(str(exc), param_hint="--executor") from exc
    raise typer.BadParameter("must be docker or local-unsafe", param_hint="--executor")


def _version_cb(value: bool) -> None:
    if value:
        out.print(f"tbv {__version__}")
        raise typer.Exit(0)


@app.callback()
def _root(
    version: Annotated[
        bool, typer.Option("--version", callback=_version_cb, is_eager=True, help="Show version.")
    ] = False,
) -> None:
    """Root options."""


# ---------------------------------------------------------------- suite
@suite_app.command("expand")
def suite_expand(
    specs_dir: Annotated[Path, typer.Option(exists=True, file_okay=False)] = DEFAULT_SPECS_DIR,
    tasks_dir: Annotated[Path, typer.Option()] = DEFAULT_TASKS_DIR,
) -> None:
    """Expand compact YAML specs into full task directories."""
    from tbv.suite.factory import expand_dir

    made = expand_dir(specs_dir, tasks_dir)
    out.print(f"expanded {len(made)} tasks into {tasks_dir}")


@suite_app.command("validate")
def suite_validate(
    tasks_dir: Annotated[Path, typer.Option(exists=True, file_okay=False)] = DEFAULT_TASKS_DIR,
    report_dir: Annotated[Path, typer.Option()] = REPO_ROOT / "data" / "validation",
    executor: ExecutorOpt = "docker",
) -> None:
    """Validate every task in the sandbox (hidden tests fail on seed, pass on reference, ...)."""
    from tbv.suite.task import load_tasks
    from tbv.suite.validator import validate_task, write_reports

    ex, gate = _executor(executor), load_gate()
    results = []
    for t in load_tasks(tasks_dir):
        r = validate_task(t, ex, gate)
        results.append(r)
        out.print(
            f"{'(+) VALID  ' if r.valid else '(x) INVALID'} {r.task_id} {'; '.join(r.reasons)}"
        )
    write_reports(results, report_dir)
    out.print(f"{sum(r.valid for r in results)} valid of {len(results)}; reports in {report_dir}")
    if not all(r.valid for r in results):
        raise typer.Exit(ExitCode.VALIDATION_FAILED)


@suite_app.command("split")
def suite_split(
    tasks_dir: Annotated[Path, typer.Option(exists=True, file_okay=False)] = DEFAULT_TASKS_DIR,
    n_test: Annotated[int, typer.Option(min=1, help="Size of the TEST split.")] = 20,
    splits_file: Annotated[Path, typer.Option()] = REPO_ROOT / "suite" / "splits.yaml",
) -> None:
    """Create the stratified DEV/TEST split. Refuses to overwrite a frozen split."""
    from tbv.suite.splits import make_splits, write_splits
    from tbv.suite.task import load_tasks

    try:
        write_splits(splits_file, make_splits(load_tasks(tasks_dir), n_test))
    except RuntimeError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(ExitCode.USAGE) from exc
    out.print(f"wrote {splits_file}")


@suite_app.command("stats")
def suite_stats(
    tasks_dir: Annotated[Path, typer.Option(exists=True, file_okay=False)] = DEFAULT_TASKS_DIR,
    splits_file: Annotated[Path, typer.Option()] = REPO_ROOT / "suite" / "splits.yaml",
) -> None:
    """Counts per type, difficulty and split (generated, never typed by hand)."""
    from tbv.suite.splits import load_splits
    from tbv.suite.task import load_tasks

    tasks = load_tasks(tasks_dir)
    splits = load_splits(splits_file) if splits_file.exists() else {}
    for title, key in (
        ("type", lambda t: t.spec.type.value),
        ("difficulty", lambda t: t.spec.difficulty.value),
        ("split", lambda t: splits.get(t.spec.id, Split.DEV).value),
    ):
        tbl = Table(title=f"By {title} (n={len(tasks)})")
        tbl.add_column(title)
        tbl.add_column("count")
        for k, v in sorted(Counter(key(t) for t in tasks).items()):
            tbl.add_row(k, str(v))
        out.print(tbl)


# -------------------------------------------------------------- sandbox
@sandbox_app.command("build")
def sandbox_build() -> None:
    """Build the sandbox image (needs Docker). Then pin the base digest (see infra/Dockerfile)."""
    res = check_docker()
    if not res.ok:
        err.print(f"[red]{res.detail}[/]")
        raise typer.Exit(ExitCode.ENV_UNAVAILABLE)
    import docker

    from tbv.sandbox.docker_executor import DEFAULT_IMAGE

    image, _ = docker.from_env().images.build(
        path=str(REPO_ROOT / "infra"), dockerfile="Dockerfile.sandbox", tag=DEFAULT_IMAGE
    )
    out.print(f"built {DEFAULT_IMAGE} ({image.short_id})")


# ------------------------------------------------------------ run / gate
@app.command("run")
def run(
    agent: Annotated[str, typer.Option(help="Agent name from config/agents.yaml.")],
    task: Annotated[str, typer.Option(help="Task id (directory name under suite/tasks).")],
    repeat: Annotated[int, typer.Option(min=0, help="Repeat index.")] = 0,
    tasks_dir: Annotated[Path, typer.Option(exists=True, file_okay=False)] = DEFAULT_TASKS_DIR,
    db: Annotated[Path, typer.Option()] = DEFAULT_DB,
    executor: ExecutorOpt = "docker",
) -> None:
    """Run one agent on one task (live model) and store the result. Needs Docker and a key."""
    from tbv.experiment.store import Store
    from tbv.live import Matrix, make_spec, run_experiment
    from tbv.suite.task import load_tasks

    cfgs = {a.name: a for a in load_agents().agents}
    if agent not in cfgs:
        raise typer.BadParameter(
            f"unknown agent {agent!r}; known: {', '.join(cfgs)}", param_hint="--agent"
        )
    tasks = [t for t in load_tasks(tasks_dir) if t.spec.id == task]
    if not tasks:
        raise typer.BadParameter(f"no task {task!r} in {tasks_dir}", param_hint="--task")
    store = Store(db)
    try:
        spec = make_spec(cfgs[agent], Settings.from_env(), store)
    except RuntimeError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(ExitCode.USAGE) from exc
    summary = run_experiment(
        store,
        [spec],
        tasks,
        {},
        Matrix(agents=[agent], repeats=repeat + 1),
        _executor(executor),
        load_gate(),
        db.parent / "work",
    )
    _print_summary(summary)
    for r in store.con.execute(
        "SELECT attempt, status, gate_overall, completed_correctly, steps "
        "FROM runs WHERE agent=? AND task=? ORDER BY attempt",
        (agent, task),
    ):
        out.print(
            f"  attempt {r['attempt']}: status={r['status']} gate={r['gate_overall']} "
            f"hidden+visible tests pass={bool(r['completed_correctly'])} steps={r['steps']}"
        )


def _print_summary(summary: Summary) -> None:
    out.print(f"ran {summary.ran} cells, skipped {summary.skipped} already done")
    if summary.paused_until:
        utc = dt.datetime.fromtimestamp(summary.paused_until, dt.UTC)
        ist = utc.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30)))
        out.print(
            f"[yellow]Daily quota used up. Re-run the same command after {utc:%H:%M} UTC "
            f"({ist:%H:%M} IST); finished cells are skipped automatically.[/]"
        )


@app.command("verify")
def verify(
    transcript: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, readable=True, help="Transcript JSONL.")
    ],
    workspace: Annotated[
        Path, typer.Option(exists=True, file_okay=False, readable=True, help="Final workspace.")
    ],
    task_dir: Annotated[
        Path,
        typer.Option(
            exists=True, file_okay=False, help="Task directory (seed repo + public task)."
        ),
    ],
    output_format: Annotated[
        str, typer.Option("--format", help="terminal | json | markdown.")
    ] = "terminal",
    executor: ExecutorOpt = "docker",
) -> None:
    """Run the gate on a saved transcript and workspace. Exit 0 PASS, 2 WARN, 1 BLOCK."""
    if output_format not in {"terminal", "json", "markdown"}:
        raise typer.BadParameter("must be terminal, json or markdown", param_hint="--format")
    from tbv.agents.types import read_transcript
    from tbv.core.models import RunStatus
    from tbv.gate.pipeline import run_gate
    from tbv.gate.report import render_terminal, to_json, to_markdown
    from tbv.gate.verdict import exit_code_for
    from tbv.suite.task import load_task

    tr = read_transcript(transcript)
    if tr.final is None or tr.final.status is not RunStatus.FINISHED:
        raise typer.BadParameter(
            "the run did not finish, so there is no claim to verify", param_hint="--transcript"
        )
    task = load_task(task_dir)
    report = run_gate(
        task.public(),
        tr,
        task.repo_dir,
        workspace,
        _executor(executor),
        load_gate(),
        tr.final.message,
    )
    if output_format == "json":
        print(to_json(report))
    elif output_format == "markdown":
        print(to_markdown(report))
    else:
        render_terminal(report, out)
    raise typer.Exit(exit_code_for(report))


@app.command("experiment")
def experiment(
    matrix: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, help="Matrix YAML (agents, split, repeats)."),
    ],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Run 5 tasks, print projected requests and time.")
    ] = False,
    final: Annotated[
        bool, typer.Option("--final", help="Evaluate the TEST split once with the frozen config.")
    ] = False,
    tasks_dir: Annotated[Path, typer.Option(exists=True, file_okay=False)] = DEFAULT_TASKS_DIR,
    splits_file: Annotated[Path, typer.Option()] = REPO_ROOT / "suite" / "splits.yaml",
    db: Annotated[Path, typer.Option()] = DEFAULT_DB,
    executor: ExecutorOpt = "docker",
) -> None:
    """Run the experiment matrix (resumable). Real runs need docs/PREREG.md to be FROZEN."""
    if not dry_run and prereg_status() != "FROZEN":
        err.print("[red]docs/PREREG.md is not FROZEN; commit it before any real experiment.[/]")
        raise typer.Exit(ExitCode.USAGE)
    if final and dry_run:
        raise typer.BadParameter("--final cannot be combined with --dry-run", param_hint="--final")
    from tbv.experiment.store import Store, TestSplitGuard
    from tbv.live import dry_run as live_dry_run
    from tbv.live import load_matrix, make_spec, run_experiment, select_tasks
    from tbv.suite.splits import load_splits
    from tbv.suite.task import load_tasks

    mx = load_matrix(matrix)
    cfgs = {a.name: a for a in load_agents().agents}
    unknown = [a for a in mx.agents if a not in cfgs]
    if unknown:
        raise typer.BadParameter(f"unknown agents: {unknown}", param_hint="--matrix")
    tasks = load_tasks(tasks_dir)
    splits = load_splits(splits_file) if splits_file.exists() else {}
    store = Store(":memory:" if dry_run else db)
    try:
        specs = [make_spec(cfgs[a], Settings.from_env(), store) for a in mx.agents]
    except RuntimeError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(ExitCode.USAGE) from exc
    ex, gate = _executor(executor), load_gate()
    if dry_run:
        n = len(select_tasks(mx, tasks, splits)) * len(specs) * mx.repeats
        cfg = cfgs[mx.agents[0]]
        p = live_dry_run(specs, tasks, splits, mx, ex, gate, n, cfg.rpd or 1, cfg.tpm)
        out.print(
            f"Projection for {n} runs: about {p.requests:.0f} requests "
            f"({p.days_at_rpd:.0f} day(s) at {cfg.rpd}/day)"
            + (
                f", about {p.minutes_at_tpm / 60:.1f} h of token budget at {cfg.tpm} TPM"
                if p.minutes_at_tpm
                else ""
            )
            + f"; {100 * p.retry_fraction:.0f}% of sampled runs retried."
        )
        return
    try:
        summary = run_experiment(
            store,
            specs,
            tasks,
            splits,
            mx,
            ex,
            gate,
            db.parent / "work",
            final=final,
            on_progress=lambda i, n, m: out.print(f"  [{i}/{n}] {m}"),
        )
    except TestSplitGuard as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(ExitCode.USAGE) from exc
    _print_summary(summary)


@app.command("models")
def models(
    contains: Annotated[str, typer.Option(help="Only show ids containing this text.")] = "",
) -> None:
    """List model ids your API key can call (copy exact ids into config/agents.yaml)."""
    key = Settings.from_env().gemini_api_key
    if not key:
        err.print("[red]GEMINI_API_KEY is not set (Codespaces secret or .env).[/]")
        raise typer.Exit(ExitCode.USAGE)
    from google import genai

    for m in genai.Client(api_key=key).models.list():
        name = (m.name or "").removeprefix("models/")
        if "generateContent" in (m.supported_actions or []) and contains.lower() in name.lower():
            out.print(name)


@app.command("analyze")
def analyze(
    db: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, help="results.sqlite.")
    ] = DEFAULT_DB,
    out_dir: Annotated[Path, typer.Option(help="Output directory.")] = REPO_ROOT / "results",
) -> None:
    """Rebuild the results page (HTML) from results.sqlite. Fixture data is stamped SYNTHETIC."""
    from tbv.analysis.report_html import write_html

    try:
        path = write_html(db, out_dir / "report.html")
    except ValueError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(ExitCode.USAGE) from exc
    out.print(f"wrote {path}")


@app.command("demo")
def demo(
    out_dir: Annotated[Path, typer.Option(help="Where to write the demo outputs.")] = Path(
        "demo_out"
    ),
) -> None:
    """Offline demo: scripted agents through the real gate. Free, no Docker, no API key."""
    from tbv.demo import run_demo

    path = run_demo(out_dir, out)
    out.print(f"\nOpen this page in a browser: {path.resolve()}")


@app.command("doctor")
def doctor() -> None:
    """Check that this machine is ready: Docker, configs, keys, spend cap, pre-registration."""
    rows: list[tuple[str, str, str]] = []
    docker_res = check_docker()
    rows.append(("Docker", "OK" if docker_res.ok else "FAIL", docker_res.detail[:90]))
    try:
        agents = load_agents().agents
        unset = [a.name for a in agents if not a.is_configured]
        rows.append(
            (
                "Agent models",
                "TODO" if unset else "OK",
                f"model string not set for: {', '.join(unset)}" if unset else "all set",
            )
        )
    except Exception as exc:  # noqa: BLE001
        rows.append(("config/agents.yaml", "FAIL", str(exc)))
    for name, loader in (("config/gate.yaml", load_gate), ("config/pricing.yaml", load_pricing)):
        try:
            loader()
            rows.append((name, "OK", "loads and validates"))
        except Exception as exc:  # noqa: BLE001
            rows.append((name, "FAIL", str(exc)))
    try:
        s = Settings.from_env()
        rows.append(
            (
                "SPEND_CAP_USD",
                "OK" if s.spend_cap_usd else "TODO",
                "set" if s.spend_cap_usd else "not set (free tier: optional)",
            )
        )
        rows.append(
            (
                "GEMINI_API_KEY",
                "OK" if s.gemini_api_key else "TODO",
                "set" if s.gemini_api_key else "not set",
            )
        )
    except ValueError as exc:
        rows.append(("SPEND_CAP_USD", "FAIL", str(exc)))
    status = prereg_status()
    rows.append(("docs/PREREG.md", "OK" if status == "FROZEN" else "TODO", f"Status: {status}"))
    # Symbol AND word, never colour alone. Parentheses, because Rich reads [x] as markup.
    symbols = {"OK": "[green](+) OK[/]", "TODO": "[yellow](!) TODO[/]", "FAIL": "[red](x) FAIL[/]"}
    table = Table(title="tbv doctor")
    for col in ("Check", "Status", "Detail"):
        table.add_column(col)
    for check, st, detail in rows:
        table.add_row(check, symbols[st], detail)
    out.print(table)
    if any(st == "FAIL" for _, st, _ in rows):
        raise typer.Exit(ExitCode.ENV_UNAVAILABLE)


def _cli_error_show(exc: Exception) -> bool:
    """True if `exc` is a Typer/Click user-facing CLI error. Detected by behaviour, not class,
    because Typer 0.29+ ships a private copy of click."""
    show = getattr(exc, "show", None)
    if callable(show) and isinstance(getattr(exc, "exit_code", None), int):
        show()
        return True
    return False


def main() -> None:
    """Entry point. Maps every failure to a code that cannot be mistaken for a gate verdict."""
    try:
        result = app(standalone_mode=False)
    except typer.Abort:
        err.print("Aborted.")
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001
        if _cli_error_show(exc):
            sys.exit(int(ExitCode.USAGE))
        err.print(f"[bold red]internal error:[/] {type(exc).__name__}: {exc}")
        sys.exit(int(ExitCode.INTERNAL))
    sys.exit(result if isinstance(result, int) else 0)
