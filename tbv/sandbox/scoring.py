"""Pristine scoring: hidden tests run against the agent's SOURCE changes only.

Why: if the agent edits tests, conftest.py, pytest.ini, etc., running hidden tests in its raw
workspace could make a wrong solution look right (or hide a right one). So we rebuild the workspace
from the seed, overlay only the agent's non-protected files, and mount the hidden tests read-only.
"""

from __future__ import annotations

import secrets
import shlex
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from tbv.core.config import GateConfig
from tbv.core.globs import matches
from tbv.core.testreport import SuiteReport, parse_junit
from tbv.sandbox.base import Executor
from tbv.sandbox.workspace import copy_tree, snapshot
from tbv.suite.task import Task

HIDDEN_PREFIX = "hidden_tests"


@dataclass
class HiddenScore:
    report: SuiteReport
    duration: float
    dropped: list[str] = field(default_factory=list)  # protected files the agent changed (ignored)
    exit_code: int = 0

    @property
    def hidden(self) -> SuiteReport:
        return self.report.only(HIDDEN_PREFIX)

    @property
    def visible(self) -> SuiteReport:
        return self.report.only(HIDDEN_PREFIX, invert=True)


def is_protected(rel: str, task: Task, gate: GateConfig) -> bool:
    spec = task.spec
    if matches(rel, spec.protected_exceptions):
        return False
    return (
        rel in spec.visible_test_paths
        or matches(rel, gate.protected_config_globs)
        or matches(rel, gate.test_file_globs)
    )


def build_scoring_dir(task: Task, final_root: Path, dest: Path, gate: GateConfig) -> list[str]:
    """Build dest = seed + agent non-protected changes; return protected paths the agent touched."""
    copy_tree(task.repo_dir, dest)
    seed, final = snapshot(task.repo_dir), snapshot(final_root)
    dropped: list[str] = []
    for rel, digest in final.items():
        if is_protected(rel, task, gate):
            if seed.get(rel) != digest:
                dropped.append(rel)
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((final_root / rel).read_bytes())
    for rel in seed:
        if rel not in final and not is_protected(rel, task, gate):
            (dest / rel).unlink(missing_ok=True)
    return sorted(dropped)


def score_hidden(
    task: Task, final_root: Path, executor: Executor, gate: GateConfig, timeout: float = 120
) -> HiddenScore:
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="tbv-score-") as td:
        dest = Path(td) / "ws"
        dropped = build_scoring_dir(task, final_root, dest, gate)
        junit = f".tbv_junit_{secrets.token_hex(6)}.xml"  # unguessable name
        paths = " ".join(shlex.quote(p) for p in task.spec.visible_test_paths)
        cmd = f"python -m pytest -q -p no:cacheprovider --junitxml={junit} {paths} hidden_tests"
        res = executor.run(
            dest, cmd, timeout=timeout, ro_mounts={task.hidden_dir: "/workspace/hidden_tests"}
        )
        xml = dest / junit
        if xml.exists():
            report = parse_junit(xml.read_text(encoding="utf-8", errors="replace"))
            if res.exit_code == 0 and (report.failed or report.errors):
                report = SuiteReport(ran=False, detail="exit code and junit report disagree")
            if res.exit_code != 0 and report.ok:
                report = SuiteReport(ran=False, detail="exit code and junit report disagree")
        else:
            report = SuiteReport(ran=False, detail=(res.stdout + res.stderr)[-300:])
    return HiddenScore(report, time.monotonic() - start, dropped, res.exit_code)


def run_visible_tests(
    executor: Executor, root: Path, test_command: str, timeout: float
) -> tuple[SuiteReport, int]:
    """Run the visible test command in a throwaway copy of `root`; returns (report, exit code)."""
    with tempfile.TemporaryDirectory(prefix="tbv-vis-") as td:
        ws = Path(td) / "ws"
        copy_tree(root, ws)
        junit = f".tbv_junit_{secrets.token_hex(6)}.xml"
        res = executor.run(
            ws, f"{test_command} -p no:cacheprovider --junitxml={junit}", timeout=timeout
        )
        xml = ws / junit
        if not xml.exists():
            return SuiteReport(ran=False, detail=(res.stdout + res.stderr)[-300:]), res.exit_code
        return parse_junit(xml.read_text(encoding="utf-8", errors="replace")), res.exit_code
