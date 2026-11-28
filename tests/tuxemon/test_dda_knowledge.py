from pathlib import Path

import pytest

from tuxemon.dda import knowledge
from tuxemon.dda.types import FuzzyTerms

VALID_DDA_YAML = """\
version: 1
enabled: true
fuzzy:
  centroid_steps: 100
  rules:
    - name: player_low_opponent_low
      player: low
      opponent: low
      pressure: moderate
    - name: player_low_opponent_moderate
      player: low
      opponent: moderate
      pressure: high
    - name: player_low_opponent_high
      player: low
      opponent: high
      pressure: high
    - name: player_moderate_opponent_low
      player: moderate
      opponent: low
      pressure: low
    - name: both_moderate
      player: moderate
      opponent: moderate
      pressure: moderate
    - name: player_moderate_opponent_high
      player: moderate
      opponent: high
      pressure: high
    - name: player_high_opponent_low
      player: high
      opponent: low
      pressure: low
    - name: player_high_opponent_moderate
      player: high
      opponent: moderate
      pressure: low
    - name: both_high
      player: high
      opponent: high
      pressure: moderate
"""


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


def test_enabled_settings_load_fuzzy_rules(mods_root: Path) -> None:
    write_dda(mods_root, VALID_DDA_YAML)

    settings = knowledge.load_dda_settings("campaign")

    assert settings.enabled is True
    assert settings.fuzzy is not None
    assert settings.fuzzy.rules[0].player is FuzzyTerms.LOW
    assert settings.fuzzy.centroid_steps == 100
    assert knowledge.load_dda_enabled("campaign") is True


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("version: 1\nenabled: [\n", id="invalid_yaml"),
        pytest.param(
            "version: 1\nenabled: true\nmode: fuzzy\n", id="unknown_key"
        ),
        pytest.param("version: 2\nenabled: false\n", id="unsupported_version"),
        pytest.param(
            "version: 1\nenabled: true\n", id="enabled_without_fuzzy_rules"
        ),
        pytest.param(
            VALID_DDA_YAML.replace(
                "    - name: player_high_opponent_moderate\n"
                "      player: high\n"
                "      opponent: moderate\n"
                "      pressure: low\n",
                "",
            ),
            id="incomplete_rule_coverage",
        ),
        pytest.param(
            VALID_DDA_YAML.replace("player: moderate", "player: impossible"),
            id="unknown_fuzzy_term",
        ),
        pytest.param(
            VALID_DDA_YAML.replace(
                "    - name: both_moderate\n",
                "    - name: both_moderate\n"
                "      player: low\n"
                "      opponent: low\n"
                "      pressure: high\n"
                "    - name: both_moderate\n",
            ),
            id="duplicate_rule_name",
        ),
    ],
)
def test_invalid_file_disables_dda(mods_root: Path, text: str) -> None:
    write_dda(mods_root, text)
    settings = knowledge.load_dda_settings("campaign")
    assert settings.enabled is False
    assert knowledge.load_dda_enabled("campaign") is False


def test_legacy_config_defaults_to_disabled_observation(mods_root: Path) -> None:
    write_dda(mods_root, VALID_DDA_YAML)
    assert knowledge.load_dda_settings("campaign").mode == "disabled"
