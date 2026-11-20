"""Guard for the pre-registration discipline: no real experiment before PREREG.md is frozen."""

from __future__ import annotations

import re
from pathlib import Path

from tbv.core.config import REPO_ROOT

_STATUS = re.compile(r"^\s*Status:\s*(\w+)", re.MULTILINE)


def prereg_status(path: Path | None = None) -> str:
    """Return the value of the `Status:` line in PREREG.md (DRAFT or FROZEN), or MISSING."""
    p = path or REPO_ROOT / "docs" / "PREREG.md"
    if not p.exists():
        return "MISSING"
    m = _STATUS.search(p.read_text(encoding="utf-8"))
    return m.group(1).upper() if m else "MISSING"


def prereg_is_frozen(path: Path | None = None) -> bool:
    return prereg_status(path) == "FROZEN"
