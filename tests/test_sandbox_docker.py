"""Sandbox tests. The unit tests run anywhere; the `docker` tests need a daemon and the image
(`uv run tbv sandbox build`) and are the real security evidence. Run them in your Codespace."""

import shutil
import tempfile
from pathlib import Path

import pytest

from tbv.sandbox.docker_executor import DEFAULT_IMAGE, DockerExecutor, build_container_kwargs
from tbv.sandbox.preflight import check_docker


def test_container_kwargs_are_locked_down() -> None:
    kw = build_container_kwargs(
        Path("/tmp/ws"), "echo hi", ro_mounts={Path("/h"): "/workspace/hidden_tests"}
    )
    assert kw["network_mode"] == "none" and kw["read_only"] is True
    assert kw["cap_drop"] == ["ALL"] and "no-new-privileges" in kw["security_opt"]
    assert kw["user"] == "1000:1000" and kw["pids_limit"] <= 256 and kw["mem_limit"]
    assert kw["volumes"]["/h"]["mode"] == "ro"
    assert not any("docker.sock" in v for v in kw["volumes"])
    assert "privileged" not in kw


@pytest.fixture(scope="module")
def dx() -> DockerExecutor:
    res = check_docker()
    if not res.ok:
        pytest.skip(res.detail)
    ex = DockerExecutor()
    try:
        ex.client.images.get(DEFAULT_IMAGE)
    except Exception:  # noqa: BLE001
        pytest.skip("sandbox image missing: run `uv run tbv sandbox build`")
    return ex


@pytest.fixture
def ws() -> Path:
    d = Path(tempfile.mkdtemp(prefix="tbv-dx-"))
    yield d  # type: ignore[misc]
    shutil.rmtree(d, ignore_errors=True)


PY_NET = "python -c \"import socket; socket.create_connection(('1.1.1.1', 53), 3)\""


@pytest.mark.docker
def test_no_network(dx: DockerExecutor, ws: Path) -> None:
    assert dx.run(ws, PY_NET, timeout=20).exit_code != 0


@pytest.mark.docker
def test_runs_as_non_root(dx: DockerExecutor, ws: Path) -> None:
    assert dx.run(ws, "id -u", timeout=20).stdout.strip() == "1000"


@pytest.mark.docker
def test_cannot_write_outside_workspace(dx: DockerExecutor, ws: Path) -> None:
    assert dx.run(ws, "touch /etc/evil", timeout=20).exit_code != 0
    assert dx.run(ws, "touch /workspace/ok && echo fine", timeout=20).exit_code == 0


@pytest.mark.docker
def test_hidden_tests_not_visible_to_agent_container(dx: DockerExecutor, ws: Path) -> None:
    (ws / "a.py").write_text("x = 1\n")
    res = dx.run(
        ws, "find / -name 'hidden_tests' -not -path '/proc/*' 2>/dev/null | head", timeout=30
    )
    assert res.stdout.strip() == ""


@pytest.mark.docker
def test_infinite_loop_times_out(dx: DockerExecutor, ws: Path) -> None:
    res = dx.run(ws, "while true; do :; done", timeout=3)
    assert res.timed_out and res.duration < 30


@pytest.mark.docker
def test_fork_bomb_is_contained(dx: DockerExecutor, ws: Path) -> None:
    res = dx.run(ws, ":(){ :|:& };:; sleep 5", timeout=15)
    assert res.duration < 60  # the PID limit stops it; the container is killed on timeout


@pytest.mark.docker
def test_huge_output_is_truncated(dx: DockerExecutor, ws: Path) -> None:
    res = dx.run(ws, "head -c 200000000 /dev/zero | tr '\\0' 'a'", timeout=60)
    assert len(res.stdout) < 200_000 and res.truncated


@pytest.mark.docker
def test_no_docker_socket_and_no_leftovers(dx: DockerExecutor, ws: Path) -> None:
    assert dx.run(ws, "test -e /var/run/docker.sock", timeout=20).exit_code != 0
    assert dx.cleanup_leftovers() == 0
