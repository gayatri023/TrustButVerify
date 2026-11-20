"""Executor interface. Everything that runs a command goes through this one seam."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

OUTPUT_CAP_BYTES = 64 * 1024


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    stderr: str
    exit_code: int
    duration: float
    truncated: bool = False
    timed_out: bool = False


class Executor(Protocol):
    def run(
        self,
        workdir: Path,
        command: str,
        *,
        timeout: float,
        ro_mounts: dict[Path, str] | None = None,
    ) -> CommandResult:
        """Run `command` with `workdir` as /workspace; ro_mounts maps host dir -> container path."""
        ...


def cap(text: str, limit: int = OUTPUT_CAP_BYTES) -> tuple[str, bool]:
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= limit:
        return text, False
    return raw[:limit].decode("utf-8", errors="replace") + "\n[output truncated]", True
