"""Docker executor: one throwaway, locked-down container per command.

NOTE: written against the Docker SDK but not exercised in the authoring environment (no daemon).
`build_container_kwargs` is pure and unit-tested; the real security tests live in
tests/test_sandbox_docker.py (marked `docker`) and must pass on a machine with Docker.
"""

from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path
from typing import Any

from tbv.sandbox.base import OUTPUT_CAP_BYTES, CommandResult, cap

DEFAULT_IMAGE = "tbv-sandbox:latest"
LABEL = "tbv.sandbox"


def build_container_kwargs(
    workdir: Path,
    command: str,
    *,
    image: str = DEFAULT_IMAGE,
    cpus: float = 1.0,
    memory: str = "512m",
    pids: int = 128,
    ro_mounts: dict[Path, str] | None = None,
) -> dict[str, Any]:
    volumes: dict[str, dict[str, str]] = {str(workdir): {"bind": "/workspace", "mode": "rw"}}
    for host, container in (ro_mounts or {}).items():
        volumes[str(host)] = {"bind": container, "mode": "ro"}
    return {
        "image": image,
        "command": ["sh", "-c", command],
        "working_dir": "/workspace",
        "volumes": volumes,
        "network_mode": "none",
        "mem_limit": memory,
        "memswap_limit": memory,
        "nano_cpus": int(cpus * 1_000_000_000),
        "pids_limit": pids,
        "read_only": True,
        "tmpfs": {"/tmp": "rw,size=64m"},  # noqa: S108 - container-internal tmpfs
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges"],
        "user": "1000:1000",
        "environment": {
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "HOME": "/tmp",  # noqa: S108
        },
        "labels": {LABEL: "1"},
        "detach": True,
    }


def _world_writable(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            with contextlib.suppress(OSError):
                os.chmod(Path(dirpath) / name, 0o777)
    os.chmod(root, 0o777)


class DockerExecutor:
    def __init__(self, image: str = DEFAULT_IMAGE, client: Any | None = None) -> None:
        import docker

        self.image = image
        self.client = client or docker.from_env()

    def run(
        self,
        workdir: Path,
        command: str,
        *,
        timeout: float,
        ro_mounts: dict[Path, str] | None = None,
    ) -> CommandResult:
        _world_writable(workdir)
        kwargs = build_container_kwargs(workdir, command, image=self.image, ro_mounts=ro_mounts)
        start = time.monotonic()
        container = self.client.containers.run(**kwargs)
        timed_out = False
        try:
            try:
                status = container.wait(timeout=timeout)
                exit_code = int(status.get("StatusCode", 1))
            except Exception:  # noqa: BLE001 - wait() raises on timeout; kill the container
                timed_out = True
                exit_code = 124
                container.kill()
            out = container.logs(stdout=True, stderr=False, tail=2000)
            err = container.logs(stdout=False, stderr=True, tail=2000)
        finally:
            container.remove(force=True)
        so, t1 = cap(out.decode("utf-8", errors="replace")[-OUTPUT_CAP_BYTES * 2 :])
        se, t2 = cap(err.decode("utf-8", errors="replace")[-OUTPUT_CAP_BYTES * 2 :])
        return CommandResult(so, se, exit_code, time.monotonic() - start, t1 or t2, timed_out)

    def cleanup_leftovers(self) -> int:
        """Remove any container carrying our label (e.g. after a crash). Returns how many."""
        found = self.client.containers.list(all=True, filters={"label": LABEL})
        for c in found:
            c.remove(force=True)
        return len(found)
