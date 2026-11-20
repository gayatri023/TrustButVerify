"""Startup check for the Docker daemon. Nothing in TBV runs model-written code without it."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    detail: str


def check_docker() -> PreflightResult:
    try:
        import docker
        from docker.errors import DockerException
    except ImportError:
        return PreflightResult(False, "the 'docker' Python package is not installed")
    try:
        client = docker.from_env()
        client.ping()
        version = client.version().get("Version", "unknown")
    except DockerException as exc:
        return PreflightResult(False, f"Docker daemon not reachable: {exc}")
    except Exception as exc:  # noqa: BLE001 - any failure here means "not usable"
        return PreflightResult(False, f"Docker check failed: {exc}")
    return PreflightResult(True, f"Docker daemon reachable (engine {version})")
