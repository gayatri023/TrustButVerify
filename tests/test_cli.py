import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tbv.cli import app

runner = CliRunner()
COMMANDS = ["suite", "sandbox", "run", "verify", "experiment", "analyze", "demo", "doctor"]


def tbv(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run the real entry point (the only place exit-code mapping is applied)."""
    import os

    e = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, "-m", "tbv", *args], capture_output=True, text=True, env=e
    )


def test_help_lists_every_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in COMMANDS:
        assert name in result.output


def test_suite_help_lists_validate() -> None:
    assert "validate" in runner.invoke(app, ["suite", "--help"]).output


def test_live_commands_fail_cleanly_without_config(tmp_path: Path) -> None:
    m = tmp_path / "matrix.yaml"
    m.write_text("agents: [gemma-4-31b]\n")
    # model ids are still placeholders and there is no key: a clean usage error, never a crash
    r = tbv("run", "--agent", "gemma-4-31b", "--task", "bug-001", "--tasks-dir", str(tmp_path))
    assert r.returncode == 64
    r = tbv("experiment", "--matrix", str(m), "--dry-run", "--tasks-dir", str(tmp_path))
    assert r.returncode == 64


@pytest.mark.parametrize(
    "args",
    [
        ["run"],  # missing required options
        ["run", "--agent", "nope", "--task", "x"],  # unknown agent
        ["verify", "--transcript", "/does/not/exist", "--workspace", ".", "--task-dir", "."],
        ["analyze", "--db", "/does/not/exist.sqlite"],
        ["totally-unknown-command"],
    ],
)
def test_usage_errors_exit_64_not_2(args: list[str]) -> None:
    # Click's default usage-error code (2) is the same as WARN; CI must never confuse them.
    assert tbv(*args).returncode == 64


def test_experiment_real_run_requires_frozen_prereg(tmp_path: Path) -> None:
    from tbv.core.prereg import prereg_status

    if prereg_status() == "FROZEN":
        pytest.skip("PREREG is frozen in this checkout")
    m = tmp_path / "matrix.yaml"
    m.write_text("agents: [gemma-4-31b]\n")
    res = tbv("experiment", "--matrix", str(m))
    assert res.returncode == 64 and "FROZEN" in res.stderr


def test_dry_run_allowed_before_prereg_freeze(tmp_path: Path) -> None:
    m = tmp_path / "matrix.yaml"
    m.write_text("agents: [gemma-4-31b]\n")
    res = tbv("experiment", "--matrix", str(m), "--dry-run", "--tasks-dir", str(tmp_path))
    assert "PREREG" not in res.stderr  # the freeze guard does not apply to dry runs
    assert res.returncode in (64, 69)  # stops later, on missing model id / key / Docker


def test_doctor_runs_and_reports_docker_status() -> None:
    res = tbv("doctor")
    assert "Docker" in res.stdout
    assert res.returncode in (0, 69)


def test_unexpected_crash_exits_70_not_1(monkeypatch: pytest.MonkeyPatch) -> None:
    # An uncaught exception must not look like a BLOCK (exit 1).
    import tbv.cli as cli

    def explode(*_a: object, **_k: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "app", explode)
    with pytest.raises(SystemExit) as info:
        cli.main()
    assert info.value.code == 70


def test_doctor_statuses_have_symbol_and_word() -> None:
    res = tbv("doctor")
    # config/gate.yaml always validates, so an OK row must always appear with its symbol.
    assert "(+) OK" in res.stdout
    # Any failing row must also carry its symbol; a bare "FAIL" would mean the symbol was eaten.
    if "FAIL" in res.stdout:
        assert "(x) FAIL" in res.stdout


def test_demo_command_end_to_end(tmp_path: Path) -> None:
    res = tbv("demo", "--out-dir", str(tmp_path / "d"))
    assert res.returncode == 0, res.stderr
    assert (tmp_path / "d" / "report.html").exists()
    assert "SYNTHETIC" in res.stdout


def test_verify_command_exit_codes_match_verdicts(example_tasks: Path, tmp_path: Path) -> None:
    from tbv.agents.provider import ScriptedProvider
    from tbv.agents.runner import RunLimits
    from tbv.core.config import load_gate
    from tbv.experiment.cell import execute_attempt
    from tbv.sandbox.local_executor import LocalExecutor
    from tbv.scenarios import SCENARIOS
    from tbv.suite.task import load_tasks

    task = next(t for t in load_tasks(example_tasks) if t.spec.id == "bug-001")
    for name, code in (("honest_fix", 0), ("hedged_no_tests", 2), ("edit_tests", 1)):
        sc = next(s for s in SCENARIOS if s.name == name)
        o = execute_attempt(
            task,
            ScriptedProvider(sc.turns),
            LocalExecutor(),
            load_gate(),
            RunLimits(),
            tmp_path / name,
            agent="x",
        )
        res = tbv(
            "verify",
            "--transcript",
            str(o.transcript_path),
            "--workspace",
            str(o.workspace),
            "--task-dir",
            str(task.root),
            "--executor",
            "local-unsafe",
            "--format",
            "json",
        )
        assert res.returncode == code, (name, res.returncode, res.stderr)
