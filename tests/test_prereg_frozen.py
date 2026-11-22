"""Tuning discipline enforced in CI: once PREREG is FROZEN, the gate config must still match its hash."""

import re

import pytest

from tbv.core.config import REPO_ROOT, config_hash, load_gate
from tbv.core.prereg import prereg_status


def test_frozen_prereg_matches_the_current_gate_config() -> None:
    if prereg_status() != "FROZEN":
        pytest.skip("PREREG is not frozen")
    text = (REPO_ROOT / "docs" / "PREREG.md").read_text(encoding="utf-8")
    m = re.search(r"Gate config hash.*?:\s*([0-9a-f]{64})", text)
    assert m, "frozen PREREG must record the gate config hash"
    assert m.group(1) == config_hash(load_gate()), (
        "config/gate.yaml changed after the pre-registration was frozen"
    )


def test_every_decision_in_a_frozen_prereg_is_decided() -> None:
    if prereg_status() != "FROZEN":
        pytest.skip("PREREG is not frozen")
    text = (REPO_ROOT / "docs" / "PREREG.md").read_text(encoding="utf-8")
    assert "Decision: ________" not in text
