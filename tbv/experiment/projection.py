"""Dry-run projection: from a few real runs to the requests and time of the full matrix."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Projection:
    n_runs: int
    requests: float
    days_at_rpd: float
    minutes_at_tpm: float | None
    retry_fraction: float


def project(
    steps: list[int],
    tokens_in: list[int],
    retried: list[bool],
    retry_steps: list[int],
    n_runs: int,
    rpd: int,
    tpm: int | None,
) -> Projection:
    """Each list holds one entry per sampled attempt-1 run (retry_steps: per retried run)."""
    if not steps:
        raise ValueError("no sampled runs to project from")
    avg_steps = sum(steps) / len(steps)
    retry_frac = sum(retried) / len(retried)
    avg_retry_steps = sum(retry_steps) / len(retry_steps) if retry_steps else 0.0
    per_run = avg_steps + retry_frac * avg_retry_steps
    requests = n_runs * per_run
    total_tokens = (
        n_runs * (sum(tokens_in) / len(tokens_in)) * (per_run / avg_steps if avg_steps else 1)
    )
    minutes = total_tokens / tpm if tpm else None
    return Projection(
        n_runs, requests, math.ceil(requests / rpd) if rpd else float("nan"), minutes, retry_frac
    )
