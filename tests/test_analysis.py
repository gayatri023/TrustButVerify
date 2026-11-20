import math
from pathlib import Path

import pytest

from tbv.analysis import metrics as m
from tbv.analysis.report_html import build_html
from tbv.analysis.stats import (
    bootstrap_ci,
    breakeven_fcr,
    cluster_bootstrap_ratio,
    mcnemar_exact,
    net_minutes_saved,
    wilson,
)


def test_wilson_hand_computed() -> None:
    zero = wilson(0, 20)  # upper bound = z^2 / (n + z^2) = 3.84146 / 23.84146
    assert zero.lo == 0 and zero.hi == pytest.approx(0.16113, abs=1e-4)
    half = wilson(10, 20)
    assert (half.lo, half.hi) == (pytest.approx(0.2993, abs=1e-3), pytest.approx(0.7007, abs=1e-3))
    assert wilson(0, 0).n == 0 and math.isnan(wilson(0, 0).lo)
    assert wilson(73, 73).hi == pytest.approx(1.0)


def test_wilson_sample_size_claim_in_prereg() -> None:
    # PREREG decision 6: with zero events, n >= 73 is needed for an upper bound under 5%.
    assert wilson(0, 72).hi > 0.05 > wilson(0, 73).hi


def test_mcnemar_exact_hand_computed() -> None:
    assert mcnemar_exact(0, 5) == pytest.approx(2 / 32)
    assert mcnemar_exact(1, 5) == pytest.approx(14 / 64)
    assert mcnemar_exact(3, 3) == 1.0 and mcnemar_exact(0, 0) == 1.0


def test_breakeven_hand_computed() -> None:
    p = breakeven_fcr(recall=0.8, far=0.1, minutes_fc=30, minutes_fa=10)
    assert p == pytest.approx(0.04)
    assert net_minutes_saved(p, 0.8, 0.1, 30, 10) == pytest.approx(0.0, abs=1e-9)
    assert net_minutes_saved(0.5, 0.8, 0.1, 30, 10, gate_minutes=1) == pytest.approx(
        0.5 * 0.8 * 30 - 0.5 * 0.1 * 10 - 1
    )


def test_bootstrap_constant_and_cluster() -> None:
    assert bootstrap_ci([2.0] * 10) == (2.0, 2.0)
    rows = [("t1", 1, 2), ("t1", 1, 2), ("t2", 1, 2)]  # every cluster has ratio 0.5
    lo, hi = cluster_bootstrap_ratio(rows, lambda r: r[0], lambda r: r[1], lambda r: r[2])
    assert lo == pytest.approx(0.5) and hi == pytest.approx(0.5)


def row(
    task: str,
    correct: bool,
    gate: str | None,
    attempt: int = 1,
    status: str = "finished",
    tax: str | None = None,
    agent: str = "A",
    fixture: bool = False,
) -> m.Row:
    return m.Row(
        agent,
        task,
        0,
        attempt,
        "dev",
        "seeded_bug",
        status,
        status == "finished",
        gate,
        correct,
        False,
        tax,
        0.5,
        10,
        5,
        1.0,
        fixture,
    )


def _rows() -> list[m.Row]:
    fc = [("f1", "BLOCK"), ("f2", "BLOCK"), ("f3", "WARN"), ("f4", "PASS")]
    ok = [
        ("c1", "BLOCK"),
        ("c2", "WARN"),
        ("c3", "PASS"),
        ("c4", "PASS"),
        ("c5", "PASS"),
        ("c6", "PASS"),
    ]
    rows = [row(t, False, g, tax="tampered" if t == "f1" else "unsupported_claim") for t, g in fc]
    rows += [row(t, True, g) for t, g in ok]
    rows += [
        row("x1", False, None, status="budget_exhausted"),
        row("x2", False, None, status="error"),
    ]  # no claim: excluded from every denominator
    rows += [
        row("f1", True, "PASS", attempt=2),
        row("f2", False, "BLOCK", attempt=2),
        row("c1", True, "PASS", attempt=2),
    ]
    return rows


def test_metrics_hand_computed() -> None:
    r = _rows()
    assert (m.fcr(r).k, m.fcr(r).n) == (4, 10)
    assert (m.gate_recall(r, True).k, m.gate_recall(r, True).n) == (3, 4)
    assert (m.gate_recall(r, False).k, m.gate_recall(r, False).n) == (2, 4)
    assert (m.false_alarm_rate(r, False).k, m.false_alarm_rate(r, False).n) == (1, 6)
    assert (m.false_alarm_rate(r, True).k, m.false_alarm_rate(r, True).n) == (2, 6)
    assert (m.residual_fcr(r).k, m.residual_fcr(r).n) == (1, 5)  # PASS runs: f4 + c3..c6
    res = m.retry_rescue(r)
    assert (res.blocked, res.blocked_fc, res.rescued) == (3, 2, 1)
    assert (res.b, res.c) == (1, 0) and res.p_mcnemar == 1.0
    assert res.pass_after_retry_among_blocked.k == 2 and res.pass_after_retry_among_blocked.n == 3
    tax = m.taxonomy(r)
    assert tax["tampered"].k == 1 and tax["unsupported_claim"].k == 3


def test_html_report_banner_and_mixing_guard(tmp_path: Path) -> None:
    from tbv.experiment.store import Store

    db = tmp_path / "r.sqlite"
    st = Store(db)
    base = dict(
        agent="a",
        task="t",
        repeat=0,
        attempt=1,
        split="dev",
        task_type="seeded_bug",
        difficulty="easy",
        status="finished",
        claimed_done=1,
        completed_correctly=0,
        gate_overall="PASS",
        gate_seconds=0.1,
        tampered=0,
        fixture=1,
    )
    st.insert("runs", base)
    assert "SYNTHETIC FIXTURE DATA" in build_html(db)
    st.insert("runs", {**base, "task": "t2", "fixture": 0})
    with pytest.raises(ValueError, match="mixes fixture and real"):
        build_html(db)
