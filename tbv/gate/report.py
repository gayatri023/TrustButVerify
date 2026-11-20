"""Three renderings of a GateReport: terminal (Rich), JSON, and a Markdown PR comment."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from tbv.core.models import ClaimVerdict, OverallVerdict
from tbv.gate.verdict import GateReport

OVERALL_SYMBOL = {
    OverallVerdict.PASS: "(+) PASS",
    OverallVerdict.WARN: "(!) WARN",
    OverallVerdict.BLOCK: "(x) BLOCK",
}
OVERALL_STYLE = {
    OverallVerdict.PASS: "green",
    OverallVerdict.WARN: "yellow",
    OverallVerdict.BLOCK: "red",
}
CLAIM_SYMBOL = {
    ClaimVerdict.VERIFIED: "(+) VERIFIED",
    ClaimVerdict.UNSUPPORTED: "(?) UNSUPPORTED",
    ClaimVerdict.CONTRADICTED: "(x) CONTRADICTED",
    ClaimVerdict.UNCHECKABLE: "(-) UNCHECKABLE",
}
PR_LIMIT = 4000


def render_terminal(report: GateReport, console: Console) -> None:
    style = OVERALL_STYLE[report.overall]
    console.print(
        Panel(
            f"[bold {style}]{OVERALL_SYMBOL[report.overall]}[/]  task {report.task_id}",
            title="TrustButVerify gate",
            subtitle=f"gate v{report.gate_version}",
        )
    )
    table = Table(title="Claims")
    for col in ("Claim", "Verdict", "Evidence"):
        table.add_column(col, overflow="fold")
    for cr in report.claims:
        hedge = " (hedged)" if cr.claim.polarity.value == "hedged" else ""
        table.add_row(
            f"{cr.claim.type.value}{hedge}: {cr.claim.text_span}",
            CLAIM_SYMBOL[cr.verdict],
            cr.reason,
        )
    console.print(table)
    if report.tamper:
        t = Table(title="Tamper findings")
        for col in ("Rule", "Severity", "Path", "Detail"):
            t.add_column(col, overflow="fold")
        for f in report.tamper:
            t.add_row(f.rule_id, f.severity.value.upper(), f.path, f.detail)
        console.print(t)
    for note in report.notes:
        console.print(f"  note: {note}")
    total = sum(v.runtime_s for v in report.verifiers)
    console.print(f"  gate time {report.gate_seconds:.2f}s (verifiers {total:.2f}s)")


def to_json(report: GateReport) -> str:
    return report.model_dump_json(indent=2)


def to_markdown(report: GateReport, limit: int = PR_LIMIT) -> str:
    def build(max_reason: int) -> str:
        n = {v: sum(c.verdict is v for c in report.claims) for v in ClaimVerdict}
        lines = [
            f"## TrustButVerify: {OVERALL_SYMBOL[report.overall]}",
            f"Task `{report.task_id}`. Claims: {n[ClaimVerdict.VERIFIED]} verified, "
            f"{n[ClaimVerdict.UNSUPPORTED]} unsupported, {n[ClaimVerdict.CONTRADICTED]} "
            f"contradicted, {n[ClaimVerdict.UNCHECKABLE]} uncheckable.",
            "",
        ]
        for cr in report.claims:
            span = cr.claim.text_span[:100].replace("`", "'")
            lines += [
                f"<details><summary>{CLAIM_SYMBOL[cr.verdict]} {cr.claim.type.value}: "
                f"{span}</summary>",
                "",
                cr.reason[:max_reason],
                "",
                "</details>",
            ]
        if report.tamper:
            lines += ["", "### Tamper findings"]
            lines += [
                f"- {f.severity.value.upper()} {f.rule_id} `{f.path}`: {f.detail[:max_reason]}"
                for f in report.tamper[:15]
            ]
        lines += [f"- {n_}" for n_ in report.notes[:3]]
        lines += [
            "",
            "### How to reproduce",
            "`tbv verify --transcript <transcript.jsonl> --workspace <final-workspace>`",
            f"_gate v{report.gate_version}, schema {report.schema_version}_",
        ]
        return "\n".join(lines)

    for max_reason in (400, 200, 100, 40):
        text = build(max_reason)
        if len(text) <= limit:
            return text
    return text[: limit - 20] + "\n[truncated]"
