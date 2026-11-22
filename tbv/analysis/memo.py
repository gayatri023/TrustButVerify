"""Decision memo (HTML): applies the pre-registered decision rules to the measured data.

Everything numeric comes from results.sqlite. Fixture data is stamped SYNTHETIC. Nothing here is typed
by hand except fixed wording, thresholds that come from docs/PREREG.md, and clearly labelled limits."""

from __future__ import annotations

import html
from pathlib import Path

from tbv.analysis import metrics as m
from tbv.analysis.report_html import ASSUME_MIN_FA, ASSUME_MIN_FC, CSS
from tbv.analysis.stats import Proportion, breakeven_fcr

H2_RECALL_THRESHOLD = 0.50  # PREREG H2: below this, lead with the residual failures
H3_FALSE_ALARM_TARGET = 0.05  # PREREG H3: target false-alarm rate (BLOCK only)


def _p(x: Proportion) -> str:
    return html.escape(x.fmt())


def _verdict_h2(rec: Proportion) -> str:
    if not rec.n:
        return "No false completions occurred, so recall cannot be computed."
    if rec.p < H2_RECALL_THRESHOLD:
        return (
            f"NOT SUPPORTED (point estimate {100 * rec.p:.0f}% is below 50%). Per the pre-registered "
            "rule, the residual failures lead this memo and a v2 check derived from the task "
            "spec is the next step."
        )
    note = " The interval includes values below 50%." if rec.lo < H2_RECALL_THRESHOLD else ""
    return f"SUPPORTED on the point estimate ({100 * rec.p:.0f}% is at least 50%).{note}"


def _verdict_h3(far: Proportion) -> str:
    if not far.n:
        return "No correct completions occurred, so the false-alarm rate cannot be computed."
    ok = far.p <= H3_FALSE_ALARM_TARGET
    cant = (
        f" The 95% upper bound ({100 * far.hi:.0f}%) is above 5%, so these data cannot rule out "
        "a higher false-alarm rate."
        if far.hi > H3_FALSE_ALARM_TARGET
        else ""
    )
    return f"{'MET' if ok else 'NOT MET'} on the point estimate ({100 * far.p:.0f}% vs a 5% target).{cant}"


def _split_block(rows: list[m.Row], label: str) -> str:
    if not m.finished(rows):
        return f"<h2>{label}</h2><p class='mut'>No finished runs in this split.</p>"
    fc, rec, far = m.fcr(rows), m.gate_recall(rows, True), m.false_alarm_rate(rows, False)
    resid, resc = m.residual_fcr(rows), m.retry_rescue(rows)
    tax = m.taxonomy(rows)
    per_agent = "".join(
        f"<tr><td>{html.escape(a)}</td><td>{_p(m.fcr(v))}</td></tr>"
        for a, v in m.group_by(rows, lambda r: r.agent).items()
    )
    tax_rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{_p(v)}</td></tr>" for k, v in tax.items()
    )
    return (
        f"<h2>{label}</h2><h3>H1: false-completion rate (no threshold)</h3><p>{_p(fc)}</p>"
        f"<table><tr><th>Agent</th><th>False-completion rate</th></tr>{per_agent}</table>"
        f"<h3>H2: the gate catches most false completions (recall of at least 50%)</h3>"
        f"<p>Recall (WARN or BLOCK): {_p(rec)}<br>BLOCK only: {_p(m.gate_recall(rows, False))}</p>"
        f"<p><b>{_verdict_h2(rec)}</b></p>"
        f"<h3>H3: the gate rarely blocks correct work (false alarms of at most 5%)</h3>"
        f"<p>False-alarm rate (BLOCK only): {_p(far)}<br>WARN or BLOCK: "
        f"{_p(m.false_alarm_rate(rows, True))}</p><p><b>{_verdict_h3(far)}</b></p>"
        f"<h3>H4: one evidence-guided retry rescues blocked runs</h3>"
        f"<p>Blocked runs: {resc.blocked}; blocked false completions: {resc.blocked_fc}; rescued: "
        f"{resc.rescued}. Rescue rate: {_p(resc.rate_among_blocked_fc)}. Paired exact McNemar "
        f"p = {resc.p_mcnemar:.3f} (b={resc.b}, c={resc.c}).</p>"
        f"<h3>What the gate cannot see (residual failures)</h3>"
        f"<p>Residual false-completion rate among runs the gate passed: {_p(resid)}.</p>"
        f"<h3>Failure taxonomy</h3><table><tr><th>Type</th><th>Share of false completions</th></tr>"
        f"{tax_rows}</table>"
    )


def _recommendation(rows: list[m.Row]) -> str:
    rec, far = m.gate_recall(rows, True), m.false_alarm_rate(rows, False)
    fc = m.fcr(rows)
    if not (rec.n and far.n and fc.n):
        return "Not enough false and correct completions in this sample to make a recommendation."
    p_star = breakeven_fcr(rec.p, far.p, ASSUME_MIN_FC, ASSUME_MIN_FA)
    above = fc.p > p_star
    return (
        f"With the measured recall ({100 * rec.p:.0f}%) and false-alarm rate ({100 * far.p:.0f}%), and the "
        f"labelled assumptions of {ASSUME_MIN_FC:.0f} minutes per missed false completion and "
        f"{ASSUME_MIN_FA:.0f} minutes per needless block, the break-even false-completion rate is "
        f"{100 * p_star:.1f}%. The measured rate ({100 * fc.p:.0f}%) is "
        f"{'ABOVE' if above else 'BELOW'} it, so on these assumptions a default gate "
        f"{'would save reviewer time' if above else 'would not pay for itself'} for agents like these. "
        "The minutes are assumptions, not measurements."
    )


def _bullets(rows: list[m.Row]) -> str:
    f = m.finished(rows)
    if not f:
        return ""
    tasks = len({r.task for r in m.base(rows)})
    agents = len({r.agent for r in m.base(rows)})
    fc, rec, far, resc = (
        m.fcr(rows),
        m.gate_recall(rows, True),
        m.false_alarm_rate(rows, False),
        m.retry_rescue(rows),
    )
    return (
        "<ul>"
        f"<li>Built a verification gate for coding agents (Python, Docker, Gemini API) and a "
        f"{tasks}-task validated suite; measured a {100 * fc.p:.0f}% false-completion rate across "
        f"{agents} agent configuration(s) (95% CI {100 * fc.lo:.0f}-{100 * fc.hi:.0f}%, n={fc.n}).</li>"
        f"<li>The gate flagged {100 * rec.p:.0f}% of false completions (n={rec.n}) at a "
        f"{100 * far.p:.0f}% false-alarm rate (n={far.n}); one evidence-guided retry rescued "
        f"{100 * resc.rate_among_blocked_fc.p:.0f}% of blocked false completions "
        f"(n={resc.blocked_fc}).</li></ul>"
        if rec.n and far.n and resc.blocked_fc
        else "<p class='mut'>Resume bullets need at least one false completion, one correct completion "
        "and one blocked false completion in the data.</p>"
    )


def build_memo(db: Path | str, title: str = "TrustButVerify: decision memo") -> str:
    rows = m.load_rows(db)
    fixtures = {r.fixture for r in rows}
    if len(fixtures) > 1:
        raise ValueError("database mixes fixture and real rows; refusing to build a memo")
    banner = (
        '<div class="banner">SYNTHETIC FIXTURE DATA: scripted agents, not results.</div>'
        if True in fixtures
        else ""
    )
    models = sorted({r.agent for r in rows})
    sections = "".join(
        _split_block([r for r in rows if r.split == s], lbl)
        for s, lbl in (("dev", "DEV split"), ("test", "TEST split (evaluated once, frozen config)"))
    )
    return (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
        f"content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title>"
        f"<style>{CSS}</style></head><body>{banner}<h1>{html.escape(title)}</h1>"
        f"<p class='mut'>{len(m.base(rows))} base runs; agents: {html.escape(', '.join(models))}. "
        "Results are specific to this task suite and these agent configurations. This is a pilot-scale "
        "study; intervals are wide and the memo says so wherever it matters.</p>"
        f"<h2>Recommendation</h2><p>{_recommendation([r for r in rows if r.split == 'dev'] or rows)}</p>"
        f"{sections}<h2>Resume bullets (generated from the numbers above)</h2>{_bullets(rows)}"
        "<h2>Limitations</h2><ul><li>Small custom suite (written by an AI assistant, reviewed by "
        "automated validation only; no human task review yet).</li><li>Small free-tier models in a "
        "minimal tool loop: the false-completion rate says nothing about frontier coding agents.</li>"
        "<li>Claims were extracted by deterministic rules; their recall on paraphrased claims is "
        "unmeasured, and no human labelling was done.</li><li>The gate's heuristics were designed from "
        "examples and not tuned on this data; their precision is unmeasured.</li><li>Runs on one task "
        "are correlated; per-agent intervals are Wilson intervals and treat runs as independent.</li>"
        "<li>No developer study was run, so there is no evidence about how people use the evidence "
        "view.</li></ul></body></html>"
    )


def write_memo(db: Path | str, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_memo(db), encoding="utf-8")
    return out
