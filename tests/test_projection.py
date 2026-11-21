import pytest

from tbv.experiment.projection import project


def test_projection_hand_computed() -> None:
    p = project([10, 20], [10_000, 20_000], [False, False], [], n_runs=100, rpd=500, tpm=16_000)
    assert p.requests == 1500 and p.days_at_rpd == 3
    assert p.minutes_at_tpm == pytest.approx(100 * 15_000 / 16_000)
    q = project([10, 10], [1000, 1000], [True, False], [4], n_runs=10, rpd=1000, tpm=None)
    assert q.requests == pytest.approx(10 * (10 + 0.5 * 4)) and q.retry_fraction == 0.5
    with pytest.raises(ValueError):
        project([], [], [], [], n_runs=1, rpd=1, tpm=None)
