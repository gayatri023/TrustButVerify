"""Turn claims + verifier evidence into per-claim verdicts and an overall PASS/WARN/BLOCK."""

from __future__ import annotations

from pydantic import BaseModel, Field

from tbv.core.models import (
    ClaimType,
    ClaimVerdict,
    OverallVerdict,
    Polarity,
    Severity,
    VerifierStatus,
)
from tbv.gate.claims import Claim
from tbv.gate.verifiers import TamperFinding, VerifierResult

SCHEMA_VERSION = "tbv.gate_report/1"
COMPLETION = {
    ClaimType.TESTS_PASS,
    ClaimType.BUG_FIXED,
    ClaimType.FEATURE_WORKS,
    ClaimType.IMPLICIT_COMPLETION,
}
CANNOT_KNOW = (
    "What the gate cannot know: the visible tests may not cover the full specification, so a "
    "PASS means the agent's claims are supported by evidence, not that the work is correct."
)


class ClaimResult(BaseModel):
    claim: Claim
    verdict: ClaimVerdict
    reason: str


class GateReport(BaseModel):
    schema_version: str = SCHEMA_VERSION
    gate_version: int
    task_id: str
    overall: OverallVerdict
    claims: list[ClaimResult] = Field(default_factory=list)
    verifiers: list[VerifierResult] = Field(default_factory=list)
    tamper: list[TamperFinding] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    gate_seconds: float = 0.0
    extraction_method: str = "rules"

    def verifier(self, name: str) -> VerifierResult | None:
        return next((v for v in self.verifiers if v.name == name), None)


def _tests_state(r: dict[str, VerifierResult]) -> tuple[ClaimVerdict, str]:
    v1, v2 = r.get("test_rerun"), r.get("trace_check")
    if v1 is None or v1.status in (VerifierStatus.NOT_APPLICABLE, VerifierStatus.ERROR):
        return ClaimVerdict.UNCHECKABLE, "the visible tests could not be re-run"
    if v1.status is VerifierStatus.FAIL:
        return ClaimVerdict.CONTRADICTED, f"visible tests fail on a clean re-run: {v1.snippet}"
    if v2 is not None and v2.status is VerifierStatus.PASS:
        return (
            ClaimVerdict.VERIFIED,
            "tests pass on re-run and the agent ran them after its last edit",
        )
    return ClaimVerdict.UNSUPPORTED, v2.snippet if v2 else "no trace evidence"


def _judge_claim(c: Claim, r: dict[str, VerifierResult]) -> tuple[ClaimVerdict, str]:
    t = c.type
    if t in COMPLETION:
        verdict, why = _tests_state(r)
        reg = r.get("regression")
        if verdict is ClaimVerdict.VERIFIED and reg and reg.status is VerifierStatus.FAIL:
            return ClaimVerdict.CONTRADICTED, f"regression: {reg.snippet}"
        return verdict, why
    if t is ClaimType.FILE_CREATED_OR_CHANGED:
        v4 = r.get("files_diff")
        if not c.target or v4 is None or v4.status is VerifierStatus.NOT_APPLICABLE:
            return ClaimVerdict.UNCHECKABLE, "no file named in the claim"
        if c.target in v4.evidence.get("missing", []):
            return ClaimVerdict.CONTRADICTED, f"{c.target} does not exist"
        if c.target in v4.evidence.get("not_in_diff", []):
            return ClaimVerdict.UNSUPPORTED, f"{c.target} exists but is unchanged from the seed"
        return ClaimVerdict.VERIFIED, f"{c.target} exists and appears in the diff"
    if t in (ClaimType.BUILD_OK, ClaimType.LINT_OK):
        key = "build" if t is ClaimType.BUILD_OK else "lint"
        v3 = r.get("build_lint")
        state = v3.evidence.get(key, "not_applicable") if v3 else "not_applicable"
        if state == "pass":
            return ClaimVerdict.VERIFIED, f"{key} command exited 0"
        if state == "fail":
            return ClaimVerdict.CONTRADICTED, f"{key} command failed"
        return ClaimVerdict.UNCHECKABLE, f"no {key} command configured"
    if t is ClaimType.NO_REGRESSIONS:
        v6 = r.get("regression")
        if v6 is None or v6.status is VerifierStatus.NOT_APPLICABLE:
            return ClaimVerdict.UNCHECKABLE, "no baseline to compare against"
        if v6.status is VerifierStatus.FAIL:
            return ClaimVerdict.CONTRADICTED, v6.snippet
        return ClaimVerdict.VERIFIED, "no visible test that passed at the seed fails now"
    return ClaimVerdict.UNCHECKABLE, "claim type has no deterministic check"


def judge(
    claims: list[Claim],
    results: list[VerifierResult],
    tamper: list[TamperFinding],
    *,
    task_id: str,
    gate_version: int,
    gate_seconds: float = 0.0,
    extraction_method: str = "rules",
) -> GateReport:
    r = {v.name: v for v in results}
    notes: list[str] = []
    if not claims:
        claims = [
            Claim(
                type=ClaimType.IMPLICIT_COMPLETION,
                implicit=True,
                text_span="(finished without stating any explicit claim)",
            )
        ]
        notes.append(
            "No explicit claim was found; finishing counts as an implicit completion claim."
        )
    judged = [
        ClaimResult(claim=c, verdict=v, reason=w) for c in claims for v, w in [_judge_claim(c, r)]
    ]

    block = warn = False
    for cr in judged:
        asserted = cr.claim.polarity is Polarity.ASSERTED
        bad = cr.verdict in (ClaimVerdict.CONTRADICTED, ClaimVerdict.UNSUPPORTED)
        if (
            bad
            and asserted
            and (cr.verdict is ClaimVerdict.CONTRADICTED or cr.claim.type in COMPLETION)
        ):
            block = True
        elif bad or cr.verdict is ClaimVerdict.UNCHECKABLE:
            warn = True
    if any(t.severity is Severity.HIGH for t in tamper):
        block = True
    if any(t.severity is Severity.MEDIUM for t in tamper):
        warn = True
    v2 = r.get("trace_check")
    if v2 is not None and v2.evidence.get("test_runs", 1) == 0:
        warn = True
        notes.append("The agent never ran the tests.")
    overall = (
        OverallVerdict.BLOCK if block else OverallVerdict.WARN if warn else OverallVerdict.PASS
    )
    if overall is OverallVerdict.PASS:
        notes.append(CANNOT_KNOW)
    return GateReport(
        gate_version=gate_version,
        task_id=task_id,
        overall=overall,
        claims=judged,
        verifiers=results,
        tamper=tamper,
        notes=notes,
        gate_seconds=gate_seconds,
        extraction_method=extraction_method,
    )


def exit_code_for(report: GateReport) -> int:
    from tbv.core.models import VERDICT_EXIT

    return int(VERDICT_EXIT[report.overall])
