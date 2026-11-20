"""One call that runs the whole gate on a finished run: claims -> verifiers -> verdict."""

from __future__ import annotations

import time
from pathlib import Path

from tbv.agents.types import Transcript
from tbv.core.config import GateConfig
from tbv.core.models import ClaimType
from tbv.gate.claims import LLM, Extraction, extract_claims
from tbv.gate.verdict import GateReport, judge
from tbv.gate.verifiers import (
    VerifierResult,
    VerifyContext,
    v1_test_rerun,
    v2_trace_check,
    v3_build_lint,
    v4_files_diff,
    v5_tamper,
    v6_regression,
)
from tbv.sandbox.base import Executor
from tbv.sandbox.scoring import run_visible_tests
from tbv.suite.task import PublicTask


def run_gate(
    public: PublicTask,
    transcript: Transcript,
    seed_dir: Path,
    final_dir: Path,
    executor: Executor,
    gate: GateConfig,
    final_message: str,
    llm: LLM | None = None,
    extraction: Extraction | None = None,
) -> GateReport:
    """`public` is a PublicTask: this function has no way to reach hidden tests or hidden notes."""
    t0 = time.monotonic()
    ext = extraction or extract_claims(final_message, llm)
    ctx = VerifyContext(public, transcript, seed_dir, final_dir, executor, gate)
    v1, final_report = v1_test_rerun(ctx)
    baseline = None
    if public.test_command:
        baseline, _ = run_visible_tests(executor, seed_dir, public.test_command, ctx.timeout)
    claimed_files = [
        c.target for c in ext.claims if c.type is ClaimType.FILE_CREATED_OR_CHANGED and c.target
    ]
    v5, findings = v5_tamper(ctx)
    results: list[VerifierResult] = [
        v1,
        v2_trace_check(ctx),
        v3_build_lint(ctx),
        v4_files_diff(ctx, claimed_files),
        v5,
        v6_regression(baseline, final_report),
    ]
    return judge(
        ext.claims,
        results,
        findings,
        task_id=public.id,
        gate_version=gate.version,
        gate_seconds=round(time.monotonic() - t0, 3),
        extraction_method=ext.method,
    )
