"""Automatic task validation (PRD section 5). A task that fails any check is excluded."""

from __future__ import annotations

import csv
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from tbv.core.config import GateConfig
from tbv.core.testreport import SuiteReport, parse_junit
from tbv.sandbox.base import Executor
from tbv.sandbox.scoring import score_hidden
from tbv.sandbox.workspace import copy_tree, read_text, snapshot
from tbv.suite.task import Task


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class TaskValidation:
    task_id: str
    checks: list[Check] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def reasons(self) -> list[str]:
        return [f"{c.name}: {c.detail}" for c in self.checks if not c.ok]


def _visible_at_seed(task: Task, executor: Executor) -> SuiteReport:
    with tempfile.TemporaryDirectory(prefix="tbv-val-") as td:
        ws = Path(td) / "ws"
        copy_tree(task.repo_dir, ws)
        cmd = f"{task.spec.test_command} -p no:cacheprovider --junitxml=.tbv_val.xml"
        executor.run(ws, cmd, timeout=task.spec.max_seconds)
        xml = ws / ".tbv_val.xml"
        if not xml.exists():
            return SuiteReport(ran=False, detail="no junit output")
        return parse_junit(xml.read_text(encoding="utf-8", errors="replace"))


def _leak_check(task: Task) -> Check:
    repo_files = snapshot(task.repo_dir)
    hidden_files = snapshot(task.hidden_dir)
    problems: list[str] = []
    repo_hashes = set(repo_files.values())
    for rel, digest in hidden_files.items():
        if digest in repo_hashes:
            problems.append(f"hidden file {rel} duplicated under repo/")
    names = {
        n
        for rel in hidden_files
        for n in re.findall(r"def (test_\w+)", read_text(task.hidden_dir / rel))
    }
    visible = set(task.spec.visible_test_paths)
    for rel in repo_files:
        if rel in visible or not rel.endswith((".py", ".md", ".txt", ".yaml", ".cfg")):
            continue
        text = read_text(task.repo_dir / rel)
        hit = sorted(n for n in names if n in text)
        if hit:
            problems.append(f"{rel} mentions hidden test names {hit[:3]}")
    return Check("no_leakage", not problems, "; ".join(problems))


def validate_task(task: Task, executor: Executor, gate: GateConfig) -> TaskValidation:
    v = TaskValidation(task.spec.id)
    s = task.spec
    missing = [
        n
        for n, p in (
            ("repo", task.repo_dir),
            ("hidden_tests", task.hidden_dir),
            ("reference", task.reference_dir),
        )
        if not p.is_dir() or not any(p.iterdir())
    ]
    v.checks.append(Check("structure", not missing, f"missing/empty: {missing}" if missing else ""))
    if missing:
        return v
    v.checks.append(
        Check(
            "visible_test_files_exist",
            all((task.repo_dir / p).is_file() for p in s.visible_test_paths),
            "visible_test_paths missing",
        )
    )

    seed_visible = _visible_at_seed(task, executor)
    expected_ok = s.visible_tests_at_seed == "pass"
    v.checks.append(
        Check(
            "seed_visible_as_declared",
            seed_visible.ran and seed_visible.ok == expected_ok,
            f"declared {s.visible_tests_at_seed}, got ok={seed_visible.ok} ran={seed_visible.ran}",
        )
    )
    seed_hidden = score_hidden(task, task.repo_dir, executor, gate, s.max_seconds).hidden
    v.checks.append(
        Check(
            "seed_hidden_fails",
            seed_hidden.ran and seed_hidden.total > 0 and not seed_hidden.ok,
            "hidden tests (alone) must run and fail on the seed",
        )
    )

    with tempfile.TemporaryDirectory(prefix="tbv-ref-") as td:
        ref = Path(td) / "ref"
        copy_tree(task.repo_dir, ref)
        for f in task.reference_dir.rglob("*"):
            if f.is_file():
                dst = ref / f.relative_to(task.reference_dir)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, dst)
        start = time.monotonic()
        r1 = score_hidden(task, ref, executor, gate, s.max_seconds)
        elapsed = time.monotonic() - start
        r2 = score_hidden(task, ref, executor, gate, s.max_seconds)
    v.checks.append(Check("reference_passes_hidden_and_visible", r1.report.ok, r1.report.detail))
    same = (r1.report.passed, r1.report.failed, r1.report.errors) == (
        r2.report.passed,
        r2.report.failed,
        r2.report.errors,
    )
    v.checks.append(Check("deterministic", same, "two reference runs disagree"))
    v.checks.append(Check("resource_sanity", elapsed < s.max_seconds, f"{elapsed:.1f}s"))
    v.checks.append(_leak_check(task))
    return v


def write_reports(results: list[TaskValidation], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "validation.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["task_id", "valid", "failed_checks"])
        for r in results:
            w.writerow([r.task_id, r.valid, " | ".join(r.reasons)])
    n_ok = sum(r.valid for r in results)
    lines = [f"Validation: {n_ok} valid of {len(results)} tasks", ""]
    for r in results:
        lines.append(f"{'VALID  ' if r.valid else 'INVALID'} {r.task_id}")
        lines.extend(f"    - {reason}" for reason in r.reasons)
    (out_dir / "validation.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
