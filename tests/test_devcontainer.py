import json
from pathlib import Path

CFG = Path(__file__).resolve().parents[1] / ".devcontainer" / "devcontainer.json"


def test_devcontainer_is_valid_json_and_has_docker() -> None:
    data = json.loads(CFG.read_text(encoding="utf-8"))
    assert any("docker-in-docker" in f for f in data["features"])
    assert "3.12" in data["image"]
