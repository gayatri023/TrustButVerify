from pathlib import Path

from tbv.core.prereg import prereg_is_frozen, prereg_status


def test_status_parsing(tmp_path: Path) -> None:
    p = tmp_path / "PREREG.md"
    assert prereg_status(p) == "MISSING"
    p.write_text("# x\nStatus: DRAFT\n")
    assert prereg_status(p) == "DRAFT" and not prereg_is_frozen(p)
    p.write_text("# x\nStatus: FROZEN\n")
    assert prereg_is_frozen(p)
    p.write_text("# no status line here\n")
    assert prereg_status(p) == "MISSING"


def test_repo_prereg_has_a_status() -> None:
    assert prereg_status() in {"DRAFT", "FROZEN"}
