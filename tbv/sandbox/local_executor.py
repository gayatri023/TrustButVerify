"""TEST-ONLY executor: runs commands as plain subprocesses with NO isolation.

It exists so the validator, verifiers and gate can be unit-tested on trusted, handwritten fixtures
where Docker is unavailable. It refuses to run unless TBV_ALLOW_UNSAFE_LOCAL=1 is set, and model
written code must never be run through it (SECURITY.md, D-006).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from tbv.sandbox.base import CommandResult, cap

ENV_FLAG = "TBV_ALLOW_UNSAFE_LOCAL"


class LocalExecutor:
    def __init__(self) -> None:
        if os.environ.get(ENV_FLAG) != "1":
            raise RuntimeError(f"LocalExecutor is unsafe test tooling; set {ENV_FLAG}=1 to use it.")

    def run(
        self,
        workdir: Path,
        command: str,
        *,
        timeout: float,
        ro_mounts: dict[Path, str] | None = None,
    ) -> CommandResult:
        for host, container in (ro_mounts or {}).items():
            target = workdir / Path(container).relative_to("/workspace")
            shutil.copytree(host, target, dirs_exist_ok=True)
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(workdir),
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        start = time.monotonic()
        try:
            p = subprocess.run(
                ["sh", "-c", command],
                cwd=workdir,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                errors="replace",
            )
            out, t1 = cap(p.stdout)
            err, t2 = cap(p.stderr)
            return CommandResult(out, err, p.returncode, time.monotonic() - start, t1 or t2)
        except subprocess.TimeoutExpired:
            return CommandResult("", "timed out", 124, time.monotonic() - start, timed_out=True)
