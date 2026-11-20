import pytest
from docker.errors import DockerException

from tbv.sandbox import preflight


def test_unreachable_daemon_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> None:
        raise DockerException("no daemon")

    monkeypatch.setattr("docker.from_env", boom)
    res = preflight.check_docker()
    assert not res.ok and "not reachable" in res.detail


def test_reachable_daemon_is_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    class Fake:
        def ping(self) -> bool:
            return True

        def version(self) -> dict[str, str]:
            return {"Version": "99.0"}

    monkeypatch.setattr("docker.from_env", lambda: Fake())
    res = preflight.check_docker()
    assert res.ok and "99.0" in res.detail


@pytest.mark.docker
def test_real_docker_if_available() -> None:
    res = preflight.check_docker()
    if not res.ok:
        pytest.skip(res.detail)
    assert res.ok
