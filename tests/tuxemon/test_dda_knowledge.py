from pathlib import Path

import pytest

from tuxemon.dda import knowledge


@pytest.fixture
def mods_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(knowledge, "mods_folder", tmp_path)
    return tmp_path


def write_dda(mods_root: Path, text: str) -> None:
    mod_dir = mods_root / "campaign"
    mod_dir.mkdir()
    (mod_dir / "dda.yaml").write_text(text, encoding="utf-8")


def test_missing_file_disables_dda(mods_root: Path) -> None:
    assert knowledge.load_dda_enabled("campaign") is False


def test_enabled_true_turns_dda_on(mods_root: Path) -> None:
    write_dda(mods_root, "version: 1\nenabled: true\n")
    assert knowledge.load_dda_enabled("campaign") is True


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("version: 1\nenabled: [\n", id="invalid_yaml"),
        pytest.param(
            "version: 1\nenabled: true\nmode: fuzzy\n", id="unknown_key"
        ),
        pytest.param("version: 0\nenabled: true\n", id="unsupported_version"),
    ],
)
def test_invalid_file_disables_dda(mods_root: Path, text: str) -> None:
    write_dda(mods_root, text)
    assert knowledge.load_dda_enabled("campaign") is False
