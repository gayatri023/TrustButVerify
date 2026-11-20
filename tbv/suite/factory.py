"""Expand a compact YAML task spec into a full task directory (repo/, hidden_tests/, reference/)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_TASK_KEYS = [
    "id",
    "type",
    "difficulty",
    "tags",
    "instruction",
    "hidden_requirement",
    "tempting_shortcut",
    "visible_tests_at_seed",
    "test_command",
    "build_command",
    "lint_command",
    "expected_files",
    "generator_prompt_version",
    "protected_exceptions",
    "max_seconds",
]


def _write_files(base: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def expand_spec(spec: dict[str, Any], out_dir: Path) -> Path:
    """Write one task directory under out_dir/<id>/ and return its path."""
    root = out_dir / str(spec["id"])
    root.mkdir(parents=True, exist_ok=True)
    _write_files(root / "repo", {**spec.get("files", {}), **spec["visible_tests"]})
    _write_files(root / "hidden_tests", spec["hidden_tests"])
    _write_files(root / "reference", spec["reference"])
    meta = {k: spec[k] for k in _TASK_KEYS if k in spec}
    meta["visible_test_paths"] = sorted(spec["visible_tests"])
    (root / "task.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    return root


def expand_dir(specs_dir: Path, out_dir: Path) -> list[Path]:
    out: list[Path] = []
    for f in sorted(specs_dir.glob("*.yaml")):
        out.append(expand_spec(yaml.safe_load(f.read_text(encoding="utf-8")), out_dir))
    return out
