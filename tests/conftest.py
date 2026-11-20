import os
from pathlib import Path

import pytest

os.environ.setdefault("TBV_ALLOW_UNSAFE_LOCAL", "1")  # trusted fixtures only; see local_executor.py

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def example_tasks(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from tbv.suite.factory import expand_dir

    out = tmp_path_factory.mktemp("tasks")
    expand_dir(ROOT / "suite" / "specs", out)
    return out
