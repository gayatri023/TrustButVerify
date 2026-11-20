"""DEV/TEST split: stratified by task type, deterministic, and frozen once written."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path

import yaml

from tbv.core.models import Split
from tbv.suite.task import Task


def make_splits(
    tasks: list[Task], n_test: int, seed: str = "tbv-splits-v1"
) -> dict[str, list[str]]:
    by_type: dict[str, list[Task]] = defaultdict(list)
    for t in tasks:
        by_type[t.spec.type.value].append(t)
    total = len(tasks)
    test: list[str] = []
    for _, group in sorted(by_type.items()):
        group.sort(key=lambda t: hashlib.sha256(f"{seed}:{t.spec.id}".encode()).hexdigest())
        k = max(1, round(n_test * len(group) / total)) if n_test else 0
        test += [t.spec.id for t in group[:k]]
    test = sorted(test)[:n_test] if len(test) > n_test else sorted(test)
    dev = sorted(t.spec.id for t in tasks if t.spec.id not in set(test))
    return {"dev": dev, "test": test}


def write_splits(path: Path, splits: dict[str, list[str]]) -> None:
    if path.exists() and yaml.safe_load(path.read_text(encoding="utf-8")).get("frozen"):
        raise RuntimeError(f"{path} is frozen; splits must never change after creation")
    path.write_text(yaml.safe_dump({"frozen": True, **splits}, sort_keys=False), encoding="utf-8")


def load_splits(path: Path) -> dict[str, Split]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, Split] = {}
    for tid in data.get("dev", []):
        out[tid] = Split.DEV
    for tid in data.get("test", []):
        out[tid] = Split.TEST
    return out
