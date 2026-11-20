"""Statistics with no heavy dependencies. Every function has a hand-computed test."""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

Z95 = 1.959963984540054


@dataclass(frozen=True)
class Proportion:
    k: int
    n: int
    lo: float
    hi: float

    @property
    def p(self) -> float:
        return self.k / self.n if self.n else float("nan")

    def fmt(self) -> str:
        if self.n == 0:
            return "n/a (n=0)"
        ci = f"95% CI {100 * self.lo:.1f}-{100 * self.hi:.1f}%"
        return f"{100 * self.p:.1f}% ({self.k}/{self.n}; {ci})"


def wilson(k: int, n: int, z: float = Z95) -> Proportion:
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return Proportion(0, 0, float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return Proportion(k, n, max(0.0, centre - half), min(1.0, centre + half))


def bootstrap_ci(
    values: Sequence[float],
    stat: Callable[[Sequence[float]], float] = lambda v: sum(v) / len(v),
    n_boot: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float]:
    if not values:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    n = len(values)
    stats = sorted(stat([values[rng.randrange(n)] for _ in range(n)]) for _ in range(n_boot))
    return stats[int(n_boot * alpha / 2)], stats[min(n_boot - 1, int(n_boot * (1 - alpha / 2)))]


def cluster_bootstrap_ratio[T](
    rows: Sequence[T],
    cluster: Callable[[T], str],
    num: Callable[[T], int],
    den: Callable[[T], int],
    n_boot: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """CI for sum(num)/sum(den), resampling whole clusters (tasks): runs on a task correlate."""
    groups: dict[str, list[T]] = {}
    for r in rows:
        groups.setdefault(cluster(r), []).append(r)
    keys = sorted(groups)
    if not keys:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    vals: list[float] = []
    for _ in range(n_boot):
        picked = [groups[keys[rng.randrange(len(keys))]] for _ in keys]
        d = sum(den(r) for g in picked for r in g)
        if d:
            vals.append(sum(num(r) for g in picked for r in g) / d)
    if not vals:
        return float("nan"), float("nan")
    vals.sort()
    return vals[int(len(vals) * alpha / 2)], vals[
        min(len(vals) - 1, int(len(vals) * (1 - alpha / 2)))
    ]


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the discordant counts b and c."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return float(min(1.0, 2 * tail))


def breakeven_fcr(recall: float, far: float, minutes_fc: float, minutes_fa: float) -> float:
    """False-completion rate p* above which the gate saves time: p*r*M_fc = (1-p*)*f*M_fa."""
    num = far * minutes_fa
    den = recall * minutes_fc + num
    return num / den if den else float("nan")


def net_minutes_saved(
    p_fc: float,
    recall: float,
    far: float,
    minutes_fc: float,
    minutes_fa: float,
    gate_minutes: float = 0.0,
) -> float:
    """Expected minutes saved per task by gating (assumption-driven; see docs/METRICS.md)."""
    return p_fc * recall * minutes_fc - (1 - p_fc) * far * minutes_fa - gate_minutes
