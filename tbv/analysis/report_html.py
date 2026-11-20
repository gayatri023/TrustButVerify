"""Self-contained HTML results page (inline CSS and SVG, no scripts, works offline).

Fixture data is stamped SYNTHETIC on every page; a page can never mix fixture and real rows."""

from __future__ import annotations

import html
from pathlib import Path

from tbv.analysis import metrics as m
from tbv.analysis.stats import Proportion, breakeven_fcr, net_minutes_saved

ASSUME_MIN_FC = 30.0  # ASSUMPTION: minutes lost to an undetected false completion
ASSUME_MIN_FA = 10.0  # ASSUMPTION: minutes lost to a needless block

CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--mut:#666;--card:#f5f5f7;--bar:#3b6fd4;--bad:#b3261e;--line:#ddd}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--fg:#eee;--mut:#aaa;--card:#222;
--bar:#7aa2f7;--bad:#f2867b;--line:#444}}
body{background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;max-width:920px;
margin:0 auto;padding:16px}h1{font-size:1.6rem}h2{margin-top:2rem;border-bottom:1px solid var(--line)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}
.card{background:var(--card);border-radius:10px;padding:12px}.big{font-size:1.5rem;font-weight:600}
.mut{color:var(--mut);font-size:.9rem}.banner{background:var(--bad);color:#fff;padding:12px;
border-radius:8px;font-weight:600}table{border-collapse:collapse;width:100%;display:block;
overflow-x:auto}td,th{border-bottom:1px solid var(--line);padding:6px 10px;text-align:left}
svg text{fill:var(--fg);font-size:12px}
"""


def _bars(items: list[tuple[str, Proportion]]) -> str:
    if not items:
        return '<p class="mut">No data.</p>'
    h, w = 28 * len(items) + 10, 640
    out = [
        f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="bar chart with 95% CIs">'
    ]
    for i, (label, p) in enumerate(items):
        y = 6 + i * 28
        out.append(f'<text x="0" y="{y + 14}">{html.escape(label[:22])}</text>')
        if p.n:
            x0, span = 170, 330
            out.append(
                f'<rect x="{x0}" y="{y + 2}" width="{span * p.p:.1f}" height="16" fill="var(--bar)"/>'
            )
            out.append(
                f'<line x1="{x0 + span * p.lo:.1f}" x2="{x0 + span * p.hi:.1f}" y1="{y + 10}" '
                f'y2="{y + 10}" stroke="var(--fg)" stroke-width="2"/>'
            )
            out.append(f'<text x="{x0 + span + 8}" y="{y + 14}">{100 * p.p:.0f}% (n={p.n})</text>')
        else:
            out.append(f'<text x="170" y="{y + 14}">n=0</text>')
    return "".join(out) + "</svg>"


def _card(title: str, p: Proportion, note: str = "") -> str:
    big = "n/a" if p.n == 0 else f"{100 * p.p:.1f}%"
    return (
        f'<div class="card"><div class="mut">{html.escape(title)}</div><div class="big">{big}</div>'
        f'<div class="mut">{html.escape(p.fmt())}</div><div class="mut">{html.escape(note)}</div></div>'
    )


def _section(rows: list[m.Row], label: str) -> str:
    if not rows:
        return f"<h2>{label}</h2><p class='mut'>No runs in this split.</p>"
    resc = m.retry_rescue(rows)
    secs, ci, n = m.gate_cost(rows)
    out = [
        f"<h2>{label}</h2><div class='cards'>",
        _card("False-completion rate (north star)", m.fcr(rows), "claimed done, tests fail"),
        _card(
            "Gate recall (WARN or BLOCK)", m.gate_recall(rows, True), "false completions flagged"
        ),
        _card("Gate recall (BLOCK only)", m.gate_recall(rows, False)),
        _card(
            "False-alarm rate (BLOCK only)",
            m.false_alarm_rate(rows, False),
            "correct completions blocked",
        ),
        _card("False-alarm rate (WARN or BLOCK)", m.false_alarm_rate(rows, True)),
        _card("Residual FCR after gate", m.residual_fcr(rows), "false completions among PASS"),
        _card(
            "Retry rescue (blocked false completions)",
            resc.rate_among_blocked_fc,
            f"McNemar exact p={resc.p_mcnemar:.3f} on {resc.blocked} blocked",
        ),
        _card("Tamper rate", m.tamper_rate(rows)),
        "</div>",
    ]
    out.append("<h3>False-completion rate by agent</h3>")
    out.append(_bars([(k, m.fcr(v)) for k, v in m.group_by(rows, lambda r: r.agent).items()]))
    out.append("<h3>False-completion rate by task type</h3>")
    out.append(_bars([(k, m.fcr(v)) for k, v in m.group_by(rows, lambda r: r.task_type).items()]))
    out.append("<h3>Failure taxonomy (share of false completions)</h3>")
    out.append(_bars(list(m.taxonomy(rows).items())))
    out.append(
        f"<h3>Cost and latency</h3><p>Gate time per finished run: {secs:.2f}s "
        f"(95% CI {ci[0]:.2f}-{ci[1]:.2f}s, n={n}).</p>"
    )
    return "".join(out)


def _breakeven(rows: list[m.Row]) -> str:
    rec, far = m.gate_recall(rows, True), m.false_alarm_rate(rows, False)
    if not rec.n or not far.n:
        return "<h2>Break-even</h2><p class='mut'>Needs both false completions and correct completions.</p>"
    p_star = breakeven_fcr(rec.p, far.p, ASSUME_MIN_FC, ASSUME_MIN_FA)
    head = "".join(f"<th>FCR {int(f * 100)}%</th>" for f in (0.05, 0.1, 0.2, 0.4, 0.6))
    body = ""
    for mf in (15.0, 30.0, 60.0):
        cells = "".join(
            f"<td>{net_minutes_saved(f, rec.p, far.p, mf, ASSUME_MIN_FA):+.1f}</td>"
            for f in (0.05, 0.1, 0.2, 0.4, 0.6)
        )
        body += f"<tr><td>{mf:.0f} min per missed false completion</td>{cells}</tr>"
    return (
        f"<h2>Break-even (assumption-driven)</h2><p>Using the measured recall "
        f"({100 * rec.p:.0f}%) and false-alarm rate ({100 * far.p:.0f}%), and the ASSUMPTIONS "
        f"{ASSUME_MIN_FC:.0f} min lost per undetected false completion and {ASSUME_MIN_FA:.0f} min "
        f"per needless block, the gate saves time when the false-completion rate exceeds "
        f"{100 * p_star:.1f}%. Minutes saved per task:</p><table><tr><th></th>{head}</tr>{body}"
        f"</table><p class='mut'>Minutes are assumptions, not measurements.</p>"
    )


def build_html(db: Path | str, title: str = "TrustButVerify results") -> str:
    rows = m.load_rows(db)
    fixtures = {r.fixture for r in rows}
    if len(fixtures) > 1:
        raise ValueError("database mixes fixture and real rows; refusing to build a report")
    fixture = bool(fixtures and True in fixtures)
    banner = (
        '<div class="banner">SYNTHETIC FIXTURE DATA: produced by scripted agents to demonstrate '
        "the pipeline. These are NOT results.</div>"
        if fixture
        else ""
    )
    sections = []
    for split, label in (
        ("dev", "DEV split (used for tuning)"),
        ("test", "TEST split (evaluated once)"),
    ):
        sections.append(_section([r for r in rows if r.split == split], label))
    n_runs = len(m.base(rows))
    scope = (
        "Results are specific to this task suite and these agent configurations; they say "
        "nothing about coding agents in general."
    )
    return (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
        f"content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title>"
        f"<style>{CSS}</style></head><body>{banner}<h1>{html.escape(title)}</h1>"
        f"<p class='mut'>{n_runs} base runs. {scope}</p>{''.join(sections)}"
        f"{_breakeven([r for r in rows if r.split == 'dev'] or rows)}"
        f"<h2>Limitations</h2><ul><li>Small custom suite, partly AI-drafted; see the data card."
        f"</li><li>Intervals are Wilson 95%; runs on one task are correlated.</li>"
        f"<li>The gate cannot see hidden requirements the visible tests miss.</li></ul>"
        f"</body></html>"
    )


def write_html(db: Path | str, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(db), encoding="utf-8")
    return out
